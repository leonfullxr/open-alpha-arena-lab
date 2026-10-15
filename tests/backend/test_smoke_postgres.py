from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from app.db.models import Account, AgentRun, Competition
from app.llm.smoke import (
    _create_competition,
    _load_config,
    _preflight_smoke_inputs,
)
from app.market.indicators import INDICATOR_POLICY, INDICATOR_WARMUP_BARS
from app.market.persistence import persist_quote_set
from app.market.types import (
    BASELINE_SYMBOLS,
    CandleBar,
    CandleFeatures,
    InstrumentSpec,
    MarketQuote,
    MarketQuoteSet,
)
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
_POSTGRES_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(_POSTGRES_URL is None, reason="TEST_DATABASE_URL is not configured")


def test_smoke_setup_and_preflight_on_migrated_postgres_without_provider_calls() -> None:
    assert _POSTGRES_URL is not None
    root = Path(__file__).resolve().parents[2]
    schema = f"arena_smoke_setup_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_POSTGRES_URL, pool_pre_ping=True)
    engine: Engine | None = None
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = make_url(_POSTGRES_URL).set(
        drivername="postgresql+psycopg",
        query={"options": f"-csearch_path={schema},pg_catalog"},
    )
    env = os.environ.copy()
    env["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, ("services/api", env.get("PYTHONPATH"))))
    migration = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "services/api/alembic.ini",
            "upgrade",
            "head",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert migration.returncode == 0, "isolated Alembic upgrade failed"

    try:
        engine = create_engine(isolated_url, pool_pre_ping=True)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        captured_at = datetime.now(UTC).replace(second=0, microsecond=0)
        latest_open = captured_at - timedelta(minutes=3)
        features: list[CandleFeatures] = []
        for symbol in BASELINE_SYMBOLS:
            for index in range(12):
                opened = latest_open - timedelta(minutes=3 * (11 - index))
                value = Decimal("100")
                candle = CandleBar(
                    symbol=symbol,
                    interval="3m",
                    open_at=opened,
                    close_at=opened + timedelta(minutes=3) - timedelta(milliseconds=1),
                    source_received_at=captured_at,
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=Decimal("1"),
                )
                features.append(
                    CandleFeatures(
                        candle=candle,
                        ema20=value,
                        rsi7=Decimal("50"),
                        macd=Decimal("0"),
                        macd_signal=Decimal("0"),
                        macd_histogram=Decimal("0"),
                    )
                )
        quote_set = MarketQuoteSet(
            captured_at=captured_at,
            quotes=tuple(
                MarketQuote(
                    symbol=symbol,
                    bid=Decimal("99"),
                    ask=Decimal("101"),
                    mark=Decimal("100"),
                    funding_rate=Decimal("0"),
                    open_interest=Decimal("10"),
                    source_at=captured_at,
                    received_at=captured_at,
                    context_received_at=captured_at,
                    oracle_px=Decimal("100"),
                )
                for symbol in BASELINE_SYMBOLS
            ),
            instruments=tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
            candle_features=tuple(features),
            source="hyperliquid",
        )
        with factory() as db:
            snapshot_receipt = persist_quote_set(db, quote_set)
        assert snapshot_receipt.trusted

        repo_config = _load_config(root / "configs/live-smoke.example.json")
        competition_id = _create_competition(factory, repo_config, snapshot_receipt)
        with factory() as db:
            competition = db.get(Competition, competition_id)
            assert competition is not None
            agents = db.scalars(
                select(AgentRun)
                .where(AgentRun.competition_id == competition_id)
                .order_by(AgentRun.manifest_order)
            ).all()
            assert len(agents) == 2
            accounts = db.scalars(
                select(Account).where(Account.agent_run_id.in_([agent.id for agent in agents]))
            ).all()
            assert len(accounts) == 2
            assert competition.rules_bytes
            assert INDICATOR_POLICY in competition.rules_bytes.decode("utf-8")
            assert str(INDICATOR_WARMUP_BARS) in competition.rules_bytes.decode("utf-8")

        _preflight_smoke_inputs(factory, competition_id, snapshot_receipt, repo_config, rounds=1)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
