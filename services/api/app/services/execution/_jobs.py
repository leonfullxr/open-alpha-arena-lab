from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from app.db.models import (
    Account as AccountRow,
)
from app.db.models import (
    AgentRun,
    Competition,
    DecisionRound,
    InvocationAttempt,
    InvocationResult,
    MarketQuote,
    MarketSnapshot,
    QuoteSet,
    RiskEvaluation,
    RoundAgentJob,
    TradeProposal,
)
from app.db.models import (
    Position as PositionRow,
)
from app.engine.finance import Action, EngineResult, FinanceError, Quote, apply_action
from app.llm.schema import ProposalBatch, ProposalOutputError, parse_proposal_output
from app.services.execution._context import (
    _account,
    _Context,
    _instruments,
    _normalize_timestamp,
    _parse_json,
    _rules,
    _string_list,
    _timedelta_seconds,
    _timestamp_seconds,
    _transaction,
)
from app.services.execution._effects import (
    _append_event,
    _persist_account_and_equity,
    _persist_engine_result,
    _sync_position_rows,
)
from app.services.execution._protection import _apply_triggers
from app.services.execution._receipts import ExecutionReceipt
from app.services.reconciliation import reconcile_ledger
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def execute_job(
    db: Session,
    job_id: str,
    fence: int,
    quote_set_id: str,
) -> ExecutionReceipt:
    """Apply one timely provider result and ledger effects in a fenced transaction.

    Provider I/O is deliberately absent. Lock order is competition, job, account, then
    positions ordered by symbol. The whole proposal batch commits atomically and a committed
    terminal job is an idempotent no-op on later executor passes.
    """
    with _transaction(db):
        replay = _terminal_replay(db, job_id, fence)
        if replay is not None:
            return replay
        context = _load_context(db, job_id, fence, quote_set_id)
        if context.job.state != "RESPONDED":
            raise ValueError("job result is not ready for paper execution")
        if db.scalar(
            select(func.count()).select_from(TradeProposal).where(TradeProposal.job_id == job_id)
        ):
            raise RuntimeError("responded job already contains executed proposals")
        if context.competition.state != "RUNNING" or context.competition.kill_switch:
            context.job.state = "TERMINAL"
            context.job.terminal_result = "SKIPPED_PAUSED"
            context.job.error_code = "COMPETITION_STOPPED"
            return ExecutionReceipt(
                job_id, context.account_row.id, context.job.terminal_result, 0, 0, 0, False
            )

        ledger_clean = reconcile_ledger(db, competition_id=context.competition.id).balanced
        protective_count = _apply_protective_exits(db, context)
        try:
            batch = parse_proposal_output(context.output)
        except ProposalOutputError:
            _persist_account_and_equity(db, context)
            context.job.state = "TERMINAL"
            context.job.terminal_result = "PROVIDER_ERROR"
            context.job.error_code = "INVALID_PROPOSAL_OUTPUT"
            _append_event(
                db,
                context.competition,
                account_id=context.account_row.id,
                event_type="agent.error",
                payload={"agent_id": context.job.agent_run_id, "reason": "INVALID_PROPOSAL_OUTPUT"},
                at=context.now,
            )
            return ExecutionReceipt(
                job_id,
                context.account_row.id,
                context.job.terminal_result,
                0,
                0,
                protective_count,
                False,
            )

        accepted, rejected = _apply_proposals(
            db, context, batch, allow_new_entries=ledger_clean
        )
        _persist_account_and_equity(db, context)
        context.job.state = "TERMINAL"
        context.job.terminal_result = "SUCCESS" if rejected == 0 else "RISK_REJECTED"
        context.job.error_code = None if rejected == 0 else "RISK_REJECTED"
        context.job.lease_owner = None
        context.job.lease_expires_at = None
        return ExecutionReceipt(
            job_id,
            context.account_row.id,
            context.job.terminal_result,
            accepted,
            rejected,
            protective_count,
            False,
        )


def _load_context(db: Session, job_id: str, fence: int, quote_set_id: str) -> _Context:
    competition = db.scalar(
        select(Competition)
        .join(DecisionRound, DecisionRound.competition_id == Competition.id)
        .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
        .where(RoundAgentJob.id == job_id)
        .with_for_update(of=Competition)
    )
    if competition is None:
        raise LookupError("job not found")
    round_row = db.scalar(
        select(DecisionRound)
        .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
        .where(RoundAgentJob.id == job_id)
        .with_for_update(of=DecisionRound)
    )
    if round_row is None:
        raise RuntimeError("job round is missing")
    job = db.scalar(select(RoundAgentJob).where(RoundAgentJob.id == job_id).with_for_update())
    if job is None or job.fence != fence:
        raise ValueError("job fence is stale")
    agent = db.get(AgentRun, job.agent_run_id)
    if round_row is None or agent is None or agent.competition_id != competition.id:
        raise RuntimeError("job execution context is incomplete")
    attempt = db.scalar(
        select(InvocationAttempt).where(InvocationAttempt.job_id == job.id).with_for_update()
    )
    if attempt is None or attempt.fence != fence:
        raise ValueError("job has no matching invocation attempt")
    result = db.scalar(select(InvocationResult).where(InvocationResult.attempt_id == attempt.id))
    if result is None or result.late or result.error_code is not None:
        raise ValueError("job has no timely successful provider result")
    rules_json = _parse_json(competition.rules_bytes)
    symbols = tuple(_string_list(rules_json.get("symbols")))
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("competition symbol universe is invalid")
    rules = _rules(rules_json)
    snapshot = db.get(MarketSnapshot, round_row.snapshot_id)
    if snapshot is None:
        raise ValueError("round snapshot is unavailable")
    account_row = db.scalar(
        select(AccountRow).where(AccountRow.agent_run_id == agent.id).with_for_update()
    )
    if account_row is None:
        raise RuntimeError("agent account is missing")
    position_rows = tuple(
        db.scalars(
            select(PositionRow)
            .where(PositionRow.account_id == account_row.id, PositionRow.state == "OPEN")
            .order_by(PositionRow.symbol)
            .with_for_update()
        ).all()
    )
    now = db.scalar(select(func.now()))
    if now is None:
        raise RuntimeError("database time is unavailable")
    now = _normalize_timestamp(now)
    if _normalize_timestamp(round_row.deadline_at) > now:
        raise ValueError("round execution deadline has not arrived")
    if round_row.execution_quote_set_id is None:
        candidate = db.get(QuoteSet, quote_set_id)
        if candidate is None:
            raise LookupError("execution quote set not found")
        captured_at = _normalize_timestamp(candidate.captured_at)
        if (
            captured_at < _normalize_timestamp(round_row.deadline_at)
            or captured_at > now
            or _timedelta_seconds(now - captured_at) > rules.max_quote_age_seconds
        ):
            raise ValueError("round execution quote set is not post-deadline and fresh")
        round_row.execution_quote_set_id = candidate.id
        db.flush()
    else:
        quote_set_id = round_row.execution_quote_set_id
    quote_set = db.get(QuoteSet, quote_set_id)
    if quote_set is None:
        raise LookupError("execution quote set not found")
    quote_rows = tuple(
        db.scalars(
            select(MarketQuote)
            .where(MarketQuote.quote_set_id == quote_set_id)
            .order_by(MarketQuote.symbol)
        ).all()
    )
    row_by_symbol = {row.symbol: row for row in quote_rows}
    selected = [row_by_symbol[symbol] for symbol in symbols if symbol in row_by_symbol]
    ages = [now - _normalize_timestamp(row.source_at) for row in selected]
    source_times = [_normalize_timestamp(row.source_at) for row in selected]
    skew = max(source_times) - min(source_times) if source_times else timedelta.max
    quote_trusted = (
        quote_set.complete
        and len(selected) == len(symbols)
        and bool(ages)
        and all(age >= timedelta(0) for age in ages)
        and _timedelta_seconds(max(ages)) <= rules.max_quote_age_seconds
        and _timedelta_seconds(skew) <= rules.max_quote_skew_seconds
    )
    instruments, instrument_max_leverage = _instruments(snapshot.canonical_bytes, symbols, rules)
    quotes = {
        row.symbol: Quote(
            row.symbol,
            row.bid,
            row.ask,
            row.mark,
            _timedelta_seconds(now - _normalize_timestamp(row.source_at)),
            _timestamp_seconds(_normalize_timestamp(row.source_at)),
        )
        for row in selected
    }
    account = _account(account_row, position_rows, competition.initial_balance)
    return _Context(
        competition,
        job,
        round_row,
        account_row,
        account,
        position_rows,
        rules,
        symbols,
        instruments,
        instrument_max_leverage,
        quotes,
        quote_trusted,
        quote_set_id,
        now,
        result.output_bytes,
    )


def _terminal_replay(db: Session, job_id: str, fence: int) -> ExecutionReceipt | None:
    competition = db.scalar(
        select(Competition)
        .join(DecisionRound, DecisionRound.competition_id == Competition.id)
        .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
        .where(RoundAgentJob.id == job_id)
        .with_for_update(of=Competition)
    )
    if competition is None:
        raise LookupError("job not found")
    round_row = db.scalar(
        select(DecisionRound)
        .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
        .where(RoundAgentJob.id == job_id)
        .with_for_update(of=DecisionRound)
    )
    if round_row is None:
        raise RuntimeError("job round is missing")
    job = db.scalar(select(RoundAgentJob).where(RoundAgentJob.id == job_id).with_for_update())
    if job is None or job.fence != fence:
        raise ValueError("job fence is stale")
    if job.state != "TERMINAL":
        return None
    agent = db.get(AgentRun, job.agent_run_id)
    if agent is None:
        raise RuntimeError("job agent is missing")
    account = db.scalar(select(AccountRow).where(AccountRow.agent_run_id == agent.id))
    if account is None:
        raise RuntimeError("agent account is missing")
    return ExecutionReceipt(
        job.id,
        account.id,
        job.terminal_result or "TERMINAL",
        0,
        0,
        0,
        True,
    )


def _apply_protective_exits(db: Session, context: _Context) -> int:
    before = set(context.account.positions)
    count, context.account, context.positions = _apply_triggers(
        db,
        competition=context.competition,
        account_row=context.account_row,
        account=context.account,
        positions=context.positions,
        rules=context.rules,
        instruments=context.instruments,
        quotes=context.quotes,
        quote_set_id=context.quote_set_id,
        now=context.now,
    )
    context.protectively_closed_symbols.update(before - set(context.account.positions))
    return count


def _apply_proposals(
    db: Session,
    context: _Context,
    batch: ProposalBatch,
    *,
    allow_new_entries: bool,
) -> tuple[int, int]:
    accepted = rejected = 0
    seen_symbols: set[str] = set()
    symbol_order = {symbol: index for index, symbol in enumerate(context.symbols)}
    ordered = sorted(
        enumerate(batch.proposals),
        key=lambda item: (symbol_order.get(item[1].symbol, len(symbol_order)), item[0]),
    )
    for source_sequence, proposal in ordered:
        proposal_id = str(uuid.uuid4())
        reasons: list[str] = []
        engine_result: EngineResult | None = None
        key = f"proposal:{context.job.id}:{source_sequence}"
        db.add(
            TradeProposal(
                id=proposal_id,
                job_id=context.job.id,
                sequence=source_sequence,
                action=proposal.action.value,
                symbol=proposal.symbol,
                quantity=proposal.quantity,
                raw_bytes=context.output,
            )
        )
        db.flush()
        if proposal.action.value in {"OPEN_LONG", "OPEN_SHORT"} and not allow_new_entries:
            reasons.append("account ledger reconciliation is dirty; new entries are blocked")
        elif proposal.symbol not in context.symbols:
            reasons.append("symbol outside frozen competition universe")
        elif proposal.symbol in context.protectively_closed_symbols:
            reasons.append("symbol closed by a protective order in this batch")
        elif proposal.symbol in seen_symbols:
            reasons.append("duplicate symbol proposal")
        elif not context.quote_trusted:
            reasons.append("shared execution quote set is incomplete or stale")
        else:
            seen_symbols.add(proposal.symbol)
            instrument = context.instruments[proposal.symbol]
            quote = context.quotes[proposal.symbol]
            max_leverage = min(
                context.rules.max_leverage,
                Decimal(context.instrument_max_leverage[proposal.symbol]),
            )
            if proposal.leverage > max_leverage:
                reasons.append("leverage exceeds frozen instrument maximum")
            else:
                try:
                    action = Action(proposal.action.value)
                    engine_result = apply_action(
                        context.account,
                        action=action,
                        symbol=proposal.symbol,
                        quantity=proposal.quantity,
                        leverage=proposal.leverage,
                        quote=quote,
                        instrument=instrument,
                        rules=context.rules,
                        stop_loss=proposal.stop_loss,
                        take_profit=proposal.take_profit,
                        idempotency_key=key,
                        current_quotes=context.quotes,
                        current_instruments=context.instruments,
                        as_of=context.now.date(),
                    )
                except FinanceError as exc:
                    reasons.append(str(exc))
        accepted_now = not reasons
        db.add(
            RiskEvaluation(
                id=str(uuid.uuid4()),
                proposal_id=proposal_id,
                decision="ACCEPTED" if accepted_now else "REJECTED",
                reasons=reasons,
                policy_version=f"{context.competition.profile}:frozen-v1",
            )
        )
        _append_event(
            db,
            context.competition,
            account_id=context.account_row.id,
            event_type="agent.decision",
            payload={
                "agent_id": context.job.agent_run_id,
                "action": proposal.action.value,
                "symbol": proposal.symbol,
                "quantity": str(proposal.quantity),
                "risk": "ACCEPTED" if accepted_now else "REJECTED",
                "reason": reasons[0] if reasons else None,
            },
            at=context.now,
        )
        if accepted_now and engine_result is not None:
            _persist_engine_result(
                db,
                engine_result,
                account_id=context.account_row.id,
                proposal_id=proposal_id,
                idempotency_key=key,
                kind="MARKET",
                executed_at=context.now,
                quote_set_id=context.quote_set_id,
                event_sequence=context.competition.event_seq,
            )
            context.account = engine_result.account
            _sync_positions(db, context, proposal.symbol)
            accepted += 1
        else:
            rejected += 1
    return accepted, rejected


def _sync_positions(db: Session, context: _Context, changed_symbol: str) -> None:
    context.positions = _sync_position_rows(
        db,
        context.account_row.id,
        context.positions,
        context.account,
        changed_symbol,
        context.now,
    )

