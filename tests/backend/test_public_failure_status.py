from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from app.db.models import (
    Competition,
    DecisionRound,
    InvocationResult,
    RoundAgentJob,
)
from app.db.session import get_db
from app.main import app
from app.services.invocation import (
    InvocationCompletion,
    apply_invocation_result,
    claim_next_job,
    prepare_invocation_dispatch,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
_POSTGRES_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(_POSTGRES_URL is None, reason="TEST_DATABASE_URL is not configured")


@pytest.mark.parametrize("invalid_status", [True, 99, 600, "429", None])
def test_decision_history_exposes_only_bounded_provider_http_status(invalid_status: object) -> None:
    assert _POSTGRES_URL is not None
    from test_invocation_lifecycle import _pending_job

    engine = create_engine(_POSTGRES_URL, pool_pre_ping=True)
    prepared: list[tuple[str, str]] = []
    with Session(engine, expire_on_commit=False) as db:
        valid_job = _pending_job(db)
        valid_competition = _competition_for_job(db, valid_job)
        valid_competition.source_label = "DEMO REPLAY HTTP STATUS TEST"
        db.commit()
        valid_claim = claim_next_job(db, worker_name="public-http-status-test")
        assert valid_claim is not None and valid_claim.job_id == valid_job
        valid_attempt = prepare_invocation_dispatch(
            db,
            job_id=valid_job,
            fence=valid_claim.fence,
            provider="test",
            model="status-model",
            prompt_bytes=b"safe prompt",
            public_parameters={},
            reservation_amount=Decimal("0.01"),
        )
        assert valid_attempt is not None
        apply_invocation_result(
            db,
            valid_job,
            valid_claim.fence,
            InvocationCompletion(
                output_bytes=b"",
                error_code="PROVIDER_HTTP_ERROR",
                public_metadata={"status_code": 429},
            ),
        )
        prepared.append((valid_claim.competition_id, valid_job))

        invalid_job = _pending_job(db)
        invalid_competition = _competition_for_job(db, invalid_job)
        invalid_competition.source_label = "DEMO REPLAY HTTP STATUS TEST"
        db.commit()
        invalid_claim = claim_next_job(db, worker_name="public-http-status-test")
        assert invalid_claim is not None and invalid_claim.job_id == invalid_job
        invalid_attempt = prepare_invocation_dispatch(
            db,
            job_id=invalid_job,
            fence=invalid_claim.fence,
            provider="test",
            model="invalid-status-model",
            prompt_bytes=b"safe prompt",
            public_parameters={},
            reservation_amount=Decimal("0.01"),
        )
        assert invalid_attempt is not None
        db.add(
            InvocationResult(
                id=str(uuid.uuid4()),
                attempt_id=invalid_attempt.attempt_id,
                output_bytes=b"",
                output_sha256=hashlib.sha256(b"").hexdigest(),
                latency_ms=None,
                estimated_cost_usd=None,
                usage={},
                error_code="PROVIDER_HTTP_ERROR",
                late=False,
                public_metadata={
                    "status_code": invalid_status,
                    "private_transport_body": "PRIVATE_CANARY",
                    "authorization": "SECRET_CANARY",
                },
            )
        )
        db.commit()
        prepared.append((invalid_claim.competition_id, invalid_job))

    def test_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(app) as client:
            for competition_id, job_id in prepared:
                response = client.get(
                    f"/api/v1/public/competitions/{competition_id}/decisions?limit=10"
                )
                assert response.status_code == 200
                decision = response.json()["items"][0]
                assert decision["id"]
                if job_id == prepared[0][1]:
                    assert decision["error_code"] == "PROVIDER_HTTP_ERROR"
                    assert decision["provider_status_code"] == 429
                else:
                    assert decision["provider_status_code"] is None
                    assert "PRIVATE_CANARY" not in response.text
                    assert "SECRET_CANARY" not in response.text
                    assert "private_transport_body" not in response.text
                    assert "authorization" not in response.text.lower()
                    assert "PRIVATE_CANARY" not in str(response.headers)
                    assert "SECRET_CANARY" not in str(response.headers)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _competition_for_job(db: Session, job_id: str) -> Competition:
    competition = db.scalar(
        select(Competition)
        .join(DecisionRound, DecisionRound.competition_id == Competition.id)
        .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
        .where(RoundAgentJob.id == job_id)
    )
    assert competition is not None
    return competition
