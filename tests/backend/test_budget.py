from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.services.budget import BudgetRejected, _bounded, parse_frozen_competition_budget

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
PG_URL = DATABASE_URL if DATABASE_URL and DATABASE_URL.startswith("postgresql") else None


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (b'{"inference_budget_usd":"2.50"}', Decimal("2.50")),
        (b'{"inference_budget_usd":0}', None),
        (b'{"inference_budget_usd":"NaN"}', None),
        (b"not-json", None),
    ],
)
def test_frozen_budget_parser_is_decimal_and_fail_closed(
    rules: bytes, expected: Decimal | None
) -> None:
    assert parse_frozen_competition_budget(rules) == expected


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("1e30")])
def test_reservation_rejects_nonfinite_or_overflow(value: Decimal) -> None:
    with pytest.raises(BudgetRejected):
        _bounded(value)


@pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_reservation_is_written_before_dispatch_and_survives_restart() -> None:
    from app.db.models import DailyBudget, SpendReservation
    from app.services.invocation import claim_next_job, prepare_invocation_dispatch
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from test_invocation_lifecycle import _pending_job

    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as db:
        job_id = _pending_job(db)
        claim = claim_next_job(db, worker_name="budget-test")
        assert claim is not None and claim.job_id == job_id
        dispatch = prepare_invocation_dispatch(
            db,
            job_id=job_id,
            fence=claim.fence,
            provider="test-provider",
            model="budgeted-model",
            prompt_bytes=b"immutable request prompt",
            public_parameters={"max_output_tokens": 50},
            reservation_amount=Decimal("0.125"),
        )
        assert dispatch is not None
        reservation = db.scalar(select(SpendReservation).where(SpendReservation.job_id == job_id))
        assert reservation is not None and reservation.amount_usd == Decimal("0.125")
        day = reservation.budget_date
        engine.dispose()
        restarted = create_engine(PG_URL, pool_pre_ping=True)
        with Session(restarted) as reopened:
            assert (
                reopened.scalar(
                    select(SpendReservation.id).where(SpendReservation.job_id == job_id)
                )
                == reservation.id
            )
            row = reopened.get(DailyBudget, day)
            assert row is not None and row.reserved_usd >= Decimal("0.125")
        restarted.dispose()


@pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_competition_budget_does_not_reset_at_utc_midnight() -> None:
    from app.db.models import AgentRun, Competition, DecisionRound, RoundAgentJob
    from app.services.budget import reserve_provider_spend
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from test_invocation_lifecycle import _pending_job

    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    with Session(engine) as db:
        first_job_id = _pending_job(db)
        first_job = db.get(RoundAgentJob, first_job_id)
        assert first_job is not None
        round_row = db.get(DecisionRound, first_job.round_id)
        assert round_row is not None
        competition = db.get(Competition, round_row.competition_id)
        assert competition is not None
        original_agent = db.get(AgentRun, first_job.agent_run_id)
        assert original_agent is not None
        second_agent = AgentRun(
            id=str(uuid.uuid4()),
            competition_id=competition.id,
            manifest_order=1,
            name="Second Budget Agent",
            provider="test",
            model="test-model",
            model_settings_bytes=b"{}",
            settings_sha256="3" * 64,
            prompt_version_id=original_agent.prompt_version_id,
            status="ACTIVE",
        )
        db.add(second_agent)
        db.flush()
        second_job = RoundAgentJob(
            id=str(uuid.uuid4()),
            round_id=round_row.id,
            agent_run_id=second_agent.id,
            state="PENDING",
            fence=0,
        )
        db.add(second_job)
        competition.rules_bytes = b'{"inference_budget_usd":"2"}'
        db.commit()

        base_day = datetime.now(UTC).date() + timedelta(days=200 + uuid.uuid4().int % 1000)
        for job_id, day, amount in (
            (first_job.id, base_day, Decimal("1.2")),
            (second_job.id, base_day + timedelta(days=1), Decimal("0.9")),
        ):
            locked_competition = db.scalar(
                select(Competition).where(Competition.id == competition.id).with_for_update()
            )
            assert locked_competition is not None
            admitted = reserve_provider_spend(
                db,
                competition=locked_competition,
                job_id=job_id,
                amount_usd=amount,
                reserved_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            )
            if amount == Decimal("1.2"):
                assert admitted
                db.commit()
            else:
                assert not admitted
                db.rollback()
    engine.dispose()


@pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_global_daily_budget_serializes_different_competitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.budget as budget_service
    from app.core.config import Settings
    from app.db.models import Competition, DecisionRound, RoundAgentJob
    from app.services.budget import reserve_provider_spend
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from test_invocation_lifecycle import _pending_job

    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    monkeypatch.setattr(
        budget_service,
        "get_settings",
        lambda: Settings(database_url=PG_URL, max_daily_llm_spend_usd=Decimal("5")),
    )
    with Session(engine) as db:
        job_ids = [_pending_job(db), _pending_job(db)]
        for job_id in job_ids:
            job = db.get(RoundAgentJob, job_id)
            assert job is not None
            round_row = db.get(DecisionRound, job.round_id)
            assert round_row is not None
            competition = db.get(Competition, round_row.competition_id)
            assert competition is not None
            competition.rules_bytes = b'{"inference_budget_usd":"4"}'
        db.commit()

    target_day = datetime.now(UTC).date() + timedelta(days=1300 + uuid.uuid4().int % 1000)
    barrier = threading.Barrier(2)

    def reserve(job_id: str) -> bool:
        with Session(engine) as db:
            job = db.get(RoundAgentJob, job_id)
            assert job is not None
            round_row = db.get(DecisionRound, job.round_id)
            assert round_row is not None
            competition = db.scalar(
                select(Competition)
                .where(Competition.id == round_row.competition_id)
                .with_for_update()
            )
            assert competition is not None
            barrier.wait(timeout=5)
            admitted = reserve_provider_spend(
                db,
                competition=competition,
                job_id=job.id,
                amount_usd=Decimal("3"),
                reserved_at=datetime.combine(target_day, datetime.min.time(), tzinfo=UTC),
            )
            db.commit()
            return admitted

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, job_ids))
    assert sorted(outcomes) == [False, True]
    engine.dispose()
