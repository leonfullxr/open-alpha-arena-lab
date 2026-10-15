from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.core.canonical import canonical_json_bytes, sha256_hex
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
    RoundAgentJob,
    TradeProposal,
)
from app.engine.finance import (
    Account,
    Action,
    Instrument,
    Quote,
    Rules,
    apply_action,
    equity,
    unrealized_pnl,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

NAMESPACE = uuid.UUID("fcb72d0c-0f43-4a12-8a98-114c9bcefa57")
SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
NOW = datetime(2025, 1, 1, tzinfo=UTC)


def stable_id(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def fixture_prices(round_index: int) -> dict[str, D]:
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
    return Rules(
        commission_rate=D("0.0005"),
        slippage_bps=D("2"),
        max_leverage=D("3"),
        max_order_notional=D("5000"),
        max_gross_exposure=D("10000"),
        max_positions=2,
    )


def seed_demo(db: Session, rounds: int = 20) -> str:
    """Create a durable, deterministic 20-round fixture competition once."""
    if not 1 <= rounds <= 200:
        raise ValueError("rounds must be from 1 through 200")
    existing = db.scalar(
        select(Competition).where(Competition.name == "Offline Paper Arena · 20 rounds")
    )
    if existing:
        return existing.id

    rules_json = {
        "profile": "alpha_2025_baseline",
        "symbols": list(SYMBOLS),
        "initial_balance": "10000",
        "round_seconds": 180,
        "source": "fixture-replay-v1",
        "fee_rate": "0.0005",
        "slippage_bps": "2",
        "max_leverage": "3",
        "allow_pyramiding": False,
    }
    rules_bytes = canonical_json_bytes(rules_json)
    prompt_bytes = open("prompts/baseline-v1.md", "rb").read()
    competition_id = stable_id("demo:competition")
    prompt_id = stable_id("demo:prompt:v1")
    competition = Competition(
        id=competition_id,
        name="Offline Paper Arena · 20 rounds",
        profile="alpha_2025_baseline",
        rules_bytes=rules_bytes,
        rules_sha256=sha256_hex(rules_bytes),
        initial_balance=D("10000"),
        state="FINISHED",
        source_label="DEMO REPLAY · deterministic local fixtures",
        started_at=NOW,
        ended_at=NOW + timedelta(minutes=57),
        event_seq=0,
    )
    db.add(competition)
    db.add(
        PromptVersion(
            id=prompt_id,
            name="baseline",
            version=1,
            template_bytes=prompt_bytes,
            sha256=sha256_hex(prompt_bytes),
        )
    )
    db.flush()

    agents = [
        ("atlas", "Atlas", "MockLLMAdapter", "mock-atlas-v1", 0),
        ("vector", "Vector", "MockLLMAdapter", "mock-vector-v1", 1),
    ]
    state: dict[str, Account] = {}
    accounts: dict[str, str] = {}
    for key, name, provider, model, order in agents:
        run_id, account_id = stable_id(f"demo:agent:{key}"), stable_id(f"demo:account:{key}")
        settings_bytes = canonical_json_bytes(
            {"adapter": "fixture", "seed": key, "external_calls": False}
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
                version=0,
            )
        )
        accounts[key] = account_id
        state[key] = Account.create(D("10000"))

    for key, _, _, _, _ in agents:
        db.add(
            EquitySample(
                id=stable_id(f"demo:equity:0:{key}"),
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
            "source": "fixture-replay-v1",
            "round": index,
            "quotes": quote_payload,
        }
        snapshot_bytes = canonical_json_bytes(snapshot_payload)
        snapshot_hash = sha256_hex(snapshot_bytes)
        snapshot_id = stable_id(f"demo:snapshot:{index}")
        quote_set_id = stable_id(f"demo:quote-set:{index}")
        db.add(
            QuoteSet(
                id=quote_set_id,
                source="fixture-replay-v1",
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
                source_label="fixture-replay-v1",
                captured_at=at,
                quote_set_id=quote_set_id,
            )
        )
        db.flush()
        round_id = stable_id(f"demo:round:{index}")
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
        for key, name, _, model, _ in agents:
            account = state[key]
            symbol = "BTC" if key == "atlas" else "ETH"
            if index % 5 == 1 and symbol not in account.positions:
                action = Action.OPEN_LONG if key == "atlas" else Action.OPEN_SHORT
                quantity = D("0.02") if key == "atlas" else D("0.5")
            elif index % 5 == 3 and symbol in account.positions:
                action, quantity = Action.CLOSE_POSITION, D("0")
            else:
                action, quantity = Action.HOLD, D("0")
            job_id = stable_id(f"demo:job:{index}:{key}")
            db.add(
                RoundAgentJob(
                    id=job_id,
                    round_id=round_id,
                    agent_run_id=stable_id(f"demo:agent:{key}"),
                    state="TERMINAL",
                    terminal_result="SUCCESS",
                    fence=1,
                )
            )
            db.flush()
            observed = {
                "agent": name,
                "round": index,
                "own_account": {
                    "cash": str(account.cash),
                    "positions": [
                        {
                            "symbol": p.symbol,
                            "side": p.side.value,
                            "quantity": str(p.quantity),
                            "average_entry": str(p.average_entry),
                        }
                        for p in account.positions.values()
                    ],
                },
                "snapshot_sha256": snapshot_hash,
                "snapshot": snapshot_payload,
            }
            prompt_artifact = prompt_bytes + b"\n\nINPUT\n" + canonical_json_bytes(observed)
            output = {
                "action": action.value,
                "symbol": symbol,
                "quantity": str(quantity),
                "justification": f"Deterministic fixture policy for round {index}.",
                "market_summary": "Fixture replay; no live market request was made.",
            }
            output_bytes = canonical_json_bytes(output)
            attempt_id = stable_id(f"demo:decision:{index}:{key}")
            db.add(
                InvocationAttempt(
                    id=attempt_id,
                    job_id=job_id,
                    prompt_bytes=prompt_artifact,
                    prompt_sha256=sha256_hex(prompt_artifact),
                    provider="MockLLMAdapter",
                    model=model,
                    public_parameters={"temperature": "0", "max_tokens": 512},
                    dispatched_at=at,
                    fence=1,
                )
            )
            db.flush()
            db.add(
                InvocationResult(
                    id=stable_id(f"demo:decision-result:{index}:{key}"),
                    attempt_id=attempt_id,
                    output_bytes=output_bytes,
                    output_sha256=sha256_hex(output_bytes),
                    latency_ms=0,
                    usage={"input_tokens": 0, "output_tokens": 0},
                    error_code=None,
                    late=False,
                    public_metadata={"source": "DEMO REPLAY", "hidden_reasoning": "not available"},
                )
            )
            proposal_id = stable_id(f"demo:proposal:{index}:{key}")
            db.add(
                TradeProposal(
                    id=proposal_id,
                    job_id=job_id,
                    sequence=0,
                    action=action.value,
                    symbol=symbol,
                    quantity=quantity,
                    raw_bytes=output_bytes,
                )
            )
            db.flush()
            quote = quotes[symbol]
            result = None
            if action is not Action.HOLD:
                result = apply_action(
                    account,
                    action=action,
                    symbol=symbol,
                    quantity=quantity,
                    leverage=D("2"),
                    quote=quote,
                    instrument=instruments[symbol],
                    rules=rules,
                    stop_loss=None,
                    take_profit=None,
                    idempotency_key=proposal_id,
                    current_quotes=quotes,
                    current_instruments=instruments,
                )
                state[key] = result.account
                order_id = stable_id(f"demo:order:{index}:{key}")
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
                            id=stable_id(f"demo:fill:{index}:{key}:{fill_index}"),
                            order_id=order_id,
                            symbol=fill.symbol,
                            side=fill.side.value,
                            quantity=fill.quantity,
                            price=fill.price,
                            fee=fill.fee,
                        )
                    )
                journal_id = stable_id(f"demo:journal:{index}:{key}")
                db.add(
                    LedgerJournal(id=journal_id, account_id=accounts[key], event_key=proposal_id)
                )
                db.flush()
                for post_index, posting in enumerate(result.postings):
                    db.add(
                        LedgerPosting(
                            id=stable_id(f"demo:posting:{index}:{key}:{post_index}"),
                            journal_id=journal_id,
                            bucket=posting.bucket,
                            amount=posting.amount,
                        )
                    )
            db.flush()
            persisted_position = db.scalar(
                select(Position).where(
                    Position.account_id == accounts[key], Position.symbol == symbol
                )
            )
            simulated_position = state[key].positions.get(symbol)
            if simulated_position is None:
                if persisted_position is not None:
                    persisted_position.state = "CLOSED"
            elif persisted_position is None:
                db.add(
                    Position(
                        id=stable_id(f"demo:position:{key}:{symbol}"),
                        account_id=accounts[key],
                        symbol=symbol,
                        side=simulated_position.side.value,
                        quantity=simulated_position.quantity,
                        average_entry=simulated_position.average_entry,
                        reserved_margin=simulated_position.reserved_margin,
                        stop_loss=simulated_position.stop_loss,
                        take_profit=simulated_position.take_profit,
                        state="OPEN",
                    )
                )
            else:
                persisted_position.side = simulated_position.side.value
                persisted_position.quantity = simulated_position.quantity
                persisted_position.average_entry = simulated_position.average_entry
                persisted_position.reserved_margin = simulated_position.reserved_margin
                persisted_position.state = "OPEN"
            account_row = db.get(AccountRow, accounts[key])
            assert account_row is not None
            current = state[key]
            account_equity = equity(current, quotes, instruments)
            u_pnl = sum(
                (unrealized_pnl(p, marks[p.symbol]) for p in current.positions.values()), D("0")
            )
            account_row.cash, account_row.realized_pnl = current.cash, current.realized_pnl
            account_row.fees, account_row.reserved_margin, account_row.version = (
                current.fees,
                current.reserved_margin,
                index,
            )
            db.add(
                EquitySample(
                    id=stable_id(f"demo:equity:{index}:{key}"),
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
                    id=stable_id(f"demo:event:{index}:{key}"),
                    competition_id=competition_id,
                    sequence=seq,
                    account_id=accounts[key],
                    event_type="agent.decision",
                    payload={
                        "agent_id": stable_id(f"demo:agent:{key}"),
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
