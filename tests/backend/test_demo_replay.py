import base64
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from app.api.public import router as public_router
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
from app.db.session import get_db
from app.services.demo import seed_demo, stable_id
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


def test_demo_is_durable_idempotent_and_reproducible_after_engine_restart(tmp_path) -> None:
    path = tmp_path / "demo.sqlite3"
    url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        legacy_id = stable_id("demo:competition")
        legacy_rules = b"{}"
        legacy = Competition(
            id=legacy_id,
            name="Offline Paper Arena · 20 rounds",
            profile="alpha_2025_baseline",
            rules_bytes=legacy_rules,
            rules_sha256=hashlib.sha256(legacy_rules).hexdigest(),
            initial_balance=Decimal("10000"),
            state="FINISHED",
            source_label="DEMO REPLAY · legacy immutable fixture",
            event_seq=0,
        )
        db.add(legacy)
        db.add(
            PromptVersion(
                id=stable_id("demo:prompt:v1"),
                name="baseline",
                version=1,
                template_bytes=b"legacy prompt fixture",
                sha256=hashlib.sha256(b"legacy prompt fixture").hexdigest(),
            )
        )
        legacy_v2_id = stable_id("demo:v2:20:competition")
        legacy_v2_rules = b'{"fixture_source":"fixture-replay-v2"}'
        legacy_v2 = Competition(
            id=legacy_v2_id,
            name="Offline Paper Arena · proposal evidence v2 · 20 rounds",
            profile="alpha_2025_baseline",
            rules_bytes=legacy_v2_rules,
            rules_sha256=hashlib.sha256(legacy_v2_rules).hexdigest(),
            initial_balance=Decimal("10000"),
            state="FINISHED",
            source_label="DEMO REPLAY · proposal evidence v2 · preserved fixture",
            event_seq=80,
        )
        legacy_v2_prompt_bytes = b"legacy v2 prompt fixture"
        db.add(legacy_v2)
        db.add(
            PromptVersion(
                id=stable_id("demo:v2:prompt"),
                name="baseline",
                version=2,
                template_bytes=legacy_v2_prompt_bytes,
                sha256=hashlib.sha256(legacy_v2_prompt_bytes).hexdigest(),
            )
        )
        legacy_v2_agent_id = stable_id("demo:v2:20:agent:atlas")
        legacy_v2_account_id = stable_id("demo:v2:20:account:atlas")
        legacy_v2_settings = b"{}"
        db.add(
            AgentRun(
                id=legacy_v2_agent_id,
                competition_id=legacy_v2_id,
                manifest_order=0,
                name="Legacy v2 Atlas",
                provider="MockLLMAdapter",
                model="mock-atlas-v2",
                provider_profile_id=None,
                model_settings_bytes=legacy_v2_settings,
                settings_sha256=hashlib.sha256(legacy_v2_settings).hexdigest(),
                prompt_version_id=stable_id("demo:v2:prompt"),
                api_key_env=None,
                status="FINISHED",
            )
        )
        db.add(
            Account(
                id=legacy_v2_account_id,
                agent_run_id=legacy_v2_agent_id,
                cash=Decimal("10000"),
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
                reserved_margin=Decimal("0"),
                halted=False,
                peak_equity=Decimal("10000"),
                daily_baseline_equity=Decimal("10000"),
                risk_day=datetime(2024, 1, 1, tzinfo=UTC).date(),
                version=0,
            )
        )
        legacy_v2_closed_at = datetime(2024, 2, 2, tzinfo=UTC)
        legacy_v2_position_id = stable_id("demo:v2:20:position:atlas:BTC")
        db.add(
            Position(
                id=legacy_v2_position_id,
                account_id=legacy_v2_account_id,
                symbol="BTC",
                side="LONG",
                quantity=Decimal("0.02"),
                average_entry=Decimal("95000"),
                reserved_margin=Decimal("950"),
                stop_loss=Decimal("90000"),
                take_profit=Decimal("100000"),
                state="CLOSED",
                opened_at=datetime(2024, 2, 1, tzinfo=UTC),
                closed_at=legacy_v2_closed_at,
            )
        )
        legacy_agent_id = stable_id("demo:agent:atlas")
        legacy_account_id = stable_id("demo:account:atlas")
        legacy_settings = b"{}"
        db.add(
            AgentRun(
                id=legacy_agent_id,
                competition_id=legacy_id,
                manifest_order=0,
                name="Legacy Atlas",
                provider="MockLLMAdapter",
                model="mock-atlas-v1",
                provider_profile_id=None,
                model_settings_bytes=legacy_settings,
                settings_sha256=hashlib.sha256(legacy_settings).hexdigest(),
                prompt_version_id=stable_id("demo:prompt:v1"),
                api_key_env=None,
                status="FINISHED",
            )
        )
        db.add(
            Account(
                id=legacy_account_id,
                agent_run_id=legacy_agent_id,
                cash=Decimal("10000"),
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
                reserved_margin=Decimal("0"),
                halted=False,
                peak_equity=Decimal("10000"),
                daily_baseline_equity=Decimal("10000"),
                risk_day=datetime(2024, 1, 1, tzinfo=UTC).date(),
                version=3,
            )
        )
        legacy_closed_at = datetime(2024, 1, 2, tzinfo=UTC)
        legacy_position_id = stable_id("demo:position:atlas:BTC")
        db.add(
            Position(
                id=legacy_position_id,
                account_id=legacy_account_id,
                symbol="BTC",
                side="LONG",
                quantity=Decimal("0.02"),
                average_entry=Decimal("95000"),
                reserved_margin=Decimal("950"),
                stop_loss=Decimal("90000"),
                take_profit=Decimal("100000"),
                state="CLOSED",
                opened_at=datetime(2024, 1, 1, tzinfo=UTC),
                closed_at=legacy_closed_at,
            )
        )
        db.flush()
        competition_id = seed_demo(db, 20)
        assert competition_id != legacy_id
        snapshot = list(
            db.scalars(
                select(EquitySample).order_by(EquitySample.account_id, EquitySample.round_index)
            )
        )
        fixture = db.get(Competition, competition_id)
        assert fixture is not None and fixture.ended_at is not None
        last_logical_at = max(row.logical_at for row in snapshot)
        persisted_ended_at = fixture.ended_at
        if last_logical_at.tzinfo is None:
            last_logical_at = last_logical_at.replace(tzinfo=UTC)
        if persisted_ended_at.tzinfo is None:
            persisted_ended_at = persisted_ended_at.replace(tzinfo=UTC)
        assert last_logical_at <= persisted_ended_at
        first_values = [(row.account_id, row.round_index, str(row.equity)) for row in snapshot]
        assert len(first_values) == 42
        assert all(
            value == "10000.000000000000000000"
            for _, round_index, value in first_values
            if round_index == 0
        )
        assert all(row.equity > Decimal("0") for row in snapshot)
        assert db.scalar(select(func.count()).select_from(InvocationAttempt)) == 40
        assert db.scalar(select(func.count()).select_from(InvocationResult)) == 40
        assert db.scalar(select(func.count()).select_from(TradeProposal)) == 80
        assert db.scalar(select(func.count()).select_from(RiskEvaluation)) == 80
        decisions = list(db.scalars(select(RiskEvaluation).order_by(RiskEvaluation.id)))
        assert sum(row.decision == "ACCEPTED" for row in decisions) == 40
        assert sum(row.decision == "REJECTED" for row in decisions) == 40
        assert all(
            row.reasons == [] if row.decision == "ACCEPTED" else len(row.reasons) == 1
            for row in decisions
        )
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 20
        assert db.scalar(select(func.count()).select_from(QuoteSet)) == 20
        assert db.scalar(select(func.count()).select_from(MarketQuote)) == 120
        assert db.scalar(select(func.count()).select_from(Order)) > 0
        assert db.scalar(select(func.count()).select_from(LedgerPosting)) > 0
        fixture_events = list(
            db.scalars(
                select(DomainEvent).where(
                    DomainEvent.competition_id == competition_id,
                    DomainEvent.event_type == "agent.decision",
                )
            )
        )
        fixture_orders = list(db.scalars(select(Order)))
        fixture_fills = list(db.scalars(select(Fill)))
        assert fixture_orders and fixture_fills
        for order in fixture_orders:
            assert order.event_sequence is not None
            assert order.quote_set_id is not None
            proposal = db.get(TradeProposal, order.proposal_id)
            assert proposal is not None
            job = db.get(RoundAgentJob, proposal.job_id)
            assert job is not None
            round_row = db.get(DecisionRound, job.round_id)
            assert round_row is not None
            assert order.quote_set_id == round_row.execution_quote_set_id
            linked_events = [
                event
                for event in fixture_events
                if event.account_id == order.account_id
                and event.payload.get("round") == round_row.round_index
            ]
            assert len(linked_events) == 1
            assert order.event_sequence == linked_events[0].sequence
            order_fills = sorted(
                (fill for fill in fixture_fills if fill.order_id == order.id),
                key=lambda fill: fill.ordinal if fill.ordinal is not None else -1,
            )
            assert [fill.ordinal for fill in order_fills] == list(range(len(order_fills)))
            assert all(fill.executed_at == round_row.logical_at for fill in order_fills)
        # Repeating the seed returns the existing replay without appending any rows.
        assert seed_demo(db, 20) == competition_id
        assert db.scalar(select(func.count()).select_from(EquitySample)) == 42
        assert db.scalar(select(func.count()).select_from(TradeProposal)) == 80
        assert db.scalar(select(func.count()).select_from(RiskEvaluation)) == 80
        assert db.get(Competition, legacy_id) == legacy
        preserved_v2 = db.get(Competition, legacy_v2_id)
        assert preserved_v2 is not None
        assert preserved_v2.rules_bytes == legacy_v2_rules
        assert preserved_v2.source_label == "DEMO REPLAY · proposal evidence v2 · preserved fixture"
        preserved_v2_position = db.get(Position, legacy_v2_position_id)
        assert preserved_v2_position is not None
        assert preserved_v2_position.state == "CLOSED"
        assert preserved_v2_position.closed_at is not None
        assert preserved_v2_position.closed_at.replace(tzinfo=UTC) == legacy_v2_closed_at
        legacy_prompt = db.get(PromptVersion, stable_id("demo:prompt:v1"))
        assert legacy_prompt is not None
        assert legacy_prompt.template_bytes == b"legacy prompt fixture"
        closed_legacy = db.get(Position, legacy_position_id)
        assert closed_legacy is not None
        assert closed_legacy.state == "CLOSED"
        assert closed_legacy.closed_at is not None
        assert closed_legacy.closed_at.replace(tzinfo=UTC) == legacy_closed_at
        preserved_v2_prompt = db.get(PromptVersion, stable_id("demo:v2:prompt"))
        assert preserved_v2_prompt is not None
        assert preserved_v2_prompt.template_bytes == legacy_v2_prompt_bytes
        fixture_prompt = db.get(PromptVersion, stable_id("demo:v3:prompt"))
        assert fixture_prompt is not None and fixture_prompt.version == 3
        original_leaderboard = [
            str(a.cash) for a in db.scalars(select(Account).order_by(Account.id))
        ]
    engine.dispose()

    restarted_engine = create_engine(url)
    restarted_factory = sessionmaker(restarted_engine, expire_on_commit=False)
    with restarted_factory() as db:
        competition = db.get(Competition, competition_id)
        persisted = list(
            db.scalars(
                select(EquitySample).order_by(EquitySample.account_id, EquitySample.round_index)
            )
        )
        assert competition is not None and competition.state == "FINISHED"
        assert competition.source_label.startswith("DEMO REPLAY")
        assert [
            (row.account_id, row.round_index, str(row.equity)) for row in persisted
        ] == first_values
        assert [
            str(a.cash) for a in db.scalars(select(Account).order_by(Account.id))
        ] == original_leaderboard
        closed_legacy = db.get(Position, legacy_position_id)
        assert closed_legacy is not None and closed_legacy.closed_at is not None
        assert closed_legacy.closed_at.replace(tzinfo=UTC) == legacy_closed_at
        preserved_v2_position = db.get(Position, legacy_v2_position_id)
        assert preserved_v2_position is not None and preserved_v2_position.closed_at is not None
        assert preserved_v2_position.closed_at.replace(tzinfo=UTC) == legacy_v2_closed_at

        app = FastAPI()
        app.include_router(public_router, prefix="/api/v1/public")

        def test_session():
            with factory() as session:
                yield session

        app.dependency_overrides[get_db] = test_session
        try:
            with TestClient(app) as client:
                competition_response = client.get(f"/api/v1/public/competitions/{competition_id}")
                assert competition_response.status_code == 200
                api_ended_at = datetime.fromisoformat(competition_response.json()["ended_at"])
                api_last_logical_at = max(row.logical_at for row in persisted)
                if api_last_logical_at.tzinfo is None:
                    api_last_logical_at = api_last_logical_at.replace(tzinfo=UTC)
                if api_ended_at.tzinfo is None:
                    api_ended_at = api_ended_at.replace(tzinfo=UTC)
                assert api_last_logical_at <= api_ended_at
                rules_response = client.get(f"/api/v1/public/competitions/{competition_id}/rules")
                assert rules_response.status_code == 200
                rules_body = rules_response.json()
                rules_bytes = base64.b64decode(rules_body["bytes_base64"], validate=True)
                assert hashlib.sha256(rules_bytes).hexdigest() == rules_body["sha256"]
                assert rules_bytes == competition.rules_bytes
                assert rules_body["public"]["fixture_source"] == "fixture-replay-v3"
                assert rules_body["withheld_fields"] is False
                assert rules_body["bytes_withheld"] is False
                trade_response = client.get(
                    f"/api/v1/public/competitions/{competition_id}/trades?limit=200"
                )
                assert trade_response.status_code == 200
                trade_body = trade_response.json()
                assert trade_body["total"] == len(fixture_fills)
                decision_response = client.get(
                    f"/api/v1/public/competitions/{competition_id}/decisions?limit=200"
                )
                assert decision_response.status_code == 200
                decision_ids = {
                    (row["agent_id"], row["round"]): row["id"]
                    for row in decision_response.json()["items"]
                }
                event_sequences = {
                    (str(event.payload["agent_id"]), int(event.payload["round"])): event.sequence
                    for event in fixture_events
                }
                assert trade_body["items"]
                for trade in trade_body["items"]:
                    key = (trade["agent_id"], trade["round"])
                    assert trade["order_kind"] == "MARKET"
                    assert trade["decision_id"] == decision_ids[key]
                    assert trade["proposal_sequence"] == 0
                    assert trade["executed_at"] is not None
                    assert trade["event_sequence"] == event_sequences[key]
                    assert trade["fill_ordinal"] is not None
                    assert trade["quote_set_id"] is not None
                    assert trade["execution_quote"] is not None
                decision_page = client.get(
                    f"/api/v1/public/competitions/{competition_id}/decisions?limit=1"
                )
                assert decision_page.status_code == 200
                body = decision_page.json()
                assert body["total"] == 40
                decision = body["items"][0]
                assert decision["validation_status"] == "VALID"
                assert decision["execution_result"] == "SUCCESS"
                assert len(decision["proposals"]) == 2
                accepted, rejected = decision["proposals"]
                assert accepted["risk_decision"] == "ACCEPTED"
                assert accepted["leverage"] == "2"
                assert accepted["confidence"] is not None
                assert accepted["stop_loss"] is not None
                assert accepted["take_profit"] is not None
                assert accepted["invalidation"]
                assert rejected["risk_decision"] == "REJECTED"
                assert "leverage" in rejected["risk_reasons"][0]
                artifact = client.get(decision["artifact_url"])
                assert artifact.status_code == 200
                artifact_body = artifact.json()
                request_bytes = base64.b64decode(
                    artifact_body["prompt_bytes_base64"], validate=True
                )
                output_bytes = base64.b64decode(artifact_body["output_bytes_base64"], validate=True)
                assert hashlib.sha256(request_bytes).hexdigest() == decision["prompt_sha256"]
                assert hashlib.sha256(output_bytes).hexdigest() == decision["output_sha256"]
                assert artifact_body["output_publicly_releasable"]
        finally:
            app.dependency_overrides.pop(get_db, None)
    restarted_engine.dispose()
