from __future__ import annotations

import os
import uuid

import pytest
from app.db.models import AgentRun, Competition
from app.services.demo import seed_demo
from app.services.metrics import agent_metrics, btc_buy_and_hold
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
PG_URL = DATABASE_URL if DATABASE_URL and DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")


def test_demo_metrics_are_derived_from_persisted_equity_and_snapshot_series() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    with Session(engine) as db:
        competition_id = seed_demo(db, 20)
        competition = db.get(Competition, competition_id)
        assert competition is not None
        agent = db.scalar(
            select(AgentRun).where(AgentRun.competition_id == competition_id).limit(1)
        )
        assert agent is not None
        metrics = agent_metrics(db, competition, agent)
        benchmark = btc_buy_and_hold(db, competition)
        assert metrics["agent_id"] == agent.id
        assert metrics["max_drawdown_pct"] is not None
        assert metrics["closed_trades"] >= 0
        assert metrics["average_leverage"] is None
        assert benchmark is not None
        assert benchmark["start_at"] < benchmark["end_at"]
        assert benchmark["fee_rate"] == "0.0005"
        assert benchmark["slippage_bps"] == "2"
        assert benchmark["equity"] != str(competition.initial_balance)
    engine.dispose()


def test_metrics_require_two_historical_btc_snapshots() -> None:
    """A competition with no two-point market series gets no fabricated benchmark."""
    from app.db.models import Competition as CompetitionRow

    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    identifier = str(uuid.uuid4())
    row = CompetitionRow(
        id=identifier,
        name=f"No market series {identifier}",
        profile="baseline",
        rules_bytes=b'{"fee_rate":"0.001","slippage_bps":"1"}',
        rules_sha256="a" * 64,
        initial_balance=100,
        state="DRAFT",
        source_label="TEST",
        event_seq=0,
    )
    with Session(engine) as db:
        db.add(row)
        db.commit()
        stored = db.get(CompetitionRow, identifier)
        assert stored is not None and btc_buy_and_hold(db, stored) is None
    engine.dispose()
