from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import (
    Account,
    AgentRun,
    Base,
    Competition,
    DecisionRound,
    DomainEvent,
    EquitySample,
    Fill,
    InvocationAttempt,
    InvocationResult,
    LedgerJournal,
    LedgerPosting,
    Order,
    Position,
    PromptVersion,
    RiskEvaluation,
    RoundAgentJob,
    TradeProposal,
)
from app.market.persistence import persist_quote_set
from app.market.types import BASELINE_SYMBOLS, InstrumentSpec, MarketQuoteSet
from app.market.types import MarketQuote as Quote
from app.services.execution import (
    _rules,
    execute_job,
    run_protective_exit_cycle,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


def _output(action: str = "OPEN_LONG", quantity: str = "0.1") -> bytes:
    return json.dumps(
        {
            "proposals": [
                {
                    "action": action,
                    "symbol": "BTC",
                    "quantity": float(quantity),
                    "leverage": 2,
                    "stop_loss": 90 if action == "OPEN_LONG" else None,
                    "take_profit": 120 if action == "OPEN_LONG" else None,
                    "confidence": 0.8,
                    "invalidation": "The supplied market condition changes.",
                    "justification": "This is a fixture response using the supplied snapshot.",
                }
            ]
        }
    ).encode()


def _setup(
    *, output: bytes | None = None, fresh: bool = True
) -> tuple[Session, str, int, str, str]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    source_at = now if fresh else now - timedelta(seconds=20)
    quotes = tuple(
        Quote(
            symbol=symbol,
            bid=Decimal("99"),
            ask=Decimal("101"),
            mark=Decimal("100"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("10"),
            source_at=source_at,
            received_at=now,
            context_received_at=now,
        )
        for symbol in BASELINE_SYMBOLS
    )
    market_set = MarketQuoteSet(
        now,
        quotes,
        tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
    )
    receipt = persist_quote_set(db, market_set)
    competition_id = "competition-1"
    prompt_id = "prompt-1"
    agent_id = "agent-1"
    account_id = "account-1"
    round_id = "round-1"
    job_id = "job-1"
    prompt = b"system prompt fixture"
    rules = canonical_profile("alpha_2025_baseline") | {"source": "test"}
    db.add_all(
        [
            Competition(
                id=competition_id,
                name="execution-test",
                profile=rules["profile"],
                rules_bytes=canonical_json_bytes(rules),
                rules_sha256=sha256_hex(canonical_json_bytes(rules)),
                initial_balance=Decimal("10000"),
                state="RUNNING",
                source_label="TEST",
                event_seq=0,
            ),
            PromptVersion(
                id=prompt_id,
                name="baseline",
                version=1,
                template_bytes=prompt,
                sha256=sha256_hex(prompt),
            ),
        ]
    )
    db.flush()
    settings = canonical_json_bytes({"test": True})
    db.add(
        AgentRun(
            id=agent_id,
            competition_id=competition_id,
            manifest_order=0,
            name="Tester",
            provider="fixture",
            model="fixture-v1",
            model_settings_bytes=settings,
            settings_sha256=sha256_hex(settings),
            prompt_version_id=prompt_id,
            status="ACTIVE",
        )
    )
    db.flush()
    db.add(
        Account(
            id=account_id,
            agent_run_id=agent_id,
            cash=Decimal("10000"),
            realized_pnl=Decimal("0"),
            fees=Decimal("0"),
            funding=Decimal("0"),
            reserved_margin=Decimal("0"),
            halted=False,
            version=0,
        )
    )
    db.add(
        DecisionRound(
            id=round_id,
            competition_id=competition_id,
            round_index=1,
            logical_at=now,
            snapshot_id=receipt.snapshot_id,
            deadline_at=now - timedelta(seconds=1),
        )
    )
    db.flush()
    db.add(
        RoundAgentJob(
            id=job_id,
            round_id=round_id,
            agent_run_id=agent_id,
            state="RESPONDED",
            fence=3,
            lease_owner="test-worker",
            lease_expires_at=now + timedelta(seconds=60),
        )
    )
    db.flush()
    attempt_id = "attempt-1"
    db.add(
        InvocationAttempt(
            id=attempt_id,
            job_id=job_id,
            prompt_bytes=prompt,
            prompt_sha256=sha256_hex(prompt),
            provider="fixture",
            model="fixture-v1",
            public_parameters={"temperature": "0"},
            dispatched_at=now,
            fence=3,
        )
    )
    response = output or _output()
    db.add(
        InvocationResult(
            id="result-1",
            attempt_id=attempt_id,
            output_bytes=response,
            output_sha256=sha256_hex(response),
            latency_ms=1,
            usage={"input_tokens": 1, "output_tokens": 1},
            error_code=None,
            late=False,
            public_metadata={"adapter": "fixture"},
        )
    )
    db.commit()
    return db, job_id, 3, receipt.quote_set_id, account_id


def test_execution_persists_balanced_ledger_and_is_idempotent() -> None:
    db, job_id, fence, quote_set_id, account_id = _setup()
    receipt = execute_job(db, job_id, fence, quote_set_id)
    assert receipt.state == "SUCCESS"
    assert receipt.accepted_proposals == 1
    assert receipt.rejected_proposals == 0
    assert not receipt.idempotent_replay
    assert execute_job(db, job_id, fence, quote_set_id).idempotent_replay
    assert db.scalar(select(func.count()).select_from(TradeProposal)) == 1
    assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert db.scalar(select(func.count()).select_from(Fill)) == 1
    assert db.scalar(select(func.count()).select_from(LedgerJournal)) == 1
    assert db.scalar(select(func.count()).select_from(EquitySample)) == 1
    account = db.get(Account, account_id)
    assert account is not None and account.cash < Decimal("10000")
    position = db.scalar(select(Position).where(Position.account_id == account_id))
    assert position is not None and position.state == "OPEN"
    postings = db.scalars(select(LedgerPosting)).all()
    assert sum((item.amount for item in postings), Decimal("0")) == Decimal("0")
    evaluation = db.scalar(select(RiskEvaluation))
    assert evaluation is not None and evaluation.decision == "ACCEPTED"
    assert db.scalar(select(func.count()).select_from(DomainEvent)) == 1
    db.close()


def test_incomplete_or_stale_shared_quotes_reject_new_entries_without_fills() -> None:
    db, job_id, fence, quote_set_id, account_id = _setup(fresh=False)
    receipt = execute_job(db, job_id, fence, quote_set_id)
    assert receipt.state == "RISK_REJECTED"
    assert receipt.accepted_proposals == 0
    assert receipt.rejected_proposals == 1
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    assert db.scalar(select(func.count()).select_from(Fill)) == 0
    account = db.get(Account, account_id)
    assert account is not None and account.cash == Decimal("10000")
    db.close()


def test_invalid_provider_schema_is_terminal_and_does_not_create_trade() -> None:
    db, job_id, fence, quote_set_id, _ = _setup(output=b'{"reasoning":"private"}')
    receipt = execute_job(db, job_id, fence, quote_set_id)
    assert receipt.state == "PROVIDER_ERROR"
    job = db.get(RoundAgentJob, job_id)
    assert job is not None and job.error_code == "INVALID_PROPOSAL_OUTPUT"
    assert db.scalar(select(func.count()).select_from(TradeProposal)) == 0
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    db.close()


def test_risk_rejection_is_audited_and_execution_remains_terminal() -> None:
    db, job_id, fence, quote_set_id, _ = _setup(output=_output(quantity="999999"))
    receipt = execute_job(db, job_id, fence, quote_set_id)
    assert receipt.state == "RISK_REJECTED"
    proposal = db.scalar(select(TradeProposal))
    evaluation = db.scalar(select(RiskEvaluation))
    assert proposal is not None
    assert evaluation is not None and evaluation.decision == "REJECTED"
    assert evaluation.reasons
    assert db.scalar(select(func.count()).select_from(Fill)) == 0
    db.close()


def test_provider_output_fence_mismatch_cannot_execute() -> None:
    db, job_id, fence, quote_set_id, _ = _setup()
    with pytest.raises(ValueError, match="fence is stale"):
        execute_job(db, job_id, fence + 1, quote_set_id)
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    db.close()


def test_protective_exit_runs_without_response_or_complete_quote_universe() -> None:
    db, job_id, fence, quote_set_id, account_id = _setup()
    receipt = execute_job(db, job_id, fence, quote_set_id)
    assert receipt.accepted_proposals == 1

    now = datetime.now(UTC).replace(microsecond=0)
    one_symbol_set = MarketQuoteSet(
        now,
        (
            Quote(
                symbol="BTC",
                bid=Decimal("88"),
                ask=Decimal("90"),
                mark=Decimal("89"),
                funding_rate=Decimal("0"),
                open_interest=Decimal("10"),
                source_at=now,
                received_at=now,
                context_received_at=now,
            ),
        ),
        (InstrumentSpec("BTC", 4, 20),),
    )
    protective_set = persist_quote_set(db, one_symbol_set)
    db.commit()

    cycle = run_protective_exit_cycle(db, quote_set_id=protective_set.quote_set_id)

    assert cycle.checked_accounts == 1
    assert cycle.protective_exits == 1
    position = db.scalar(select(Position).where(Position.account_id == account_id))
    assert position is not None and position.state == "CLOSED"
    assert db.scalar(select(func.count()).select_from(Order)) == 2
    db.close()


def test_execution_uses_canonical_frozen_risk_rule_names() -> None:
    config = canonical_profile("alpha_2025_baseline") | {
        "commission_rate": "0.001",
        "slippage_bps": "4",
        "leverage_max": "7",
        "max_notional": "30000",
        "max_gross_exposure": "50000",
        "maintenance_margin_rate": "0.02",
        "max_positions": 4,
        "quote_max_age_seconds": "8",
        "quote_set_max_skew_seconds": "3",
        "max_daily_loss": "500",
        "max_drawdown_fraction": "0.25",
        "liquidation_fee_rate": "0.01",
    }
    rules = _rules(config)
    assert rules.commission_rate == Decimal("0.001")
    assert rules.max_leverage == Decimal("7")
    assert rules.max_order_notional == Decimal("30000")
    assert rules.max_gross_exposure == Decimal("50000")
    assert rules.maintenance_margin_rate == Decimal("0.02")
    assert rules.max_positions == 4
    assert rules.max_quote_age_seconds == Decimal("8")
    assert rules.max_quote_skew_seconds == Decimal("3")
    assert rules.max_daily_loss == Decimal("500")
    assert rules.max_drawdown_fraction == Decimal("0.25")
    assert rules.liquidation_fee_rate == Decimal("0.01")




def test_same_batch_reentry_is_rejected_after_protective_close() -> None:
    output = json.dumps(
        {
            "proposals": [
                {
                    "action": "OPEN_LONG",
                    "symbol": "BTC",
                    "quantity": 0.2,
                    "leverage": 2,
                    "stop_loss": None,
                    "take_profit": None,
                    "confidence": 0.8,
                    "invalidation": "The supplied market condition changes.",
                    "justification": "The supplied snapshot supports a bounded paper entry.",
                }
            ]
        }
    ).encode()
    db, job_id, fence, _, account_id = _setup(output=output)
    account = db.get(Account, account_id)
    assert account is not None
    account.reserved_margin = Decimal("10")
    db.add(
        Position(
            id="existing-position",
            account_id=account_id,
            symbol="BTC",
            side="LONG",
            quantity=Decimal("0.2"),
            average_entry=Decimal("100"),
            reserved_margin=Decimal("10"),
            stop_loss=Decimal("95"),
            take_profit=None,
            state="OPEN",
        )
    )
    now = datetime.now(UTC).replace(microsecond=0)
    quotes = tuple(
        Quote(
            symbol=symbol,
            bid=Decimal("88") if symbol == "BTC" else Decimal("99"),
            ask=Decimal("89") if symbol == "BTC" else Decimal("101"),
            mark=Decimal("89") if symbol == "BTC" else Decimal("100"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("10"),
            source_at=now,
            received_at=now,
            context_received_at=now,
        )
        for symbol in BASELINE_SYMBOLS
    )
    execution_set = persist_quote_set(
        db,
        MarketQuoteSet(
            now,
            quotes,
            tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
        ),
    )
    db.commit()

    receipt = execute_job(db, job_id, fence, execution_set.quote_set_id)

    assert receipt.protective_exits == 1
    assert receipt.accepted_proposals == 0 and receipt.rejected_proposals == 1
    position = db.get(Position, "existing-position")
    assert position is not None and position.state == "CLOSED"
    assert db.scalar(select(func.count()).select_from(Position)) == 1
    assert db.scalar(select(func.count()).select_from(Order)) == 1
    db.close()
