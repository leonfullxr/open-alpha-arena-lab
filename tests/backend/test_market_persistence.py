from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import Base, Candle, MarketQuote, MarketSnapshot, QuoteSet
from app.market.persistence import (
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
from sqlalchemy import create_engine, func, select
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
            source_at=captured,
            received_at=captured,
            context_received_at=captured,
        )
        for symbol in BASELINE_SYMBOLS
    )
    specs = tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS)
    return MarketQuoteSet(captured, quotes, specs)


def _bar(index: int, close: str, received: datetime = NOW) -> CandleBar:
    opens = NOW + timedelta(minutes=3 * index)
    value = Decimal(close)
    return CandleBar(
        symbol="BTC",
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
        quote_set = db.get(QuoteSet, first.quote_set_id)
        snapshot = db.get(MarketSnapshot, first.snapshot_id)
        assert quote_set is not None and quote_set.complete
        assert snapshot is not None
        assert b"context_received_at" in snapshot.canonical_bytes
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


def test_candle_features_persist_and_backfill_corrections_recompute_history() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    original = tuple(_bar(i, str(100 + i)) for i in range(40))
    with Session(engine) as db:
        assert persist_candles(db, original) == 40
        assert persist_candles(db, original) == 0
        rows = list(db.scalars(select(Candle).order_by(Candle.open_at)))
        assert len(rows) == 40
        assert rows[18].ema20 is None
        assert rows[19].ema20 == Decimal("109.5")
        assert rows[33].macd_signal is not None

        revised = (_bar(0, "101"), *original[1:])
        assert persist_candles(db, revised) > 1
        corrected = db.scalar(select(Candle).where(Candle.open_at == original[0].open_at))
        assert corrected is not None and corrected.close == Decimal("101")
    engine.dispose()


def test_canonical_snapshot_freezes_bounded_completed_candle_features() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    bars = tuple(_bar(i, str(100 + i)) for i in range(40))
    as_of = NOW + timedelta(hours=3)
    with Session(engine) as db:
        persist_candles(db, bars)
        features = load_candle_features(db, ("BTC", "ETH"), as_of=as_of, per_symbol_limit=12)
        assert len(features) == 12
        assert all(item.candle.symbol == "BTC" for item in features)
        assert features[0].candle.open_at == bars[-12].open_at
        assert features[-1].ema20 is not None
        receipt = persist_quote_set(
            db,
            MarketQuoteSet(as_of, _quote_set(as_of).quotes, _quote_set(as_of).instruments,
                           candle_features=features),
        )
        snapshot = db.get(MarketSnapshot, receipt.snapshot_id)
        assert snapshot is not None
        assert b'"candles"' in snapshot.canonical_bytes
        assert b'"ema20"' in snapshot.canonical_bytes
        assert bars[-1].open_at.isoformat().encode() in snapshot.canonical_bytes
    engine.dispose()
