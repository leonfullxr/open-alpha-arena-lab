from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.canonical import canonical_json_bytes, sha256_hex
from app.db.models import AgentRun, Base, Competition, DecisionRound, MarketSnapshot, QuoteSet
from app.db.session import get_db
from app.main import app, public_app
from app.services.demo import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
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
        agents = list(
            db.scalars(
                select(AgentRun)
                .where(AgentRun.competition_id == competition_id)
                .order_by(AgentRun.manifest_order)
            )
        )
        assert [agent.name for agent in agents] == [
            "Atlas",
            "Vector",
            "Grok (simulated)",
            "Gemini (simulated)",
            "Claude (simulated)",
            "Codex (simulated)",
        ]

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
            assert equity["total"] == 126
            assert equity["limit"] == 5 and equity["offset"] == 0

            chart = client.get(
                f"{root}/competitions/{competition_id}/chart?range=ALL&points=3"
            )
            chart_body = chart.json()
            assert chart.status_code == 200
            assert chart_body["range"] == "ALL"
            assert chart_body["points"] == 3
            assert chart_body["total_raw"] == 126
            assert chart_body["sampled"]
            assert len(chart_body["items"]) == 18
            assert {item["agent_id"] for item in chart_body["items"]} == {
                agent.id for agent in agents
            }
            for agent_id in {item["agent_id"] for item in chart_body["items"]}:
                agent_points = [
                    item for item in chart_body["items"] if item["agent_id"] == agent_id
                ]
                assert len(agent_points) == 3
                assert [item["round"] for item in agent_points] == [0, 10, 20]

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
            assert len(decisions["items"]) == 2 and decisions["total"] == 120
            first = decisions["items"][0]
            assert "reasoning" not in first and "private_reasoning" not in first
            artifact = client.get(first["artifact_url"])
            assert artifact.status_code == 200
            assert artifact.json()["prompt_sha256"] == first["prompt_sha256"]

            model = client.get(f"{root}/models/{agents[0].id}").json()
            assert model["source_label"] == "DEMO REPLAY"
            assert "api_key_env" not in model and "api_key" not in model
            before = len(client.get(f"{root}/competitions").json())
            assert client.post(f"{root}/competitions").status_code == 405
            assert client.put(f"{root}/competitions/{competition_id}").status_code == 405
            assert client.delete(f"{root}/ticker").status_code == 405
            assert len(client.get(f"{root}/competitions").json()) == before
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_decision_history_projects_batches_errors_and_malformed_evidence_safely() -> None:
    from decimal import Decimal

    from app.db.models import DecisionRound, RoundAgentJob, TradeProposal
    from app.services.invocation import (
        InvocationCompletion,
        apply_invocation_result,
        claim_next_job,
        prepare_invocation_dispatch,
        terminalize_undispatched,
    )
    from test_invocation_lifecycle import _pending_job

    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    prepared: list[tuple[str, str, str | None]] = []
    with Session(engine, expire_on_commit=False) as db:
        batch_job = _pending_job(db)
        batch_competition = db.scalar(
            select(Competition)
            .join(DecisionRound, DecisionRound.competition_id == Competition.id)
            .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
            .where(RoundAgentJob.id == batch_job)
        )
        assert batch_competition is not None
        batch_competition.source_label = "DEMO REPLAY TEST"
        db.commit()
        claim = claim_next_job(db, worker_name="public-evidence-test")
        assert claim is not None and claim.job_id == batch_job
        attempt = prepare_invocation_dispatch(
            db,
            job_id=batch_job,
            fence=claim.fence,
            provider="MockLLMAdapter",
            model="batch-model",
            prompt_bytes=b"safe prompt",
            public_parameters={},
            reservation_amount=Decimal("0.1"),
        )
        assert attempt is not None
        batch_output = (
            b'{"proposals":['
            b'{"action":"OPEN_LONG","symbol":"BTC","quantity":1,"leverage":2,'
            b'"stop_loss":null,"take_profit":null,"confidence":0.75,'
            b'"invalidation":"trend breaks","justification":"support holds"},'
            b'{"action":"OPEN_SHORT","symbol":"ETH","quantity":2,"leverage":1,'
            b'"stop_loss":null,"take_profit":null,"confidence":0.6,'
            b'"invalidation":"resistance breaks","justification":"rejection confirmed"}]}'
        )
        apply_invocation_result(db, batch_job, claim.fence, InvocationCompletion(batch_output))
        db.add_all(
            [
                TradeProposal(
                    id=str(uuid.uuid4()),
                    job_id=batch_job,
                    sequence=sequence,
                    action=action,
                    symbol=symbol,
                    quantity=Decimal(quantity),
                    raw_bytes=b"{}",
                )
                for sequence, (action, symbol, quantity) in enumerate(
                    (("OPEN_LONG", "BTC", "1"), ("OPEN_SHORT", "ETH", "2"))
                )
            ]
        )
        db.commit()
        prepared.append((claim.competition_id, batch_job, None))

        bad_job = _pending_job(db)
        bad_competition = db.scalar(
            select(Competition)
            .join(DecisionRound, DecisionRound.competition_id == Competition.id)
            .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
            .where(RoundAgentJob.id == bad_job)
        )
        assert bad_competition is not None
        bad_competition.source_label = "DEMO REPLAY TEST"
        bad_agent = db.scalar(
            select(AgentRun)
            .join(RoundAgentJob, RoundAgentJob.agent_run_id == AgentRun.id)
            .where(RoundAgentJob.id == bad_job)
        )
        assert bad_agent is not None
        bad_agent.provider = "MockLLMAdapter"
        db.commit()
        claim_bad = claim_next_job(db, worker_name="public-evidence-test")
        assert claim_bad is not None and claim_bad.job_id == bad_job
        attempt_bad = prepare_invocation_dispatch(
            db,
            job_id=bad_job,
            fence=claim_bad.fence,
            provider="MockLLMAdapter",
            model="bad-model",
            prompt_bytes=b"safe prompt",
            public_parameters={},
            reservation_amount=Decimal("0.1"),
        )
        assert attempt_bad is not None
        legacy_output = (
            b'{"action":"OPEN_LONG","symbol":"BTC","quantity":"1",'
            b'"justification":"SECRET_CANARY justification",'
            b'"market_summary":"SECRET_CANARY summary"}'
        )
        apply_invocation_result(
            db,
            bad_job,
            claim_bad.fence,
            InvocationCompletion(legacy_output),
        )
        prepared.append((claim_bad.competition_id, bad_job, attempt_bad.attempt_id))

        missing_job = _pending_job(db)
        claim_missing = claim_next_job(db, worker_name="public-evidence-test")
        assert claim_missing is not None and claim_missing.job_id == missing_job
        assert terminalize_undispatched(
            db,
            job_id=missing_job,
            fence=claim_missing.fence,
            error_code="PROVIDER_NOT_CONFIGURED",
        )
        prepared.append((claim_missing.competition_id, missing_job, None))

    def test_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(app) as client:
            root = "/api/v1/public"
            comp_id, _, _ = prepared[0]
            batch = client.get(f"{root}/competitions/{comp_id}/decisions?limit=10").json()
            item = batch["items"][0]
            assert item["validation_status"] == "VALID"
            assert [p["symbol"] for p in item["proposals"]] == ["BTC", "ETH"]
            batch_export = client.get(f"{root}/competitions/{comp_id}/export?limit=10")
            assert batch_export.status_code == 200
            assert batch_export.json()["exported_decisions"] == 1
            assert batch_export.json()["decisions"][0]["validation_status"] == "VALID"
            filtered = client.get(
                f"{root}/competitions/{comp_id}/decisions?symbol=ETH&limit=10"
            ).json()
            assert filtered["total"] == 1
            assert any(p["symbol"] == "ETH" for p in filtered["items"][0]["proposals"])

            bad_comp, _, bad_attempt_id = prepared[1]
            malformed = client.get(f"{root}/competitions/{bad_comp}/decisions").json()["items"][0]
            assert malformed["validation_status"] == "INVALID"
            assert malformed["validation_errors"] == ["INVALID_PROPOSAL_OUTPUT"]
            assert malformed["proposals"] == [] and malformed["justification"] is None
            assert malformed["output_sha256"] == hashlib.sha256(legacy_output).hexdigest()
            assert "SECRET_CANARY" not in str(malformed)
            artifact_url = f"{root}/decisions/{bad_attempt_id}/artifact"
            artifact = client.get(artifact_url).json()
            assert artifact["output_publicly_releasable"] is False
            assert artifact["output_bytes_base64"] == ""
            assert artifact["output_sha256"] == hashlib.sha256(legacy_output).hexdigest()
            bad_export = client.get(f"{root}/competitions/{bad_comp}/export?limit=10")
            assert bad_export.status_code == 200
            assert bad_export.json()["exported_decisions"] == 1
            assert "SECRET_CANARY" not in str(bad_export.json())

            missing_comp, _, _ = prepared[2]
            missing = client.get(f"{root}/competitions/{missing_comp}/decisions").json()
            assert len(missing["items"]) == 1
            assert missing["items"][0]["error_code"] == "PROVIDER_NOT_CONFIGURED"
            assert missing["items"][0]["artifact_url"] is None
            missing_export = client.get(f"{root}/competitions/{missing_comp}/export?limit=10")
            assert missing_export.status_code == 200
            assert missing_export.json()["exported_decisions"] == 1
            assert missing_export.json()["decisions"][0]["error_code"] == "PROVIDER_NOT_CONFIGURED"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_live_ticker_uses_latest_collector_snapshot_and_unknown_competition_is_404() -> None:
    assert TEST_DATABASE_URL is not None
    schema = f"ticker_{uuid.uuid4().hex}"
    admin_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    competition_id = str(uuid.uuid4())
    round_id = str(uuid.uuid4())
    older_set_id, older_snapshot_id = str(uuid.uuid4()), str(uuid.uuid4())
    newest_set_id, newest_snapshot_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(
            Competition(
                id=competition_id,
                name="Live ticker test",
                profile="alpha_2025_baseline",
                rules_bytes=b"{}",
                rules_sha256=hashlib.sha256(b"{}").hexdigest(),
                initial_balance=Decimal("10000"),
                state="RUNNING",
                source_label="LIVE TEST",
                started_at=now - timedelta(minutes=10),
                ended_at=None,
                event_seq=0,
            )
        )
        db.add_all(
            [
                QuoteSet(
                    id=older_set_id,
                    source="hyperliquid",
                    captured_at=now - timedelta(minutes=3),
                    complete=True,
                    max_age_ms=1000,
                    skew_ms=0,
                ),
                QuoteSet(
                    id=newest_set_id,
                    source="hyperliquid",
                    captured_at=now,
                    complete=True,
                    max_age_ms=100,
                    skew_ms=0,
                ),
            ]
        )
        db.flush()
        for snapshot_id, quote_set_id, captured_at, mark in (
            (older_snapshot_id, older_set_id, now - timedelta(minutes=3), "90"),
            (newest_snapshot_id, newest_set_id, now, "100"),
        ):
            raw = canonical_json_bytes(
                {
                    "quotes": {
                        "BTC": {
                            "bid": mark,
                            "ask": mark,
                            "mark": mark,
                            "event_at": captured_at.isoformat(),
                            "received_at": captured_at.isoformat(),
                        }
                    }
                }
            )
            db.add(
                MarketSnapshot(
                    id=snapshot_id,
                    canonical_bytes=raw,
                    sha256=sha256_hex(raw),
                    source_label="hyperliquid",
                    captured_at=captured_at,
                    quote_set_id=quote_set_id,
                )
            )
        db.flush()
        db.add(
            DecisionRound(
                id=round_id,
                competition_id=competition_id,
                round_index=0,
                logical_at=now - timedelta(minutes=3),
                snapshot_id=older_snapshot_id,
                execution_quote_set_id=older_set_id,
                deadline_at=now - timedelta(minutes=1),
            )
        )
        db.commit()
    with Session(engine) as db:
        assert db.get(Competition, competition_id) is not None

    def test_session():
        with Session(engine) as db:
            yield db

    public_app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(public_app) as client:
            response = client.get(f"/ticker?competition_id={competition_id}")
            assert response.status_code == 200, response.text
            assert response.json()[0]["mark"] == "100"
            assert response.json()[0]["stale"] is False
            assert client.get(
                "/ticker?competition_id=missing-competition"
            ).status_code == 404
    finally:
        public_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
