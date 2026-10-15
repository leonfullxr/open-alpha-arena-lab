from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engine.finance import Quote

BASELINE_SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
ZERO = Decimal("0")


def _aware_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _finite(value: Decimal, field: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    if positive and value <= ZERO:
        raise ValueError(f"{field} must be positive")


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    symbol: str
    size_decimals: int
    max_leverage: int

    def __post_init__(self) -> None:
        if not self.symbol or not 0 <= self.size_decimals <= 18:
            raise ValueError("instrument symbol and size precision are invalid")
        if self.max_leverage < 1:
            raise ValueError("instrument max leverage must be positive")

    @property
    def quantity_step(self) -> Decimal:
        return Decimal(1).scaleb(-self.size_decimals)


@dataclass(frozen=True, slots=True)
class MarketQuote:
    symbol: str
    bid: Decimal
    ask: Decimal
    mark: Decimal
    funding_rate: Decimal | None
    open_interest: Decimal | None
    source_at: datetime
    received_at: datetime
    context_received_at: datetime
    source_at_basis: str = "hyperliquid_l2_book_time"

    def __post_init__(self) -> None:
        for field, value in (("bid", self.bid), ("ask", self.ask), ("mark", self.mark)):
            _finite(value, field, positive=True)
        if self.bid > self.ask:
            raise ValueError("bid must not exceed ask")
        if self.funding_rate is not None:
            _finite(self.funding_rate, "funding_rate")
        if self.open_interest is not None:
            _finite(self.open_interest, "open_interest")
            if self.open_interest < ZERO:
                raise ValueError("open_interest must not be negative")
        _aware_utc(self.source_at, "source_at")
        _aware_utc(self.received_at, "received_at")
        _aware_utc(self.context_received_at, "context_received_at")


@dataclass(frozen=True, slots=True)
class QuoteSetHealth:
    complete: bool
    max_age_ms: int | None
    skew_ms: int | None
    trusted: bool


@dataclass(frozen=True, slots=True)
class MarketQuoteSet:
    captured_at: datetime
    quotes: tuple[MarketQuote, ...]
    instruments: tuple[InstrumentSpec, ...]
    required_symbols: tuple[str, ...] = BASELINE_SYMBOLS
    source: str = "hyperliquid"
    candle_features: tuple[CandleFeatures, ...] = ()

    def __post_init__(self) -> None:
        _aware_utc(self.captured_at, "captured_at")
        if len(set(self.required_symbols)) != len(self.required_symbols):
            raise ValueError("required symbols must be unique")
        quote_symbols = [quote.symbol for quote in self.quotes]
        if len(set(quote_symbols)) != len(quote_symbols):
            raise ValueError("quote symbols must be unique")
        instrument_symbols = [item.symbol for item in self.instruments]
        if len(set(instrument_symbols)) != len(instrument_symbols):
            raise ValueError("instrument symbols must be unique")

    def health(
        self,
        *,
        now: datetime | None = None,
        max_age: timedelta = timedelta(seconds=10),
        max_skew: timedelta = timedelta(seconds=5),
    ) -> QuoteSetHealth:
        check_at = now or self.captured_at
        _aware_utc(check_at, "now")
        by_symbol = {quote.symbol: quote for quote in self.quotes}
        complete = all(symbol in by_symbol for symbol in self.required_symbols)
        if not complete:
            return QuoteSetHealth(False, None, None, False)
        selected = [by_symbol[symbol] for symbol in self.required_symbols]
        ages = [check_at - quote.source_at for quote in selected]
        source_times = [quote.source_at for quote in selected]
        latest_age = max(ages)
        skew = max(source_times) - min(source_times)
        max_age_ms = _timedelta_millis(latest_age)
        skew_ms = _timedelta_millis(skew)
        trusted = (
            all(age >= timedelta(0) for age in ages) and latest_age <= max_age and skew <= max_skew
        )
        return QuoteSetHealth(True, max_age_ms, skew_ms, trusted)

    def to_engine_quotes(self, now: datetime | None = None) -> dict[str, Quote]:
        check_at = now or self.captured_at
        _aware_utc(check_at, "now")
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        result: dict[str, Quote] = {}
        for item in self.quotes:
            age = check_at - item.source_at
            source_delta = item.source_at - epoch
            event_seconds = Decimal(source_delta.days * 86400 + source_delta.seconds) + Decimal(
                source_delta.microseconds
            ) / Decimal(1_000_000)
            age_seconds = Decimal(age.days * 86400 + age.seconds) + Decimal(
                age.microseconds
            ) / Decimal(1_000_000)
            result[item.symbol] = Quote(
                item.symbol,
                item.bid,
                item.ask,
                item.mark,
                age_seconds,
                event_seconds,
            )
        return result


@dataclass(frozen=True, slots=True)
class CandleBar:
    symbol: str
    interval: str
    open_at: datetime
    close_at: datetime
    source_received_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        _aware_utc(self.open_at, "open_at")
        _aware_utc(self.close_at, "close_at")
        _aware_utc(self.source_received_at, "source_received_at")
        for field, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            _finite(value, field, positive=True)
        _finite(self.volume, "volume")
        if self.volume < ZERO:
            raise ValueError("volume must not be negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is above another OHLC value")
        if self.close_at <= self.open_at:
            raise ValueError("candle close time must follow open time")


@dataclass(frozen=True, slots=True)
class FundingRateRecord:
    """Hourly historical rate returned by Hyperliquid's fundingHistory endpoint."""

    symbol: str
    rate: Decimal
    event_at: datetime
    premium: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("funding symbol is required")
        _finite(self.rate, "funding rate")
        if self.premium is not None:
            _finite(self.premium, "funding premium")
        _aware_utc(self.event_at, "funding event time")


@dataclass(frozen=True, slots=True)
class CandleFeatures:
    candle: CandleBar
    ema20: Decimal | None
    rsi7: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    macd_histogram: Decimal | None


def _timedelta_millis(value: timedelta) -> int:
    return (value.days * 86400_000) + (value.seconds * 1000) + (value.microseconds // 1000)
