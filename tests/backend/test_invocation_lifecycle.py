from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.canonical import canonical_json_bytes
from app.core.rules import canonical_profile
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    InvocationAttempt,
    InvocationResult,
    MarketSnapshot,
    PromptVersion,
    QuoteSet,
    RoundAgentJob,
    SpendReservation,
)
from app.services.invocation import (
    InvocationCompletion,
    apply_invocation_result,
    claim_next_job,
    prepare_invocation_dispatch,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
TEST_DATABASE_URL = (
    _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
)
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


def _id() -> str:
    return str(uuid.uuid4())


def _pending_job(db: Session, deadline_seconds: int = 120) -> str:
    now = datetime.now(UTC)
    stale_jobs = db.scalars(
        select(RoundAgentJob)
        .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
        .join(Competition, Competition.id == DecisionRound.competition_id)
        .where(
            Competition.source_label == "TEST",
            RoundAgentJob.state.in_(("PENDING", "CLAIMED")),
        )
    ).all()
    for stale in stale_jobs:
        stale.state = "TERMINAL"
        stale.terminal_result = "PROVIDER_ERROR"
        stale.error_code = "TEST_RESET"
        stale.lease_owner = None
        stale.lease_expires_at = None
    db.flush()
    competition_id, prompt_id, agent_id = _id(), _id(), _id()
    account_id, quote_set_id, snapshot_id = _id(), _id(), _id()
    round_id, job_id = _id(), _id()
    rules = canonical_profile("alpha_2025_baseline")
    rules["inference_budget_usd"] = "2"
    frozen_rules = canonical_json_bytes(rules)
    db.add(
        Competition(
            id=competition_id,
            name=f"Invocation test {competition_id}",
            profile="alpha_2025_baseline",
            rules_bytes=frozen_rules,
            rules_sha256=hashlib.sha256(frozen_rules).hexdigest(),
            initial_balance=10000,
            state="RUNNING",
            source_label="TEST",
            started_at=now,
            event_seq=0,
        )
    )
    db.add(
        PromptVersion(
            id=prompt_id,
            name=f"test-{prompt_id}",
            version=1,
            template_bytes=b"test prompt",
            sha256="1" * 64,
        )
    )
    db.flush()
    db.add(
        AgentRun(
            id=agent_id,
            competition_id=competition_id,
            manifest_order=0,
            name="Test Agent",
            provider="test",
            model="test-model",
            model_settings_bytes=b"{}",
            settings_sha256="2" * 64,
            prompt_version_id=prompt_id,
            status="ACTIVE",
        )
    )
    db.flush()
    db.add(
        Account(
            id=account_id,
            agent_run_id=agent_id,
            cash=10000,
            realized_pnl=0,
            fees=0,
            funding=0,
            reserved_margin=0,
            halted=False,
            version=0,
        )
    )
    db.add(QuoteSet(id=quote_set_id, source="test", captured_at=now, complete=True))
    db.flush()
    db.add(
        MarketSnapshot(
            id=snapshot_id,
            canonical_bytes=b"{}",
            sha256=hashlib.sha256(snapshot_id.encode()).hexdigest(),
            source_label="TEST",
            captured_at=now,
            quote_set_id=quote_set_id,
        )
    )
    db.flush()
    db.add(
        DecisionRound(
            id=round_id,
            competition_id=competition_id,
            round_index=1,
            logical_at=now,
            snapshot_id=snapshot_id,
            deadline_at=now + timedelta(seconds=deadline_seconds),
        )
    )
    db.flush()
    db.add(
        RoundAgentJob(
            id=job_id,
            round_id=round_id,
            agent_run_id=agent_id,
            state="PENDING",
            fence=0,
        )
    )
    db.commit()
    return job_id


def test_claim_fence_exact_dispatch_and_result_are_durable() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as db:
        job_id = _pending_job(db)
        claim = claim_next_job(db, worker_name="test-worker")
        assert claim is not None and claim.job_id == job_id and claim.fence == 1
        assert claim_next_job(db, worker_name="other-worker") is None

        prompt = b"exact canonical bytes from the dispatcher"
        prepared = prepare_invocation_dispatch(
            db,
            job_id=job_id,
            fence=claim.fence,
            provider="test-provider",
            model="test-model",
            prompt_bytes=prompt,
            public_parameters={"temperature": 0},
            reservation_amount=Decimal("0.1"),
        )
        assert prepared is not None
        receipt = apply_invocation_result(
            db,
            job_id,
            claim.fence,
            InvocationCompletion(
                output_bytes=b'{"action":"HOLD"}',
                usage={"input_tokens": 4, "output_tokens": 3},
                latency_ms=12,
                public_metadata={"adapter": "test"},
            ),
        )
        assert receipt.accepted_for_execution
        assert receipt.state == "RESPONDED"
        attempt = db.scalar(
            select(InvocationAttempt).where(InvocationAttempt.id == prepared.attempt_id)
        )
        result = db.scalar(
            select(InvocationResult).where(InvocationResult.attempt_id == prepared.attempt_id)
        )
        assert attempt is not None and attempt.prompt_bytes == prompt
        assert result is not None and result.output_bytes == b'{"action":"HOLD"}'
        assert result.late is False
    engine.dispose()


def test_expired_round_keeps_result_as_late_evidence_only() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as db:
        job_id = _pending_job(db, deadline_seconds=3)
        claim = claim_next_job(db, worker_name="late-worker")
        assert claim is not None
        prepared = prepare_invocation_dispatch(
            db,
            job_id=job_id,
            fence=claim.fence,
            provider="test-provider",
            model="test-model",
            prompt_bytes=b"late prompt",
            public_parameters={},
            reservation_amount=Decimal("0.1"),
        )
        assert prepared is not None
        time.sleep(3.1)
        receipt = apply_invocation_result(
            db,
            job_id,
            claim.fence,
            InvocationCompletion(output_bytes=b"late exact output"),
        )
        assert not receipt.accepted_for_execution
        assert receipt.late
        assert receipt.state == "TERMINAL"
        result = db.scalar(
            select(InvocationResult).where(InvocationResult.attempt_id == prepared.attempt_id)
        )
        assert result is not None and result.late
    engine.dispose()


def test_budget_denial_terminalizes_without_creating_an_attempt() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as db:
        job_id = _pending_job(db)
        claim = claim_next_job(db, worker_name="budget-worker")
        assert claim is not None
        prepared = prepare_invocation_dispatch(
            db,
            job_id=job_id,
            fence=claim.fence,
            provider="billable-test-provider",
            model="bounded-test-model",
            prompt_bytes=b"must remain undispatched",
            public_parameters={},
            reservation_amount=Decimal("2.01"),
        )
        assert prepared is None
        job = db.get(RoundAgentJob, job_id)
        assert job is not None
        assert job.state == "TERMINAL" and job.error_code == "BUDGET_EXCEEDED"
        assert db.scalar(
            select(InvocationAttempt).where(InvocationAttempt.job_id == job_id)
        ) is None
        assert db.scalar(
            select(SpendReservation).where(SpendReservation.job_id == job_id)
        ) is None
    engine.dispose()
