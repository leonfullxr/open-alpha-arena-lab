from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app.db.models import (
    AgentRun,
    Candle,
    Competition,
    DecisionRound,
    InvocationAttempt,
    MarketSnapshot,
    Position,
    RoundAgentJob,
    SpendReservation,
)
from app.market.hyperliquid import HyperliquidClient
from app.market.persistence import CandlePersistenceError, persist_candles
from app.market.types import (
    BASELINE_SYMBOLS,
    CandleBar,
    InstrumentSpec,
    MarketQuote,
    MarketQuoteSet,
)
from app.services.demo import seed_demo
from app.worker import (
    _claim_one,
    _collect_candles,
    _create_due_rounds,
    _dispatch_claim,
    capture_market_snapshot,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
_POSTGRES_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(_POSTGRES_URL is None, reason="TEST_DATABASE_URL is not configured")


def _bar(open_at: datetime, received_at: datetime, value: Decimal) -> CandleBar:
    return CandleBar(
        symbol="BTC",
        interval="3m",
        open_at=open_at,
        close_at=open_at + timedelta(minutes=3) - timedelta(milliseconds=1),
        source_received_at=received_at,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("3"),
    )


def test_postgres_collector_is_append_only_idempotent_and_restart_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _POSTGRES_URL is not None
    from app import worker

    monkeypatch.setattr(worker, "BASELINE_SYMBOLS", ("BTC",))
    schema = f"arena_candles_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_POSTGRES_URL, pool_pre_ping=True)
    engines: list[Engine] = []
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = make_url(_POSTGRES_URL).set(
        drivername="postgresql+psycopg",
        query={"options": f"-csearch_path={schema},pg_catalog"},
    )
    migration_env = os.environ.copy()
    migration_env["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
    migration_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, ("services/api", migration_env.get("PYTHONPATH")))
    )
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
        cwd=Path(__file__).resolve().parents[2],
        env=migration_env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert migration.returncode == 0, "isolated Alembic upgrade failed"

    engine = create_engine(isolated_url, pool_pre_ping=True)
    engines.append(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    captured_at = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    class FakeCollector:
        def __init__(self) -> None:
            self.calls: list[tuple[datetime, datetime]] = []

        def capture(self) -> MarketQuoteSet:
            raise AssertionError("collector candle backfill must not capture quotes")

        def fetch_candles(
            self,
            _symbol: str,
            *,
            start_at: datetime,
            end_at: datetime,
            interval: str = "3m",
        ) -> tuple[CandleBar, ...]:
            assert interval == "3m"
            self.calls.append((start_at, end_at))
            latest_boundary = end_at.replace(second=0, microsecond=0)
            latest_boundary -= timedelta(minutes=latest_boundary.minute % 3)
            latest_closed = latest_boundary - timedelta(minutes=3)
            bars: list[CandleBar] = []
            opened = start_at
            while opened <= latest_closed:
                bars.append(
                    _bar(
                        opened,
                        end_at,
                        Decimal("100") + Decimal(len(self.calls) + len(bars)),
                    )
                )
                opened += timedelta(minutes=3)
            return tuple(bars)

    client = FakeCollector()
    try:
        assert _collect_candles(client, factory, captured_at) == 511
        assert len(client.calls) == 1
        first_start, first_end = client.calls[0]
        with factory() as db:
            first_rows = db.scalars(select(Candle).order_by(Candle.open_at)).all()
            assert len(first_rows) == 511
            assert first_rows[-1].open_at == first_end.replace(second=0, microsecond=0) - timedelta(
                minutes=3
            )

        retry = _bar(
            first_rows[0].open_at,
            first_rows[0].source_received_at + timedelta(seconds=1),
            first_rows[0].close,
        )
        with factory() as db:
            assert persist_candles(db, (retry,)) == 0
            revised = _bar(
                retry.open_at,
                retry.source_received_at,
                retry.close + Decimal("1"),
            )
            with pytest.raises(CandlePersistenceError, match="market_candle_contradiction"):
                persist_candles(db, (revised,))

        same_cycle = captured_at + timedelta(seconds=1)
        assert _collect_candles(client, factory, same_cycle) == 0
        assert len(client.calls) == 1
        next_cycle = captured_at + timedelta(minutes=3)
        assert _collect_candles(client, factory, next_cycle) == 1
        assert len(client.calls) == 2

        engine.dispose()
        engine = create_engine(isolated_url, pool_pre_ping=True)
        engines.append(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        third_cycle = captured_at + timedelta(minutes=6)
        assert _collect_candles(client, factory, third_cycle) == 1
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Candle)) == 513
            latest = db.scalar(select(func.max(Candle.open_at)).where(Candle.symbol == "BTC"))
            assert latest is not None

        next_open = latest + timedelta(minutes=3)
        concurrent_bar = _bar(next_open, third_cycle + timedelta(minutes=3), Decimal("999"))

        def append_duplicate() -> int:
            with factory() as db:
                return persist_candles(db, (concurrent_bar,))

        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(lambda _index: append_duplicate(), range(2)))
        assert sum(counts) == 1
        with factory() as db:
            row_count = db.scalar(select(func.count()).select_from(Candle))
            assert row_count == 514
            with pytest.raises(DBAPIError, match="append-only"):
                db.execute(
                    text(
                        "UPDATE candles SET volume = 4 WHERE symbol = 'BTC' AND open_at = :opened"
                    ),
                    {"opened": first_start},
                )
                db.flush()
            db.rollback()

        competition_id: str
        target_position_id: str
        target_symbol: str
        target_mark: Decimal
        with factory() as db:
            competition_id = seed_demo(db, rounds=1)
            competition = db.get(Competition, competition_id)
            assert competition is not None
            competition.state = "RUNNING"
            competition.ended_at = None
            for agent in db.scalars(
                select(AgentRun).where(AgentRun.competition_id == competition_id)
            ).all():
                agent.status = "ACTIVE"
            open_position = db.scalar(
                select(Position).where(Position.state == "OPEN").order_by(Position.id).limit(1)
            )
            assert open_position is not None
            target_position_id = open_position.id
            target_symbol = open_position.symbol
            if open_position.side == "LONG":
                open_position.stop_loss = open_position.average_entry * Decimal("0.95")
                target_mark = open_position.average_entry * Decimal("0.90")
            else:
                open_position.stop_loss = open_position.average_entry * Decimal("1.05")
                target_mark = open_position.average_entry * Decimal("1.10")
            db.commit()

        monkeypatch.setattr(worker, "BASELINE_SYMBOLS", ("ETH",))
        quote_time = datetime.now(UTC) - timedelta(seconds=5)
        candle_time_ms = int(datetime.now(UTC).timestamp() * 1000)
        malformed_candle = [
            {
                "s": "ETH",
                "i": "3m",
                "t": candle_time_ms,
                "T": candle_time_ms + 179_999,
                "o": "100",
                "h": "99",
                "l": "98",
                "c": "100",
                "v": "1",
            }
        ]
        provider_requests: list[dict[str, object]] = []

        def malformed_candle_response(request: httpx.Request) -> httpx.Response:
            provider_requests.append(json.loads(request.content))
            return httpx.Response(200, json=malformed_candle)

        class CandleFailureClient:
            def __init__(self, provider: HyperliquidClient) -> None:
                self.provider = provider

            def fetch_candles(
                self,
                symbol: str,
                *,
                start_at: datetime,
                end_at: datetime,
                interval: str = "3m",
            ) -> tuple[CandleBar, ...]:
                return self.provider.fetch_candles(
                    symbol, start_at=start_at, end_at=end_at, interval=interval
                )

            def capture(self) -> MarketQuoteSet:
                def quote_for(symbol: str) -> MarketQuote:
                    price = target_mark if symbol == target_symbol else Decimal("100")
                    return MarketQuote(
                        symbol=symbol,
                        bid=price * Decimal("0.999"),
                        ask=price * Decimal("1.001"),
                        mark=price,
                        funding_rate=Decimal("0"),
                        open_interest=Decimal("10"),
                        source_at=quote_time,
                        received_at=quote_time,
                        context_received_at=quote_time,
                    )

                return MarketQuoteSet(
                    captured_at=quote_time,
                    quotes=tuple(quote_for(symbol) for symbol in BASELINE_SYMBOLS),
                    instruments=tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
                    source="hyperliquid",
                )

        with httpx.Client(transport=httpx.MockTransport(malformed_candle_response)) as http_client:
            provider = HyperliquidClient(
                symbols=("ETH",), client=http_client, clock=lambda: quote_time
            )
            candle_failure_receipt, _ = capture_market_snapshot(
                CandleFailureClient(provider), factory
            )
        assert provider_requests and provider_requests[0]["type"] == "candleSnapshot"
        assert candle_failure_receipt.trusted
        with factory() as db:
            failed_snapshot = db.scalar(
                select(MarketSnapshot).where(
                    MarketSnapshot.id == candle_failure_receipt.snapshot_id
                )
            )
            assert failed_snapshot is not None
            failed_payload = json.loads(failed_snapshot.canonical_bytes)
            assert failed_payload["candle_error"] == "market_candle_fetch_unavailable"
            assert failed_payload["candles"] == []

        from app.services.execution import run_protective_exit_cycle

        with factory.begin() as db:
            protection = run_protective_exit_cycle(
                db, quote_set_id=candle_failure_receipt.quote_set_id
            )
            assert protection.protective_exits >= 1
            closed = db.get(Position, target_position_id)
            assert closed is not None and closed.state == "CLOSED"

        with factory.begin() as db:
            current_time = db.scalar(select(func.now()))
            competition = db.get(Competition, competition_id)
            snapshot = db.get(MarketSnapshot, candle_failure_receipt.snapshot_id)
            assert competition is not None and snapshot is not None and current_time is not None
            logical_at = max(
                snapshot.captured_at,
                current_time - timedelta(seconds=1),
            )
            last_index = (
                db.scalar(
                    select(func.max(DecisionRound.round_index)).where(
                        DecisionRound.competition_id == competition_id
                    )
                )
                or 0
            )
            competition.started_at = logical_at - timedelta(seconds=(last_index + 1) * 180)
        assert _create_due_rounds(factory) == 1
        claim = _claim_one(factory)
        assert claim is not None
        with factory() as db:
            round_row = db.get(DecisionRound, claim.round_id)
            assert round_row is not None
            assert round_row.snapshot_id == candle_failure_receipt.snapshot_id
        assert (
            _dispatch_claim(
                factory,
                claim,
                {"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"},
            )
            is None
        )
        with factory() as db:
            job = db.get(RoundAgentJob, claim.job_id)
            assert job is not None
            assert job.state == "TERMINAL"
            assert job.error_code == "MARKET_INPUT_UNAVAILABLE"
            assert (
                db.scalar(
                    select(InvocationAttempt.id).where(InvocationAttempt.job_id == claim.job_id)
                )
                is None
            )
            assert (
                db.scalar(
                    select(SpendReservation.id).where(SpendReservation.job_id == claim.job_id)
                )
                is None
            )
    finally:
        for item in engines:
            item.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
