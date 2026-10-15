from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.rules import canonical_profile
from app.db.models import Base, Candle, MarketSnapshot
from app.llm.inputs import InputEvidenceError, build_user_input
from app.market.persistence import MAX_CANDLE_BATCH
from app.market.types import CandleBar, InstrumentSpec, MarketQuote, MarketQuoteSet
from app.worker import _collect_candles, capture_market_snapshot
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


def _bar(open_at: datetime, received_at: datetime) -> CandleBar:
    price = Decimal("100")
    return CandleBar(
        symbol="BTC",
        interval="3m",
        open_at=open_at,
        close_at=open_at + timedelta(minutes=3) - timedelta(milliseconds=1),
        source_received_at=received_at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1"),
    )


def test_long_candle_gap_catches_up_in_bounded_chunks_and_blocks_stale_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import worker

    monkeypatch.setattr(worker, "BASELINE_SYMBOLS", ("BTC",))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(second=0, microsecond=0)

    class Collector:
        calls: list[tuple[datetime, datetime]]

        def __init__(self) -> None:
            self.calls = []

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
            bars: list[CandleBar] = []
            opened = start_at
            while opened < end_at:
                bars.append(_bar(opened, end_at))
                opened += timedelta(minutes=3)
            return tuple(bars)

        def capture(self) -> MarketQuoteSet:
            captured = datetime.now(UTC)
            quote = MarketQuote(
                symbol="BTC",
                bid=Decimal("99"),
                ask=Decimal("101"),
                mark=Decimal("100"),
                funding_rate=Decimal("0"),
                open_interest=Decimal("1"),
                source_at=captured,
                received_at=captured,
                context_received_at=captured,
            )
            return MarketQuoteSet(
                captured_at=captured,
                quotes=(quote,),
                instruments=(InstrumentSpec("BTC", 4, 20),),
                required_symbols=("BTC",),
                source="hyperliquid",
            )

    collector = Collector()
    try:
        cold_start = now - timedelta(days=7)
        assert _collect_candles(collector, factory, cold_start) == 511

        before = len(collector.calls)
        assert _collect_candles(collector, factory, now) == MAX_CANDLE_BATCH
        assert len(collector.calls) == before + 1
        start_at, end_at = collector.calls[-1]
        assert end_at == start_at + timedelta(minutes=3 * MAX_CANDLE_BATCH)

        receipt, _changes = capture_market_snapshot(collector, factory)
        with factory() as db:
            snapshot = db.get(MarketSnapshot, receipt.snapshot_id)
            assert snapshot is not None
            payload = json.loads(snapshot.canonical_bytes)
            assert receipt.trusted
            assert payload["candle_error"] == "market_candle_gap"
            assert payload["candles"] == []
            with pytest.raises(InputEvidenceError, match="live market candle evidence"):
                build_user_input(
                    logical_at=now,
                    frozen_rules=canonical_profile("alpha_2025_baseline"),
                    frozen_rules_sha256="rules-hash",
                    snapshot=payload,
                    snapshot_sha256=snapshot.sha256,
                    own_account={},
                )
            candle_count = db.scalar(select(func.count()).select_from(Candle))
            assert candle_count is not None and candle_count > 511
    finally:
        engine.dispose()
