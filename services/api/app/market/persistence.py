from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.canonical import canonical_json_bytes, sha256_hex
from app.db.models import Candle, MarketSnapshot, QuoteSet
from app.db.models import MarketQuote as MarketQuoteRow
from app.market.indicators import calculate_features
from app.market.types import CandleBar, CandleFeatures, MarketQuoteSet


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
                "funding_rate": str(item.funding_rate) if item.funding_rate is not None else None,
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
                "macd_signal": (
                    str(item.macd_signal) if item.macd_signal is not None else None
                ),
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
                    source_at=item.source_at,
                    received_at=item.received_at,
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
    """Persist backfill plus deterministic features, updating corrected history rows."""
    if not source or len(source) > 60:
        raise ValueError("candle source label is invalid")
    features = calculate_features(bars)
    changed = 0
    with _transaction(db):
        symbol_set = {item.candle.symbol for item in features}
        interval_set = {item.candle.interval for item in features}
        existing_rows = db.scalars(
            select(Candle).where(
                Candle.source == source,
                Candle.symbol.in_(symbol_set),
                Candle.interval.in_(interval_set),
            )
        ).all()
        existing = {
            (row.symbol, row.interval, _normalize_timestamp(row.open_at)): row
            for row in existing_rows
        }
        for item in features:
            bar = item.candle
            row = existing.get((bar.symbol, bar.interval, _normalize_timestamp(bar.open_at)))
            if row is None:
                row = Candle(
                    id=str(uuid.uuid4()),
                    source=source,
                    symbol=bar.symbol,
                    interval=bar.interval,
                    open_at=bar.open_at,
                    close_at=bar.close_at,
                    source_received_at=bar.source_received_at,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    ema20=item.ema20,
                    rsi7=item.rsi7,
                    macd=item.macd,
                    macd_signal=item.macd_signal,
                    macd_histogram=item.macd_histogram,
                )
                db.add(row)
                existing[(bar.symbol, bar.interval, _normalize_timestamp(bar.open_at))] = row
                changed += 1
                continue
            old = (
                _normalize_timestamp(row.close_at),
                _normalize_timestamp(row.source_received_at),
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.ema20,
                row.rsi7,
                row.macd,
                row.macd_signal,
                row.macd_histogram,
            )
            new = (
                _normalize_timestamp(bar.close_at),
                _normalize_timestamp(bar.source_received_at),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                item.ema20,
                item.rsi7,
                item.macd,
                item.macd_signal,
                item.macd_histogram,
            )
            if old != new:
                (
                    row.close_at,
                    row.source_received_at,
                    row.open,
                    row.high,
                    row.low,
                    row.close,
                    row.volume,
                    row.ema20,
                    row.rsi7,
                    row.macd,
                    row.macd_signal,
                    row.macd_histogram,
                ) = new
                changed += 1
        db.flush()
    return changed


def load_candles(
    db: Session, symbol: str, *, source: str = "hyperliquid", interval: str = "3m"
) -> tuple[CandleBar, ...]:
    rows = db.scalars(
        select(Candle)
        .where(Candle.source == source, Candle.symbol == symbol, Candle.interval == interval)
        .order_by(Candle.open_at)
    ).all()
    return tuple(
        CandleBar(
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
        for row in rows
    )


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
    rows = db.scalars(
        select(Candle)
        .where(
            Candle.source == source,
            Candle.symbol.in_(symbols),
            Candle.interval == interval,
            Candle.close_at <= cutoff,
            Candle.source_received_at <= cutoff,
        )
        .order_by(Candle.symbol, Candle.open_at.desc())
    ).all()
    grouped: dict[str, list[Candle]] = {symbol: [] for symbol in symbols}
    for row in rows:
        items = grouped[row.symbol]
        if len(items) < per_symbol_limit:
            items.append(row)
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


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return
    with db.begin():
        yield
