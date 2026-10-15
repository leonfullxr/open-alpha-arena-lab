from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.canonical import sha256_hex
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    InvocationAttempt,
    InvocationResult,
    LedgerJournal,
    LedgerPosting,
    Position,
    PromptVersion,
    RiskEvaluation,
    RoundAgentJob,
    TradeProposal,
)
from app.market.persistence import persist_quote_set
from app.market.types import BASELINE_SYMBOLS, InstrumentSpec, MarketQuoteSet
from app.market.types import MarketQuote as Quote
from app.services.execution import execute_job
from app.services.reconciliation import reconcile_ledger
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from test_execution import _setup
from test_execution_evidence import _migrated_schema

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
_PG_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None


def _proposal_output(symbol: str, action: str = "OPEN_LONG") -> bytes:
    return json.dumps(
        {
            "proposals": [
                {
                    "action": action,
                    "symbol": symbol,
                    "quantity": "0.1" if action != "HOLD" else "0",
                    "leverage": "2",
                    "stop_loss": "90" if action == "OPEN_LONG" else None,
                    "take_profit": "120" if action == "OPEN_LONG" else None,
                    "confidence": "0.8",
                    "invalidation": "The supplied market condition changes.",
                    "justification": "This is a fixture response using the supplied snapshot.",
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def _market_set(
    captured_at: datetime, *, btc_bid: str, btc_ask: str, btc_mark: str
) -> MarketQuoteSet:
    quotes = tuple(
        Quote(
            symbol=symbol,
            bid=Decimal(btc_bid if symbol == "BTC" else "99"),
            ask=Decimal(btc_ask if symbol == "BTC" else "101"),
            mark=Decimal(btc_mark if symbol == "BTC" else "100"),
            funding_rate=Decimal("0"),
            open_interest=Decimal("10"),
            source_at=captured_at,
            received_at=captured_at,
            context_received_at=captured_at,
        )
        for symbol in BASELINE_SYMBOLS
    )
    instruments = tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS)
    return MarketQuoteSet(captured_at, quotes, instruments)


def _responded_job(
    db: Session,
    *,
    round_id: str,
    agent_id: str,
    prompt_bytes: bytes,
    now: datetime,
    output: bytes,
) -> tuple[str, int]:
    job_id, attempt_id, result_id = (str(uuid.uuid4()) for _ in range(3))
    fence = 7
    db.add(
        RoundAgentJob(
            id=job_id,
            round_id=round_id,
            agent_run_id=agent_id,
            state="RESPONDED",
            fence=fence,
            lease_owner="expired-inference-worker",
            lease_expires_at=now - timedelta(seconds=5),
            dispatched_at=now - timedelta(seconds=20),
        )
    )
    db.flush()
    db.add(
        InvocationAttempt(
            id=attempt_id,
            job_id=job_id,
            prompt_bytes=prompt_bytes,
            prompt_sha256=sha256_hex(prompt_bytes),
            provider="fixture",
            model="fixture-v1",
            public_parameters={"temperature": "0"},
            dispatched_at=now - timedelta(seconds=20),
            fence=fence,
        )
    )
    db.add(
        InvocationResult(
            id=result_id,
            attempt_id=attempt_id,
            output_bytes=output,
            output_sha256=sha256_hex(output),
            latency_ms=1,
            usage={"input_tokens": 1, "output_tokens": 1},
            error_code=None,
            late=False,
            public_metadata={"adapter": "fixture"},
        )
    )
    return job_id, fence


@pytest.mark.skipif(_PG_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_expired_inference_leases_recover_twelve_responded_jobs_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import _execute_once

    assert _PG_URL is not None
    schema, admin_engine, engine = _migrated_schema(monkeypatch)
    db: Session | None = None
    try:
        db, first_job_id, first_fence, _, _ = _setup(
            engine=engine, output=_proposal_output("BTC")
        )
        now = datetime.now(UTC)
        first_competition = db.get(Competition, "competition-1")
        first_round = db.get(DecisionRound, "round-1")
        first_job = db.get(RoundAgentJob, first_job_id)
        base_agent = db.get(AgentRun, "agent-1")
        prompt = db.get(PromptVersion, "prompt-1")
        assert (
            first_competition is not None
            and first_round is not None
            and first_job is not None
            and base_agent is not None
            and prompt is not None
        )
        first_competition.source_label = "DEMO REPLAY · expired lease test"
        first_job.lease_expires_at = now - timedelta(seconds=5)
        first_job.lease_owner = "expired-inference-worker"
        first_job.dispatched_at = now - timedelta(seconds=20)
        jobs = [(first_job_id, first_fence)]

        for order in range(1, 6):
            agent_id = str(uuid.uuid4())
            settings = b"{}"
            db.add(
                AgentRun(
                    id=agent_id,
                    competition_id=first_competition.id,
                    manifest_order=order,
                    name=f"Replay {order}",
                    provider="fixture",
                    model="fixture-v1",
                    model_settings_bytes=settings,
                    settings_sha256=sha256_hex(settings),
                    prompt_version_id=prompt.id,
                    status="ACTIVE",
                )
            )
            db.flush()
            db.add(
                Account(
                    id=str(uuid.uuid4()),
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
            jobs.append(
                _responded_job(
                    db,
                    round_id=first_round.id,
                    agent_id=agent_id,
                    prompt_bytes=prompt.template_bytes,
                    now=now,
                    output=_proposal_output("BTC", "HOLD"),
                )
            )

        second_competition_id, second_round_id = str(uuid.uuid4()), str(uuid.uuid4())
        second_competition = Competition(
            id=second_competition_id,
            name="Second replay competition",
            profile=first_competition.profile,
            rules_bytes=first_competition.rules_bytes,
            rules_sha256=first_competition.rules_sha256,
            initial_balance=first_competition.initial_balance,
            state="RUNNING",
            source_label="DEMO REPLAY · expired lease test",
            started_at=now - timedelta(minutes=5),
            event_seq=0,
        )
        db.add(second_competition)
        db.flush()
        db.add(
            DecisionRound(
                id=second_round_id,
                competition_id=second_competition_id,
                round_index=1,
                logical_at=first_round.logical_at,
                snapshot_id=first_round.snapshot_id,
                deadline_at=first_round.deadline_at,
            )
        )
        db.flush()
        for order in range(6):
            agent_id = str(uuid.uuid4())
            settings = b"{}"
            db.add(
                AgentRun(
                    id=agent_id,
                    competition_id=second_competition_id,
                    manifest_order=order,
                    name=f"Second replay {order}",
                    provider="fixture",
                    model="fixture-v1",
                    model_settings_bytes=settings,
                    settings_sha256=sha256_hex(settings),
                    prompt_version_id=prompt.id,
                    status="ACTIVE",
                )
            )
            db.flush()
            db.add(
                Account(
                    id=str(uuid.uuid4()),
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
            jobs.append(
                _responded_job(
                    db,
                    round_id=second_round_id,
                    agent_id=agent_id,
                    prompt_bytes=prompt.template_bytes,
                    now=now,
                    output=_proposal_output("BTC", "HOLD"),
                )
            )
        db.commit()
        db.close()
        engine.dispose()

        factory = sessionmaker(bind=engine, expire_on_commit=False)
        env = {"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"}
        reports = [_execute_once(factory, env) for _ in range(len(jobs))]
        assert all(report.state == "READY" for report in reports)

        with Session(engine) as reopened:
            terminal = reopened.scalar(
                select(func.count()).select_from(RoundAgentJob).where(
                    RoundAgentJob.state == "TERMINAL"
                )
            )
            assert terminal == 12
            assert reconcile_ledger(
                reopened, competition_id=first_competition.id
            ).balanced
            assert reconcile_ledger(
                reopened, competition_id=second_competition_id
            ).balanced
            replay = execute_job(reopened, first_job_id, first_fence, "unused-on-terminal-replay")
            assert replay.idempotent_replay
            with pytest.raises(ValueError, match="fence is stale"):
                execute_job(reopened, first_job_id, first_fence + 1, "unused-on-stale-fence")
    finally:
        if db is not None:
            db.close()
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(_PG_URL is None, reason="TEST_DATABASE_URL is not configured")
@pytest.mark.parametrize(("proposal_symbol", "expected_accepted"), [("ETH", 1), ("BTC", 0)])
def test_clean_inline_protection_reconciles_before_other_symbol_entry(
    monkeypatch: pytest.MonkeyPatch,
    proposal_symbol: str,
    expected_accepted: int,
) -> None:
    from app.worker import _execute_once

    assert _PG_URL is not None
    schema, admin_engine, engine = _migrated_schema(monkeypatch)
    db: Session | None = None
    try:
        db, first_job_id, first_fence, quote_set_id, account_id = _setup(engine=engine)
        competition = db.get(Competition, "competition-1")
        assert competition is not None
        competition.source_label = "DEMO REPLAY · inline protection test"
        opened = execute_job(db, first_job_id, first_fence, quote_set_id)
        assert opened.accepted_proposals == 1
        assert reconcile_ledger(db, competition_id=competition.id).balanced

        now = datetime.now(UTC)
        deadline = now - timedelta(seconds=5)
        pinned_time = now - timedelta(seconds=4)
        latest_time = now - timedelta(seconds=2)
        pinned = persist_quote_set(
            db,
            _market_set(pinned_time, btc_bid="130", btc_ask="131", btc_mark="130"),
        )
        latest = persist_quote_set(
            db,
            _market_set(latest_time, btc_bid="99", btc_ask="101", btc_mark="100"),
        )
        agent = db.get(AgentRun, "agent-1")
        prompt = db.get(PromptVersion, "prompt-1")
        assert agent is not None and prompt is not None
        round_id = str(uuid.uuid4())
        db.add(
            DecisionRound(
                id=round_id,
                competition_id=competition.id,
                round_index=2,
                logical_at=deadline - timedelta(seconds=120),
                snapshot_id=pinned.snapshot_id,
                execution_quote_set_id=pinned.quote_set_id,
                deadline_at=deadline,
            )
        )
        db.flush()
        job_id, fence = _responded_job(
            db,
            round_id=round_id,
            agent_id=agent.id,
            prompt_bytes=prompt.template_bytes,
            now=now,
            output=_proposal_output(proposal_symbol),
        )
        # Keep the protective quote set newer than the round-pinned execution evidence.
        assert latest.quote_set_id != pinned.quote_set_id
        db.commit()

        report = _execute_once(
            sessionmaker(bind=engine, expire_on_commit=False),
            {"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"},
        )
        assert report.state == "READY"

        db.expire_all()
        job = db.get(RoundAgentJob, job_id)
        assert job is not None
        account = db.get(Account, account_id)
        assert account is not None and account.realized_pnl > Decimal("0")
        assert reconcile_ledger(db, competition_id=competition.id).balanced
        closed_btc = db.scalar(
            select(Position).where(
                Position.account_id == account_id,
                Position.symbol == "BTC",
                Position.state == "CLOSED",
            )
        )
        assert closed_btc is not None
        open_eth = db.scalar(
            select(Position).where(
                Position.account_id == account_id,
                Position.symbol == "ETH",
                Position.state == "OPEN",
            )
        )
        if expected_accepted:
            assert job.terminal_result == "SUCCESS"
            assert open_eth is not None
        else:
            assert job.terminal_result == "RISK_REJECTED"
            assert open_eth is None
            risk = db.scalar(
                select(RiskEvaluation)
                .join(TradeProposal, TradeProposal.id == RiskEvaluation.proposal_id)
                .where(TradeProposal.job_id == job_id)
            )
            assert risk is not None
            assert any("protective order" in reason for reason in risk.reasons)
        assert db.scalar(
            select(func.count()).select_from(LedgerJournal).where(
                LedgerJournal.account_id == account_id
            )
        ) == (3 if expected_accepted else 2)
        db.close()
    finally:
        if db is not None:
            db.close()
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_sqlite_reconciliation_reports_tiny_unbalanced_journal() -> None:
    db, _, _, _, account_id = _setup()
    journal_id = str(uuid.uuid4())
    db.add(
        LedgerJournal(
            id=journal_id,
            account_id=account_id,
            event_key="tiny-unbalanced-test",
        )
    )
    db.flush()
    db.add(
        LedgerPosting(
            id=str(uuid.uuid4()),
            journal_id=journal_id,
            bucket="cash",
            amount=Decimal("0.0000000001"),
        )
    )
    db.commit()

    report = reconcile_ledger(db, competition_id="competition-1")

    assert not report.balanced
    assert any(
        mismatch.category == "journal:tiny-unbalanced-test" for mismatch in report.mismatches
    )
    db.close()
