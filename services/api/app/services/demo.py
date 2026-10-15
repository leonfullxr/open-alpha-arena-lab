from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path

from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import Account as AccountRow
from app.db.models import (
    AgentRun,
    Competition,
    DecisionRound,
    DomainEvent,
    EquitySample,
    Fill,
    InvocationAttempt,
    InvocationResult,
    LedgerJournal,
    LedgerPosting,
    MarketQuote,
    MarketSnapshot,
    Order,
    Position,
    PromptVersion,
    QuoteSet,
    RiskEvaluation,
    RoundAgentJob,
    TradeProposal,
)
from app.engine.finance import (
    Account,
    Action,
    EngineResult,
    FinanceError,
    Instrument,
    Quote,
    Rules,
    apply_action,
    equity,
    rules_from_config,
    unrealized_pnl,
)
from app.llm.inputs import build_agent_request_bytes, build_user_input
from app.llm.providers import OPENAI_CHAT_URL, ProviderConfig
from app.llm.schema import ProposalBatch, parse_proposal_output
from sqlalchemy import select
from sqlalchemy.orm import Session

NAMESPACE = uuid.UUID("fcb72d0c-0f43-4a12-8a98-114c9bcefa57")
SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
NOW = datetime(2025, 1, 1, tzinfo=UTC)


def stable_id(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def fixture_prices(round_index: int) -> dict[str, D]:
    with localcontext() as context:
        context.prec = 60
        drift = D(round_index)
        return {
            "BTC": D("95000") + drift * D("115") + D((round_index % 4) - 1) * D("90"),
            "ETH": D("3400") + drift * D("5") + D((round_index % 3) - 1) * D("12"),
            "SOL": D("190") + drift * D("0.6"),
            "BNB": D("690") + drift * D("1.1"),
            "DOGE": D("0.34") + drift * D("0.001"),
            "XRP": D("2.4") + drift * D("0.008"),
        }


def _rules() -> Rules:
    return rules_from_config(canonical_profile("alpha_2025_baseline"))


def _sum_decimals(values: Iterable[D]) -> D:
    with localcontext() as context:
        context.prec = 60
        return sum(values, D("0"))


def _maximum_leverage_breach(rules: Rules) -> D:
    with localcontext() as context:
        context.prec = 60
        return rules.max_leverage + D("1")


def _fixture_proposal(
    *,
    action: Action,
    symbol: str,
    quantity: D,
    leverage: D,
    stop_loss: D | None,
    take_profit: D | None,
    confidence: D,
    invalidation: str,
    justification: str,
) -> dict[str, object]:
    return {
        "action": action.value,
        "symbol": symbol,
        "quantity": format(quantity, "f"),
        "leverage": format(leverage, "f"),
        "stop_loss": format(stop_loss, "f") if stop_loss is not None else None,
        "take_profit": format(take_profit, "f") if take_profit is not None else None,
        "confidence": format(confidence, "f"),
        "invalidation": invalidation,
        "justification": justification,
    }


def seed_demo(db: Session, rounds: int = 20) -> str:
    """Create a durable, deterministic fixture replay without rewriting older versions."""
    if not 1 <= rounds <= 200:
        raise ValueError("rounds must be from 1 through 200")

    def fixture_id(name: str) -> str:
        return stable_id(f"demo:v2:{rounds}:{name}")

    competition_name = f"Offline Paper Arena · proposal evidence v2 · {rounds} rounds"
    existing = db.scalar(
        select(Competition).where(Competition.name == competition_name)
    )
    if existing:
        return existing.id

    rules_json = canonical_profile("alpha_2025_baseline")
    rules_json["fixture_source"] = "fixture-replay-v2"
    rules_bytes = canonical_json_bytes(rules_json)
    root = Path(__file__).resolve().parents[4]
    prompt_bytes = (root / "prompts/baseline-v1.md").read_bytes()
    competition_id = fixture_id("competition")
    prompt_id = stable_id("demo:v2:prompt")
    competition = Competition(
        id=competition_id,
        name=competition_name,
        profile="alpha_2025_baseline",
        rules_bytes=rules_bytes,
        rules_sha256=sha256_hex(rules_bytes),
        initial_balance=D("10000"),
        state="FINISHED",
        source_label="DEMO REPLAY · proposal evidence v2 · deterministic local fixtures",
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=rounds * 180),
        event_seq=0,
    )
    db.add(competition)
    prompt_version = db.get(PromptVersion, prompt_id)
    if prompt_version is None:
        db.add(
            PromptVersion(
                id=prompt_id,
                name="baseline",
                version=2,
                template_bytes=prompt_bytes,
                sha256=sha256_hex(prompt_bytes),
            )
        )
    elif prompt_version.sha256 != sha256_hex(prompt_bytes):
        raise RuntimeError("fixture prompt version is immutable")
    db.flush()

    agents = [
        ("atlas", "Atlas", "MockLLMAdapter", "mock-atlas-v2", 0),
        ("vector", "Vector", "MockLLMAdapter", "mock-vector-v2", 1),
    ]
    state: dict[str, Account] = {}
    accounts: dict[str, str] = {}
    for key, name, provider, model, order in agents:
        run_id, account_id = fixture_id(f"agent:{key}"), fixture_id(f"account:{key}")
        settings_bytes = canonical_json_bytes(
            {
                "adapter": "mock",
                "external_calls": False,
                "max_output_tokens": 512,
                "seed": key,
                "temperature": "0",
            }
        )
        db.add(
            AgentRun(
                id=run_id,
                competition_id=competition_id,
                manifest_order=order,
                name=name,
                provider=provider,
                model=model,
                model_settings_bytes=settings_bytes,
                settings_sha256=sha256_hex(settings_bytes),
                prompt_version_id=prompt_id,
                status="FINISHED",
            )
        )
        db.flush()
        db.add(
            AccountRow(
                id=account_id,
                agent_run_id=run_id,
                cash=D("10000"),
                realized_pnl=D("0"),
                fees=D("0"),
                funding=D("0"),
                reserved_margin=D("0"),
                halted=False,
                peak_equity=D("10000"),
                daily_baseline_equity=D("10000"),
                risk_day=NOW.date(),
                version=0,
            )
        )
        accounts[key] = account_id
        state[key] = Account.create(D("10000"))

    for key, _, _, _, _ in agents:
        db.add(
            EquitySample(
                id=fixture_id(f"equity:0:{key}"),
                account_id=accounts[key],
                round_index=0,
                logical_at=NOW,
                equity=D("10000"),
                realized_pnl=D("0"),
                unrealized_pnl=D("0"),
                fees=D("0"),
                funding=D("0"),
            )
        )
    db.flush()

    instruments = {s: Instrument(s, min_notional=D("10")) for s in SYMBOLS}
    rules = _rules()
    seq = 0
    for index in range(1, rounds + 1):
        at = NOW + timedelta(seconds=index * 180)
        marks = fixture_prices(index)
        with localcontext() as context:
            context.prec = 60
            quote_payload = {
                s: {
                    "bid": str(v - max(v * D("0.00005"), D("0.00001"))),
                    "ask": str(v + max(v * D("0.00005"), D("0.00001"))),
                    "mark": str(v),
                    "event_at": at.isoformat(),
                    "received_at": at.isoformat(),
                }
                for s, v in marks.items()
            }
        snapshot_payload = {
            "schema_version": 1,
            "source": "fixture-replay-v2",
            "round": index,
            "quotes": quote_payload,
            "candles": [],
        }
        snapshot_bytes = canonical_json_bytes(snapshot_payload)
        snapshot_hash = sha256_hex(snapshot_bytes)
        snapshot_id = fixture_id(f"snapshot:{index}")
        quote_set_id = fixture_id(f"quote-set:{index}")
        db.add(
            QuoteSet(
                id=quote_set_id,
                source="fixture-replay-v2",
                captured_at=at,
                complete=True,
                max_age_ms=0,
                skew_ms=0,
            )
        )
        db.flush()
        for symbol, values in quote_payload.items():
            db.add(
                MarketQuote(
                    quote_set_id=quote_set_id,
                    symbol=symbol,
                    bid=D(values["bid"]),
                    ask=D(values["ask"]),
                    mark=marks[symbol],
                    funding_rate=D("0"),
                    open_interest=None,
                    source_at=at,
                    received_at=at,
                    source_at_basis="fixture_replay_timestamp",
                )
            )
        db.flush()
        db.add(
            MarketSnapshot(
                id=snapshot_id,
                canonical_bytes=snapshot_bytes,
                sha256=snapshot_hash,
                source_label="fixture-replay-v2",
                captured_at=at,
                quote_set_id=quote_set_id,
            )
        )
        db.flush()
        round_id = fixture_id(f"round:{index}")
        db.add(
            DecisionRound(
                id=round_id,
                competition_id=competition_id,
                round_index=index,
                logical_at=at,
                snapshot_id=snapshot_id,
                deadline_at=at + timedelta(seconds=120),
            )
        )
        db.flush()
        quotes = {
            s: Quote(s, D(quote_payload[s]["bid"]), D(quote_payload[s]["ask"]), marks[s])
            for s in SYMBOLS
        }
        for key, _, _, model, _ in agents:
            account = state[key]
            symbol = "BTC" if key == "atlas" else "ETH"
            if index % 5 == 1 and symbol not in account.positions:
                action = Action.OPEN_LONG if key == "atlas" else Action.OPEN_SHORT
                quantity = D("0.02") if key == "atlas" else D("0.5")
            elif index % 5 == 3 and symbol in account.positions:
                action, quantity = Action.CLOSE_POSITION, D("0")
            else:
                action, quantity = Action.HOLD, D("0")
            job_id = fixture_id(f"job:{index}:{key}")
            db.add(
                RoundAgentJob(
                    id=job_id,
                    round_id=round_id,
                    agent_run_id=fixture_id(f"agent:{key}"),
                    state="TERMINAL",
                    terminal_result="SUCCESS",
                    fence=1,
                )
            )
            db.flush()
            stop_loss = take_profit = None
            with localcontext() as context:
                context.prec = 60
                if action is Action.OPEN_LONG:
                    stop_loss, take_profit = (
                        marks[symbol] * D("0.95"),
                        marks[symbol] * D("1.10"),
                    )
                elif action is Action.OPEN_SHORT:
                    stop_loss, take_profit = (
                        marks[symbol] * D("1.10"),
                        marks[symbol] * D("0.90"),
                    )
            primary = _fixture_proposal(
                action=action,
                symbol=symbol,
                quantity=quantity,
                leverage=D("2"),
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=D("0.82") if action is not Action.HOLD else D("0.58"),
                invalidation=(
                    f"Reassess if {symbol} reaches its stated protective level."
                    if stop_loss is not None
                    else f"Reassess if the next {symbol} snapshot changes the supplied evidence."
                ),
                justification=(
                    f"Deterministic fixture policy selected {action.value} for round {index}."
                ),
            )
            rejected = _fixture_proposal(
                action=Action.OPEN_LONG,
                symbol="XRP",
                quantity=D("5"),
                leverage=_maximum_leverage_breach(rules),
                stop_loss=None,
                take_profit=None,
                confidence=D("0.91"),
                invalidation="Do not enter if the configured leverage ceiling is exceeded.",
                justification="Fixture case for a proposal rejected by the paper risk engine.",
            )
            user_input = build_user_input(
                logical_at=at,
                frozen_rules=rules_json,
                frozen_rules_sha256=sha256_hex(rules_bytes),
                snapshot=snapshot_payload,
                snapshot_sha256=snapshot_hash,
                own_account={
                    "version": index - 1,
                    "cash": str(account.cash),
                    "realized_pnl": str(account.realized_pnl),
                    "fees": str(account.fees),
                    "funding": str(account.funding),
                    "positions": [
                        {
                            "symbol": position.symbol,
                            "side": position.side.value,
                            "quantity": str(position.quantity),
                            "average_entry": str(position.average_entry),
                            "reserved_margin": str(position.reserved_margin),
                            "stop_loss": (
                                str(position.stop_loss) if position.stop_loss is not None else None
                            ),
                            "take_profit": (
                                str(position.take_profit)
                                if position.take_profit is not None
                                else None
                            ),
                        }
                        for position in sorted(
                            account.positions.values(), key=lambda item: item.symbol
                        )
                    ],
                },
            )
            provider_config = ProviderConfig(
                provider="MockLLMAdapter",
                model=model,
                endpoint=OPENAI_CHAT_URL,
                max_output_tokens=512,
                temperature=D("0"),
            )
            request_bytes = build_agent_request_bytes(
                provider_config,
                system_prompt_bytes=prompt_bytes,
                user_prompt_bytes=user_input,
            )
            output_bytes = canonical_json_bytes({"proposals": [primary, rejected]})
            batch: ProposalBatch = parse_proposal_output(output_bytes)
            attempt_id = fixture_id(f"decision:{index}:{key}")
            db.add(
                InvocationAttempt(
                    id=attempt_id,
                    job_id=job_id,
                    prompt_bytes=request_bytes,
                    prompt_sha256=sha256_hex(request_bytes),
                    provider="MockLLMAdapter",
                    model=model,
                    public_parameters={
                        **provider_config.public_parameters,
                        "offline_fixture": True,
                    },
                    dispatched_at=at,
                    fence=1,
                )
            )
            db.flush()
            db.add(
                InvocationResult(
                    id=fixture_id(f"decision-result:{index}:{key}"),
                    attempt_id=attempt_id,
                    output_bytes=output_bytes,
                    output_sha256=sha256_hex(output_bytes),
                    latency_ms=0,
                    usage={"input_tokens": 0, "output_tokens": 0},
                    error_code=None,
                    late=False,
                    public_metadata={
                        "source": "DEMO REPLAY",
                        "adapter": "mock",
                        "finish_reason": "fixture",
                    },
                )
            )
            db.flush()
            results: dict[int, EngineResult | None] = {}
            for sequence, proposal in enumerate(batch.proposals):
                proposal_id = fixture_id(f"proposal:{index}:{key}:{sequence}")
                db.add(
                    TradeProposal(
                        id=proposal_id,
                        job_id=job_id,
                        sequence=sequence,
                        action=proposal.action.value,
                        symbol=proposal.symbol,
                        quantity=proposal.quantity,
                        raw_bytes=output_bytes,
                    )
                )
                try:
                    proposal_result = apply_action(
                        state[key],
                        action=Action(proposal.action.value),
                        symbol=proposal.symbol,
                        quantity=proposal.quantity,
                        leverage=proposal.leverage,
                        quote=quotes[proposal.symbol],
                        instrument=instruments[proposal.symbol],
                        rules=rules,
                        stop_loss=proposal.stop_loss,
                        take_profit=proposal.take_profit,
                        idempotency_key=proposal_id,
                        current_quotes=quotes,
                        current_instruments=instruments,
                        as_of=at.date(),
                    )
                except FinanceError as exc:
                    proposal_result = None
                    reasons = [str(exc)]
                else:
                    reasons = []
                    if sequence == 0 and proposal_result is not None:
                        state[key] = proposal_result.account
                results[sequence] = proposal_result
                db.flush()
                db.add(
                    RiskEvaluation(
                        id=fixture_id(f"risk:{index}:{key}:{sequence}"),
                        proposal_id=proposal_id,
                        decision="ACCEPTED" if proposal_result is not None else "REJECTED",
                        reasons=reasons,
                        policy_version=f"{competition.profile}:frozen-v1",
                    )
                )
            db.flush()
            result = results[0]
            if result is not None and result.fills:
                proposal_id = fixture_id(f"proposal:{index}:{key}:0")
                order_id = fixture_id(f"order:{index}:{key}")
                db.add(
                    Order(
                        id=order_id,
                        account_id=accounts[key],
                        proposal_id=proposal_id,
                        idempotency_key=proposal_id,
                        kind="MARKET",
                        status="FILLED",
                    )
                )
                db.flush()
                for fill_index, fill in enumerate(result.fills):
                    db.add(
                        Fill(
                            id=fixture_id(f"fill:{index}:{key}:{fill_index}"),
                            order_id=order_id,
                            symbol=fill.symbol,
                            side=fill.side.value,
                            quantity=fill.quantity,
                            price=fill.price,
                            fee=fill.fee,
                        )
                    )
                journal_id = fixture_id(f"journal:{index}:{key}")
                db.add(
                    LedgerJournal(id=journal_id, account_id=accounts[key], event_key=proposal_id)
                )
                db.flush()
                for post_index, posting in enumerate(result.postings):
                    db.add(
                        LedgerPosting(
                            id=fixture_id(f"posting:{index}:{key}:{post_index}"),
                            journal_id=journal_id,
                            bucket=posting.bucket,
                            amount=posting.amount,
                        )
                    )
            db.flush()
            persisted_position = db.scalar(
                select(Position)
                .where(
                    Position.account_id == accounts[key],
                    Position.symbol == symbol,
                    Position.state == "OPEN",
                )
                .order_by(Position.opened_at.desc(), Position.id)
                .limit(1)
            )
            simulated_position = state[key].positions.get(symbol)
            if simulated_position is None:
                if persisted_position is not None:
                    persisted_position.state = "CLOSED"
                    persisted_position.closed_at = at
            elif persisted_position is None:
                db.add(
                    Position(
                        id=fixture_id(f"position:{key}:{symbol}:{index}"),
                        account_id=accounts[key],
                        symbol=symbol,
                        side=simulated_position.side.value,
                        quantity=simulated_position.quantity,
                        average_entry=simulated_position.average_entry,
                        reserved_margin=simulated_position.reserved_margin,
                        stop_loss=simulated_position.stop_loss,
                        take_profit=simulated_position.take_profit,
                        state="OPEN",
                        opened_at=at,
                    )
                )
            else:
                if persisted_position.side != simulated_position.side.value:
                    persisted_position.side = simulated_position.side.value
                if persisted_position.quantity != simulated_position.quantity:
                    persisted_position.quantity = simulated_position.quantity
                if persisted_position.average_entry != simulated_position.average_entry:
                    persisted_position.average_entry = simulated_position.average_entry
                if persisted_position.reserved_margin != simulated_position.reserved_margin:
                    persisted_position.reserved_margin = simulated_position.reserved_margin
                if persisted_position.stop_loss != simulated_position.stop_loss:
                    persisted_position.stop_loss = simulated_position.stop_loss
                if persisted_position.take_profit != simulated_position.take_profit:
                    persisted_position.take_profit = simulated_position.take_profit
            account_row = db.get(AccountRow, accounts[key])
            assert account_row is not None
            current = state[key]
            with localcontext() as context:
                context.prec = 60
                account_equity = equity(current, quotes, instruments)
                u_pnl = _sum_decimals(
                    unrealized_pnl(position, marks[position.symbol])
                    for position in current.positions.values()
                )
                reserved_margin = _sum_decimals(
                    position.reserved_margin for position in current.positions.values()
                )
            account_row.cash, account_row.realized_pnl = current.cash, current.realized_pnl
            account_row.fees, account_row.reserved_margin, account_row.version = (
                current.fees,
                reserved_margin,
                index,
            )
            db.add(
                EquitySample(
                    id=fixture_id(f"equity:{index}:{key}"),
                    account_id=accounts[key],
                    round_index=index,
                    logical_at=at,
                    equity=account_equity,
                    realized_pnl=current.realized_pnl,
                    unrealized_pnl=u_pnl,
                    fees=current.fees,
                    funding=current.funding,
                )
            )
            seq += 1
            db.add(
                DomainEvent(
                    id=fixture_id(f"event:{index}:{key}"),
                    competition_id=competition_id,
                    sequence=seq,
                    account_id=accounts[key],
                    event_type="agent.decision",
                    payload={
                        "agent_id": fixture_id(f"agent:{key}"),
                        "round": index,
                        "action": action.value,
                        "source": "DEMO REPLAY",
                    },
                    event_at=at,
                )
            )
            db.flush()
        competition.event_seq = seq
    db.commit()
    return competition_id
