from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.db.models import (
    Account as AccountRow,
)
from app.db.models import (
    AgentRun,
    Competition,
    DecisionRound,
    DomainEvent,
    EquitySample,
    InvocationAttempt,
    InvocationResult,
    LedgerJournal,
    LedgerPosting,
    MarketQuote,
    MarketSnapshot,
    Order,
    QuoteSet,
    RiskEvaluation,
    RoundAgentJob,
    TradeProposal,
)
from app.db.models import (
    Fill as FillRow,
)
from app.db.models import (
    Position as PositionRow,
)
from app.engine.finance import (
    Account,
    Action,
    EngineResult,
    FinanceError,
    Instrument,
    Position,
    Quote,
    Rules,
    Side,
    apply_action,
    equity,
    rules_from_config,
    unrealized_pnl,
)
from app.llm.schema import ProposalBatch, ProposalOutputError, parse_proposal_output
from app.services.reconciliation import reconcile_ledger
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    job_id: str
    account_id: str
    state: str
    accepted_proposals: int
    rejected_proposals: int
    protective_exits: int
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class ProtectionCycleReceipt:
    checked_accounts: int
    protective_exits: int


@dataclass(slots=True)
class _Context:
    competition: Competition
    job: RoundAgentJob
    round: DecisionRound
    account_row: AccountRow
    account: Account
    positions: tuple[PositionRow, ...]
    rules: Rules
    symbols: tuple[str, ...]
    instruments: dict[str, Instrument]
    instrument_max_leverage: dict[str, int]
    quotes: dict[str, Quote]
    quote_trusted: bool
    quote_set_id: str
    now: datetime
    output: bytes
    protectively_closed_symbols: set[str] = field(default_factory=set)


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

        ledger_clean = reconcile_ledger(
            db, competition_id=context.competition.id
        ).balanced
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
    if job.lease_expires_at is None or _normalize_timestamp(job.lease_expires_at) <= now:
        raise ValueError("executor job lease expired")
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


def run_protective_exit_cycle(db: Session, *, quote_set_id: str) -> ProtectionCycleReceipt:
    """Apply protective orders independently from model responses."""
    from app.services.execution_protection import run_protective_exit_cycle as run_cycle

    receipt = run_cycle(db, quote_set_id=quote_set_id)
    return ProtectionCycleReceipt(receipt.checked_accounts, receipt.protective_exits)


def _apply_protective_exits(db: Session, context: _Context) -> int:
    from app.services.execution_protection import apply_context_protection

    before = set(context.account.positions)
    count, context.account, context.positions = apply_context_protection(db, context)
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


def _persist_engine_result(
    db: Session,
    result: EngineResult,
    *,
    account_id: str,
    proposal_id: str | None,
    idempotency_key: str,
    kind: str,
    executed_at: datetime,
    quote_set_id: str,
    event_sequence: int,
) -> Order | None:
    if not result.fills:
        return None
    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        account_id=account_id,
        proposal_id=proposal_id,
        idempotency_key=idempotency_key,
        kind=kind,
        status="FILLED",
        quote_set_id=quote_set_id,
        event_sequence=event_sequence,
    )
    db.add(order)
    db.flush()
    for ordinal, fill in enumerate(result.fills):
        db.add(
            FillRow(
                id=str(uuid.uuid4()),
                order_id=order_id,
                symbol=fill.symbol,
                side=fill.side.value,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                executed_at=executed_at,
                ordinal=ordinal,
            )
        )
    journal_id = str(uuid.uuid4())
    db.add(LedgerJournal(id=journal_id, account_id=account_id, event_key=idempotency_key))
    db.flush()
    db.add_all(
        [
            LedgerPosting(
                id=str(uuid.uuid4()),
                journal_id=journal_id,
                bucket=posting.bucket,
                amount=posting.amount,
            )
            for posting in result.postings
        ]
    )
    return order


def _sync_positions(db: Session, context: _Context, changed_symbol: str) -> None:
    context.positions = _sync_position_rows(
        db,
        context.account_row.id,
        context.positions,
        context.account,
        changed_symbol,
        context.now,
    )


def _sync_position_rows(
    db: Session,
    account_id: str,
    positions: tuple[PositionRow, ...],
    account: Account,
    changed_symbol: str,
    now: datetime,
) -> tuple[PositionRow, ...]:
    row_by_symbol = {row.symbol: row for row in positions if row.state == "OPEN"}
    simulated = account.positions
    position = simulated.get(changed_symbol)
    row = row_by_symbol.get(changed_symbol)
    if position is None:
        if row is not None:
            row.state = "CLOSED"
            row.closed_at = now
        return positions
    if row is None:
        row = PositionRow(
            id=str(uuid.uuid4()),
            account_id=account_id,
            symbol=changed_symbol,
            side=position.side.value,
            quantity=position.quantity,
            average_entry=position.average_entry,
            reserved_margin=position.reserved_margin,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            state="OPEN",
            opened_at=now,
        )
        db.add(row)
        return (*positions, row)
    row.side = position.side.value
    row.quantity = position.quantity
    row.average_entry = position.average_entry
    row.reserved_margin = position.reserved_margin
    row.stop_loss = position.stop_loss
    row.take_profit = position.take_profit
    row.state = "OPEN"
    return positions


def _persist_account_and_equity(db: Session, context: _Context) -> None:
    account = context.account
    account_row = context.account_row
    _persist_account_row(account_row, account)
    if not context.quote_trusted:
        return
    marks = {symbol: quote.mark for symbol, quote in context.quotes.items()}
    current_equity = equity(account, context.quotes, context.instruments)
    unrealized = sum(
        (
            unrealized_pnl(position, marks[symbol], context.instruments[symbol].contract_multiplier)
            for symbol, position in account.positions.items()
        ),
        Decimal("0"),
    )
    db.add(
        EquitySample(
            id=str(uuid.uuid4()),
            account_id=account_row.id,
            round_index=context.round.round_index,
            logical_at=context.round.logical_at,
            equity=current_equity,
            realized_pnl=account.realized_pnl,
            unrealized_pnl=unrealized,
            fees=account.fees,
            funding=account.funding,
        )
    )


def _persist_account_row(account_row: AccountRow, account: Account) -> None:
    account_row.cash = account.cash
    account_row.realized_pnl = account.realized_pnl
    account_row.fees = account.fees
    account_row.funding = account.funding
    account_row.reserved_margin = account.reserved_margin
    account_row.halted = account.halted
    account_row.peak_equity = account.peak_equity
    account_row.daily_baseline_equity = account.daily_baseline_equity
    account_row.risk_day = account.risk_day
    account_row.version += 1


def _append_event(
    db: Session,
    competition: Competition,
    *,
    account_id: str | None,
    event_type: str,
    payload: dict[str, Any],
    at: datetime,
) -> None:
    competition.event_seq += 1
    db.add(
        DomainEvent(
            id=str(uuid.uuid4()),
            competition_id=competition.id,
            sequence=competition.event_seq,
            account_id=account_id,
            event_type=event_type,
            payload=payload,
            event_at=at,
        )
    )


def _account(
    row: AccountRow, positions: tuple[PositionRow, ...], initial_balance: Decimal
) -> Account:
    initial = initial_balance
    peak = initial
    return Account(
        initial_balance=initial,
        cash=row.cash,
        positions={
            position.symbol: Position(
                position.symbol,
                Side(position.side),
                position.quantity,
                position.average_entry,
                position.reserved_margin,
                position.stop_loss,
                position.take_profit,
            )
            for position in positions
        },
        realized_pnl=row.realized_pnl,
        fees=row.fees,
        funding=row.funding,
        halted=row.halted,
        peak_equity=row.peak_equity or peak,
        daily_baseline_equity=row.daily_baseline_equity or initial,
        risk_day=row.risk_day,
    )


def _rules(data: dict[str, Any]) -> Rules:
    return rules_from_config(data)


def _instruments(
    snapshot_bytes: bytes, symbols: tuple[str, ...], rules: Rules
) -> tuple[dict[str, Instrument], dict[str, int]]:
    payload = _parse_json(snapshot_bytes)
    raw_instruments = payload.get("instruments", [])
    specs: dict[str, tuple[int, int]] = {}
    if isinstance(raw_instruments, list):
        for item in raw_instruments:
            if isinstance(item, dict) and isinstance(item.get("symbol"), str):
                decimals = item.get("size_decimals")
                max_leverage = item.get("max_leverage")
                if (
                    isinstance(decimals, int)
                    and not isinstance(decimals, bool)
                    and 0 <= decimals <= 18
                    and isinstance(max_leverage, int)
                    and not isinstance(max_leverage, bool)
                    and max_leverage >= 1
                ):
                    specs[item["symbol"]] = (decimals, max_leverage)
    instruments: dict[str, Instrument] = {}
    max_leverages: dict[str, int] = {}
    for symbol in symbols:
        decimals, max_leverage = specs.get(symbol, (6, int(rules.max_leverage)))
        step = Decimal(1).scaleb(-decimals)
        instruments[symbol] = Instrument(symbol, quantity_step=step, min_quantity=step)
        max_leverages[symbol] = max_leverage
    return instruments, max_leverages


def _parse_json(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("stored canonical JSON is invalid") from None
    if not isinstance(value, dict):
        raise ValueError("stored canonical JSON has an invalid shape")
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("competition symbol universe is invalid")
    return value


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timedelta_seconds(value: Any) -> Decimal:
    return Decimal(value.days * 86400 + value.seconds) + Decimal(value.microseconds) / Decimal(
        1_000_000
    )


def _timestamp_seconds(value: datetime) -> Decimal:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return _timedelta_seconds(_normalize_timestamp(value) - epoch)


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return
    with db.begin():
        yield
