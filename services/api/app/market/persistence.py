from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app.core.canonical import canonical_json_bytes, sha256_hex
from app.db.models import Candle, MarketSnapshot, QuoteSet
from app.db.models import MarketQuote as MarketQuoteRow
from app.market.indicators import (
    INDICATOR_POLICY,
    INDICATOR_WARMUP_BARS,
    calculate_trailing_feature,
)
from app.market.types import CandleBar, CandleFeatures, MarketQuoteSet

BAR_DURATION = timedelta(minutes=3)
MAX_CANDLE_BATCH = INDICATOR_WARMUP_BARS + 40


class CandlePersistenceError(RuntimeError):
    """A candle append failed a stable continuity or immutability check."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SnapshotReceipt:
    snapshot_id: str
    quote_set_id: str
    sha256: str
    trusted: bool
    duplicate: bool


def snapshot_payload(quote_set: MarketQuoteSet) -> dict[str, object]:
    health = quote_set.health()
    return {
        "schema_version": 1,
        "source": quote_set.source,
        "captured_at": quote_set.captured_at.isoformat(),
        "required_symbols": list(quote_set.required_symbols),
        "health": {
            "complete": health.complete,
            "max_age_ms": health.max_age_ms,
            "skew_ms": health.skew_ms,
            "trusted": health.trusted,
        },
        "instruments": [
            {
                "symbol": item.symbol,
                "size_decimals": item.size_decimals,
                "max_leverage": item.max_leverage,
            }
            for item in quote_set.instruments
        ],
        "quotes": {
            item.symbol: {
                "bid": str(item.bid),
                "ask": str(item.ask),
                "mark": str(item.mark),
                "oracle_px": str(item.oracle_px) if item.oracle_px is not None else None,
                "oracle_px_basis": (
                    "hyperliquid_asset_context_oracle_px" if item.oracle_px is not None else None
                ),
                "funding_rate": str(item.funding_rate) if item.funding_rate is not None else None,
                "funding_rate_basis": (
                    "hyperliquid_asset_context_predicted_hourly_rate"
                    if item.funding_rate is not None
                    else None
                ),
                "open_interest": str(item.open_interest)
                if item.open_interest is not None
                else None,
                "source_at": item.source_at.isoformat(),
                "event_at": item.source_at.isoformat(),
                "received_at": item.received_at.isoformat(),
                "context_received_at": item.context_received_at.isoformat(),
                "source_at_basis": item.source_at_basis,
            }
            for item in quote_set.quotes
        },
        "candles": _snapshot_candles(quote_set.candle_features),
        "indicator_policy": INDICATOR_POLICY,
        "indicator_warmup_bars": INDICATOR_WARMUP_BARS,
        "candle_error": quote_set.candle_error,
    }


def _snapshot_candles(features: tuple[CandleFeatures, ...]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str | None]]] = {}
    for item in features:
        bar = item.candle
        grouped.setdefault(bar.symbol, []).append(
            {
                "interval": bar.interval,
                "open_at": bar.open_at.isoformat(),
                "close_at": bar.close_at.isoformat(),
                "source_received_at": bar.source_received_at.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": str(bar.volume),
                "ema20": str(item.ema20) if item.ema20 is not None else None,
                "rsi7": str(item.rsi7) if item.rsi7 is not None else None,
                "macd": str(item.macd) if item.macd is not None else None,
                "macd_signal": (str(item.macd_signal) if item.macd_signal is not None else None),
                "macd_histogram": (
                    str(item.macd_histogram) if item.macd_histogram is not None else None
                ),
            }
        )
    return [
        {"symbol": symbol, "interval": "3m", "bars": bars}
        for symbol, bars in sorted(grouped.items())
    ]


def persist_quote_set(db: Session, quote_set: MarketQuoteSet) -> SnapshotReceipt:
    """Persist immutable market evidence and its queryable quote rows in one transaction."""
    body = canonical_json_bytes(snapshot_payload(quote_set))
    body_hash = sha256_hex(body)
    health = quote_set.health()
    quote_set_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())
    with _transaction(db):
        existing = db.scalar(select(MarketSnapshot).where(MarketSnapshot.sha256 == body_hash))
        if existing is not None:
            return SnapshotReceipt(
                snapshot_id=existing.id,
                quote_set_id=existing.quote_set_id,
                sha256=body_hash,
                trusted=health.trusted,
                duplicate=True,
            )
        db.add(
            QuoteSet(
                id=quote_set_id,
                source=quote_set.source,
                captured_at=quote_set.captured_at,
                complete=health.complete,
                max_age_ms=health.max_age_ms,
                skew_ms=health.skew_ms,
            )
        )
        db.flush()
        db.add_all(
            [
                MarketQuoteRow(
                    quote_set_id=quote_set_id,
                    symbol=item.symbol,
                    bid=item.bid,
                    ask=item.ask,
                    mark=item.mark,
                    funding_rate=item.funding_rate,
                    open_interest=item.open_interest,
                    oracle_px=item.oracle_px,
                    source_at=item.source_at,
                    received_at=item.received_at,
                    context_received_at=item.context_received_at,
                    source_at_basis=item.source_at_basis,
                )
                for item in quote_set.quotes
            ]
        )
        db.flush()
        db.add(
            MarketSnapshot(
                id=snapshot_id,
                canonical_bytes=body,
                sha256=body_hash,
                source_label=quote_set.source,
                captured_at=quote_set.captured_at,
                quote_set_id=quote_set_id,
            )
        )
        db.flush()
    return SnapshotReceipt(
        snapshot_id=snapshot_id,
        quote_set_id=quote_set_id,
        sha256=body_hash,
        trusted=health.trusted,
        duplicate=False,
    )


def persist_candles(
    db: Session,
    bars: tuple[CandleBar, ...],
    *,
    source: str = "hyperliquid",
) -> int:
    """Append complete, contiguous candle facts and immutable bounded-window features."""
    if not source or len(source) > 60:
        raise ValueError("candle source label is invalid")
    if not bars:
        return 0
    if len(bars) > MAX_CANDLE_BATCH:
        raise ValueError("candle batch exceeds the bounded insert limit")
    grouped: dict[tuple[str, str], list[CandleBar]] = {}
    for bar in bars:
        grouped.setdefault((bar.symbol, bar.interval), []).append(bar)
    for group in grouped.values():
        group.sort(key=lambda item: item.open_at)
        _validate_candle_batch(group)

    inserted = 0
    with _transaction(db):
        for (symbol, interval), group in sorted(grouped.items()):
            earliest = group[0].open_at
            latest = group[-1].open_at
            previous_rows = tuple(
                db.scalars(
                    select(Candle)
                    .where(
                        Candle.source == source,
                        Candle.symbol == symbol,
                        Candle.interval == interval,
                        Candle.open_at < earliest,
                    )
                    .order_by(Candle.open_at.desc())
                    .limit(INDICATOR_WARMUP_BARS - 1)
                ).all()
            )
            history = [_bar_from_row(row) for row in reversed(previous_rows)]
            max_open = db.scalar(
                select(func.max(Candle.open_at)).where(
                    Candle.source == source,
                    Candle.symbol == symbol,
                    Candle.interval == interval,
                )
            )
            if max_open is not None:
                normalized_max_open = _normalize_timestamp(max_open)
                first_new = next(
                    (
                        bar
                        for bar in group
                        if _normalize_timestamp(bar.open_at) > normalized_max_open
                    ),
                    None,
                )
                if first_new is not None and _normalize_timestamp(first_new.open_at) != (
                    normalized_max_open + BAR_DURATION
                ):
                    raise CandlePersistenceError("market_candle_gap")

            existing_rows = db.scalars(
                select(Candle).where(
                    Candle.source == source,
                    Candle.symbol == symbol,
                    Candle.interval == interval,
                    Candle.open_at >= earliest,
                    Candle.open_at <= latest,
                )
            ).all()
            existing = {_normalize_timestamp(row.open_at): row for row in existing_rows}
            expected: list[tuple[CandleBar, CandleFeatures]] = []
            for bar in group:
                features = calculate_trailing_feature(history, bar)
                expected.append((bar, features))
                history.append(bar)

            for bar, features in expected:
                row = existing.get(_normalize_timestamp(bar.open_at))
                if (
                    row is None
                    and max_open is not None
                    and _normalize_timestamp(bar.open_at) <= _normalize_timestamp(max_open)
                ):
                    raise CandlePersistenceError("market_candle_gap")
                if row is None:
                    continue
                if not _same_candle_facts(row, bar) or not _same_features(row, features):
                    raise CandlePersistenceError("market_candle_contradiction")

            values = [
                _candle_values(bar, features, source)
                for bar, features in expected
                if _normalize_timestamp(bar.open_at) not in existing
            ]
            if values:
                statement = _candle_insert(db, values).returning(Candle.id)
                inserted += len(db.scalars(statement).all())
                db.flush()

            persisted_rows = db.scalars(
                select(Candle).where(
                    Candle.source == source,
                    Candle.symbol == symbol,
                    Candle.interval == interval,
                    Candle.open_at >= earliest,
                    Candle.open_at <= latest,
                )
            ).all()
            persisted = {_normalize_timestamp(row.open_at): row for row in persisted_rows}
            for bar, features in expected:
                row = persisted.get(_normalize_timestamp(bar.open_at))
                if row is None:
                    raise CandlePersistenceError("market_candle_gap")
                if not _same_candle_facts(row, bar) or not _same_features(row, features):
                    raise CandlePersistenceError("market_candle_contradiction")
    return inserted


def latest_candle_open_at(
    db: Session, symbol: str, *, source: str = "hyperliquid", interval: str = "3m"
) -> datetime | None:
    value = db.scalar(
        select(func.max(Candle.open_at)).where(
            Candle.source == source, Candle.symbol == symbol, Candle.interval == interval
        )
    )
    return _normalize_timestamp(value) if value is not None else None


def load_candle_features(
    db: Session,
    symbols: tuple[str, ...],
    *,
    as_of: datetime,
    source: str = "hyperliquid",
    interval: str = "3m",
    per_symbol_limit: int = 12,
) -> tuple[CandleFeatures, ...]:
    """Load a bounded, completed candle window available by one canonical time."""
    if not symbols or not 1 <= per_symbol_limit <= 40:
        raise ValueError("candle snapshot window is invalid")
    cutoff = _normalize_timestamp(as_of)
    grouped: dict[str, list[Candle]] = {}
    for symbol in symbols:
        grouped[symbol] = list(
            db.scalars(
                select(Candle)
                .where(
                    Candle.source == source,
                    Candle.symbol == symbol,
                    Candle.interval == interval,
                    Candle.close_at < cutoff,
                    Candle.source_received_at <= cutoff,
                )
                .order_by(Candle.open_at.desc())
                .limit(per_symbol_limit)
            ).all()
        )
    output: list[CandleFeatures] = []
    for symbol in symbols:
        for row in reversed(grouped[symbol]):
            output.append(
                CandleFeatures(
                    candle=CandleBar(
                        symbol=row.symbol,
                        interval=row.interval,
                        open_at=_normalize_timestamp(row.open_at),
                        close_at=_normalize_timestamp(row.close_at),
                        source_received_at=_normalize_timestamp(row.source_received_at),
                        open=row.open,
                        high=row.high,
                        low=row.low,
                        close=row.close,
                        volume=row.volume,
                    ),
                    ema20=row.ema20,
                    rsi7=row.rsi7,
                    macd=row.macd,
                    macd_signal=row.macd_signal,
                    macd_histogram=row.macd_histogram,
                )
            )
    return tuple(output)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_candle_batch(bars: list[CandleBar]) -> None:
    if not bars:
        raise ValueError("candle batch is empty")
    if any(bar.interval != "3m" for bar in bars):
        raise ValueError("only completed 3m candles can be persisted")
    for index, bar in enumerate(bars):
        opened = _normalize_timestamp(bar.open_at)
        received = _normalize_timestamp(bar.source_received_at)
        latest_closed = _latest_closed_open(received)
        if (
            opened.second != 0
            or opened.microsecond != 0
            or opened.minute % 3 != 0
            or _normalize_timestamp(bar.close_at) >= opened + BAR_DURATION
            or _normalize_timestamp(bar.close_at) >= received
            or opened > latest_closed
        ):
            raise CandlePersistenceError("market_candle_incomplete")
        if index and opened != _normalize_timestamp(bars[index - 1].open_at) + BAR_DURATION:
            raise CandlePersistenceError("market_candle_gap")


def _latest_closed_open(received_at: datetime) -> datetime:
    received = _normalize_timestamp(received_at)
    latest_boundary = received.replace(second=0, microsecond=0)
    latest_boundary -= timedelta(minutes=latest_boundary.minute % 3)
    return latest_boundary - BAR_DURATION


def _bar_from_row(row: Candle) -> CandleBar:
    return CandleBar(
        symbol=row.symbol,
        interval=row.interval,
        open_at=_normalize_timestamp(row.open_at),
        close_at=_normalize_timestamp(row.close_at),
        source_received_at=_normalize_timestamp(row.source_received_at),
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
    )


def _same_candle_facts(row: Candle, bar: CandleBar) -> bool:
    return (
        _normalize_timestamp(row.close_at) == _normalize_timestamp(bar.close_at)
        and row.open == bar.open
        and row.high == bar.high
        and row.low == bar.low
        and row.close == bar.close
        and row.volume == bar.volume
    )


def _same_features(row: Candle, features: CandleFeatures) -> bool:
    return all(
        stored == expected
        for stored, expected in (
            (row.ema20, features.ema20),
            (row.rsi7, features.rsi7),
            (row.macd, features.macd),
            (row.macd_signal, features.macd_signal),
            (row.macd_histogram, features.macd_histogram),
        )
    )


def _candle_values(bar: CandleBar, features: CandleFeatures, source: str) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "source": source,
        "symbol": bar.symbol,
        "interval": bar.interval,
        "open_at": bar.open_at,
        "close_at": bar.close_at,
        "source_received_at": bar.source_received_at,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "ema20": features.ema20,
        "rsi7": features.rsi7,
        "macd": features.macd,
        "macd_signal": features.macd_signal,
        "macd_histogram": features.macd_histogram,
    }


def _candle_insert(db: Session, values: list[dict[str, object]]) -> Insert:
    dialect = db.get_bind().dialect.name
    insert = (
        pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    )
    if insert is None:
        raise RuntimeError("candle insert requires PostgreSQL or SQLite")
    return (
        insert(Candle)
        .values(values)
        .on_conflict_do_nothing(
            index_elements=[Candle.source, Candle.symbol, Candle.interval, Candle.open_at]
        )
    )


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return
    with db.begin():
        yield
