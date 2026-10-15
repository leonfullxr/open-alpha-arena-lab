from __future__ import annotations

import os

import pytest
from app.db.models import AgentRun, Competition
from app.db.session import get_db
from app.main import app
from app.services.demo import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
TEST_DATABASE_URL = (
    _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
)
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


def test_public_endpoints_emit_safe_paged_durable_demo_data() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as db:
        competition_id = seed_demo(db, 20)
        competition = db.get(Competition, competition_id)
        assert competition is not None
        agent = db.scalar(
            select(AgentRun).where(AgentRun.competition_id == competition_id).limit(1)
        )
        assert agent is not None

    def test_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(app) as client:
            root = "/api/v1/public"
            competition_response = client.get(f"{root}/competitions/{competition_id}")
            assert competition_response.status_code == 200
            assert competition_response.json()["source_label"].startswith("DEMO REPLAY")

            equity_response = client.get(
                f"{root}/competitions/{competition_id}/equity?limit=5&offset=0"
            )
            equity = equity_response.json()
            assert equity_response.status_code == 200
            assert len(equity["items"]) == 5
            assert equity["total"] == 42
            assert equity["limit"] == 5 and equity["offset"] == 0

            event_response = client.get(
                f"{root}/competitions/{competition_id}/events?after=0&limit=3"
            )
            events = event_response.json()
            assert event_response.status_code == 200
            assert len(events["items"]) == 3 and events["has_more"]
            assert events["next_after"] == events["items"][-1]["sequence"]

            decisions_response = client.get(
                f"{root}/competitions/{competition_id}/decisions?limit=2"
            )
            decisions = decisions_response.json()
            assert decisions_response.status_code == 200
            assert len(decisions["items"]) == 2 and decisions["total"] == 40
            first = decisions["items"][0]
            assert "reasoning" not in first and "private_reasoning" not in first
            artifact = client.get(first["artifact_url"])
            assert artifact.status_code == 200
            assert artifact.json()["prompt_sha256"] == first["prompt_sha256"]

            model = client.get(f"{root}/models/{agent.id}").json()
            assert model["source_label"] == "DEMO REPLAY"
            assert "api_key_env" not in model and "api_key" not in model
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
