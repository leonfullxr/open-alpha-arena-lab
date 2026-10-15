from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.db.models import Base, Candle, MarketQuote, MarketSnapshot, QuoteSet
from app.market.indicators import INDICATOR_POLICY, INDICATOR_WARMUP_BARS
from app.market.persistence import (
    CandlePersistenceError,
    load_candle_features,
    persist_candles,
    persist_quote_set,
)
from app.market.types import (
    BASELINE_SYMBOLS,
    CandleBar,
    InstrumentSpec,
    MarketQuoteSet,
)
from app.market.types import (
    MarketQuote as Quote,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)


def _quote_set(captured: datetime = NOW) -> MarketQuoteSet:
    quotes = tuple(
        Quote(
            symbol=symbol,
            bid=Decimal("99"),
            ask=Decimal("101"),
            mark=Decimal("100"),
            funding_rate=Decimal("0.0001"),
            open_interest=Decimal("12"),
            oracle_px=Decimal("98.5"),
            source_at=captured,
            received_at=captured,
            context_received_at=captured,
        )
        for symbol in BASELINE_SYMBOLS
    )
    specs = tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS)
    return MarketQuoteSet(captured, quotes, specs)


def _bar(
    index: int,
    close: str,
    received: datetime = NOW,
    *,
    symbol: str = "BTC",
    count: int = 40,
) -> CandleBar:
    opens = NOW - timedelta(minutes=3 * (count - index))
    value = Decimal(close)
    return CandleBar(
        symbol=symbol,
        interval="3m",
        open_at=opens,
        close_at=opens + timedelta(minutes=3) - timedelta(milliseconds=1),
        source_received_at=received,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("3"),
    )


def _engine() -> Engine:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER candles_no_update BEFORE UPDATE ON candles "
                "BEGIN SELECT RAISE(ABORT, 'evidence rows are append-only'); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER candles_no_delete BEFORE DELETE ON candles "
                "BEGIN SELECT RAISE(ABORT, 'evidence rows are append-only'); END"
            )
        )
    return engine


def test_quote_set_and_snapshot_are_atomic_canonical_and_deduplicated() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = persist_quote_set(db, _quote_set())
        again = persist_quote_set(db, _quote_set())
        assert first.trusted
        assert not first.duplicate
        assert again.duplicate
        assert first.snapshot_id == again.snapshot_id
        assert len(db.scalars(select(MarketQuote)).all()) == 6
        quote = db.scalar(select(MarketQuote))
        assert quote is not None
        assert quote.oracle_px == Decimal("98.5")
        context_received_at = quote.context_received_at
        assert context_received_at is not None
        assert context_received_at.replace(tzinfo=UTC) == NOW
        quote_set = db.get(QuoteSet, first.quote_set_id)
        snapshot = db.get(MarketSnapshot, first.snapshot_id)
        assert quote_set is not None and quote_set.complete
        assert snapshot is not None
        assert b"context_received_at" in snapshot.canonical_bytes
        assert b"oracle_px" in snapshot.canonical_bytes
        assert snapshot.sha256 == first.sha256
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 1
    engine.dispose()


def test_incomplete_quote_set_is_stored_as_untrusted_evidence() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    incomplete = MarketQuoteSet(NOW, _quote_set().quotes[:-1], _quote_set().instruments)
    with Session(engine) as db:
        receipt = persist_quote_set(db, incomplete)
        assert not receipt.trusted
        quote_set = db.get(QuoteSet, receipt.quote_set_id)
        assert quote_set is not None and not quote_set.complete
        assert db.scalar(select(func.count()).select_from(MarketQuote)) == 5
    engine.dispose()


def test_candle_history_is_immutable_and_retries_ignore_receive_time() -> None:
    engine = _engine()
    original = tuple(_bar(i, str(100 + i)) for i in range(40))
    with Session(engine) as db:
        assert persist_candles(db, original) == 40
        assert persist_candles(db, original) == 0
        rows = list(db.scalars(select(Candle).order_by(Candle.open_at)))
        assert len(rows) == 40
        assert all(row.ema20 is None and row.macd_signal is None for row in rows)

        revised = (_bar(0, "101"), *original[1:])
        with pytest.raises(CandlePersistenceError, match="market_candle_contradiction"):
            persist_candles(db, revised)
        retry = tuple(_bar(i, str(100 + i), received=NOW + timedelta(seconds=1)) for i in range(40))
        assert persist_candles(db, retry) == 0
        unchanged = db.scalar(select(Candle).where(Candle.open_at == original[0].open_at))
        assert unchanged is not None and unchanged.close == Decimal("100")
        assert unchanged.source_received_at.replace(tzinfo=UTC) == NOW
        assert db.scalar(select(func.count()).select_from(Candle)) == 40
    engine.dispose()


def test_canonical_snapshot_freezes_bounded_completed_candle_features() -> None:
    engine = _engine()
    bars = tuple(_bar(i, str(100 + i), symbol="BTC", count=511) for i in range(511))
    eth_bars = tuple(_bar(i, str(200 + i), symbol="ETH", count=511) for i in range(511))
    as_of = NOW + timedelta(hours=3)
    with Session(engine) as db:
        persist_candles(db, bars)
        persist_candles(db, eth_bars)
        features = load_candle_features(db, ("BTC", "ETH"), as_of=as_of, per_symbol_limit=12)
        assert len(features) == 24
        btc = tuple(item for item in features if item.candle.symbol == "BTC")
        assert btc[0].candle.open_at == bars[-12].open_at
        assert all(item.ema20 is not None and item.macd_signal is not None for item in btc)
        receipt = persist_quote_set(
            db,
            MarketQuoteSet(
                as_of,
                _quote_set(as_of).quotes,
                _quote_set(as_of).instruments,
                candle_features=features,
            ),
        )
        snapshot = db.get(MarketSnapshot, receipt.snapshot_id)
        assert snapshot is not None
        assert b'"candles"' in snapshot.canonical_bytes
        assert b'"ema20"' in snapshot.canonical_bytes
        assert f'"indicator_policy":"{INDICATOR_POLICY}"'.encode() in snapshot.canonical_bytes
        expected_warmup = f'"indicator_warmup_bars":{INDICATOR_WARMUP_BARS}'.encode()
        assert expected_warmup in snapshot.canonical_bytes
        assert bars[-1].open_at.isoformat().encode() in snapshot.canonical_bytes
    engine.dispose()


def test_trailing_500_features_match_batch_and_incremental_writes() -> None:
    bars = tuple(_bar(i, str(100 + i), count=511) for i in range(511))
    batch_engine = _engine()
    incremental_engine = _engine()
    with Session(batch_engine) as batch_db, Session(incremental_engine) as incremental_db:
        assert persist_candles(batch_db, bars) == len(bars)
        assert persist_candles(incremental_db, bars[:510]) == 510
        assert persist_candles(incremental_db, bars[510:]) == 1
        batch_rows = batch_db.scalars(select(Candle).order_by(Candle.open_at)).all()
        incremental_rows = incremental_db.scalars(select(Candle).order_by(Candle.open_at)).all()
        assert len(batch_rows) == len(incremental_rows) == 511
        assert all(
            row.ema20 is None and row.rsi7 is None and row.macd_signal is None
            for row in batch_rows[: INDICATOR_WARMUP_BARS - 1]
        )
        batch_features = [
            (row.ema20, row.rsi7, row.macd, row.macd_signal, row.macd_histogram)
            for row in batch_rows
        ]
        incremental_features = [
            (row.ema20, row.rsi7, row.macd, row.macd_signal, row.macd_histogram)
            for row in incremental_rows
        ]
        assert batch_features == incremental_features
        assert all(value is not None for value in batch_features[-1])
    batch_engine.dispose()
    incremental_engine.dispose()


def test_candle_gap_and_incomplete_bar_fail_without_inserting() -> None:
    engine = _engine()
    bars = tuple(_bar(i, str(100 + i)) for i in range(4))
    with Session(engine) as db:
        assert persist_candles(db, bars) == 4
        gap = _bar(5, "105")
        with pytest.raises(CandlePersistenceError, match="market_candle_gap"):
            persist_candles(db, (gap,))
        incomplete = _bar(4, "104", received=NOW - timedelta(hours=2))
        with pytest.raises(CandlePersistenceError, match="market_candle_incomplete"):
            persist_candles(db, (incomplete,))
        assert db.scalar(select(func.count()).select_from(Candle)) == 4
    engine.dispose()
