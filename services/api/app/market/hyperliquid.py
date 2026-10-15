from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.market.types import (
    BASELINE_SYMBOLS,
    CandleBar,
    FundingRateRecord,
    InstrumentSpec,
    MarketQuote,
    MarketQuoteSet,
)

INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_RESPONSE_BYTES = 2_000_000
MAX_FUNDING_EVIDENCE_BYTES = 64_000
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class MarketDataError(RuntimeError):
    """A sanitized market-data failure identified by a stable error code."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise MarketDataError("invalid_market_payload")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MarketDataError("invalid_market_payload") from None
    if not result.is_finite() or (positive and result <= 0):
        raise MarketDataError("invalid_market_payload")
    if not field:
        raise MarketDataError("invalid_market_payload")
    return result


def _utc_from_millis(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MarketDataError("invalid_market_timestamp")
    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)
    except (OverflowError, OSError, ValueError):
        raise MarketDataError("invalid_market_timestamp") from None


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _parse_json(payload: bytes) -> object:
    try:
        return json.loads(payload, parse_float=Decimal, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise MarketDataError("invalid_market_json") from None


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MarketDataError("invalid_market_payload")
    return value


def _sequence(value: object) -> Sequence[Any]:
    if not isinstance(value, list):
        raise MarketDataError("invalid_market_payload")
    return value


def _required_str(item: Mapping[str, Any], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value:
        raise MarketDataError("invalid_market_payload")
    return value


class HyperliquidClient:
    """Bounded read-only client for Hyperliquid's fixed public /info endpoint."""

    def __init__(
        self,
        *,
        symbols: tuple[str, ...] = BASELINE_SYMBOLS,
        attempts: int = 3,
        total_timeout_seconds: float = 18.0,
        request_timeout_seconds: float = 5.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not symbols or len(set(symbols)) != len(symbols) or any(not s for s in symbols):
            raise ValueError("symbols must be a non-empty unique tuple")
        if not 1 <= attempts <= 4:
            raise ValueError("market read attempts must be from 1 through 4")
        if not math.isfinite(total_timeout_seconds) or total_timeout_seconds <= 0:
            raise ValueError("total timeout must be finite and positive")
        if not math.isfinite(request_timeout_seconds) or request_timeout_seconds <= 0:
            raise ValueError("request timeout must be finite and positive")
        if not 1 <= max_response_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("response size limit is invalid")
        self.symbols = symbols
        self.attempts = attempts
        self.total_timeout_seconds = total_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._sleep = sleep
        self._deadline = 0.0
        self._owns_client = client is None
        self._client = client or httpx.Client(follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HyperliquidClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request_json(self, payload: dict[str, object]) -> object:
        return _parse_json(self._request_bytes(payload))

    def _request_bytes(self, payload: dict[str, object]) -> bytes:
        last_code = "market_transport_error"
        for attempt in range(self.attempts):
            remaining = self._deadline - self._monotonic()
            if remaining <= 0:
                raise MarketDataError("market_deadline_exceeded")
            timeout = min(self.request_timeout_seconds, remaining)
            try:
                with self._client.stream(
                    "POST",
                    INFO_URL,
                    json=payload,
                    headers={"content-type": "application/json"},
                    timeout=timeout,
                    follow_redirects=False,
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise MarketDataError(
                            "market_redirect_rejected", status_code=response.status_code
                        )
                    if response.status_code in RETRYABLE_STATUS:
                        last_code = "market_retryable_status"
                        if attempt + 1 < self.attempts:
                            self._backoff(attempt)
                            continue
                        raise MarketDataError(last_code, status_code=response.status_code)
                    if not 200 <= response.status_code < 300:
                        raise MarketDataError("market_http_error", status_code=response.status_code)
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            declared_length = int(content_length)
                        except ValueError:
                            raise MarketDataError("invalid_market_content_length") from None
                        if declared_length < 0:
                            raise MarketDataError("invalid_market_content_length")
                        if declared_length > self.max_response_bytes:
                            raise MarketDataError("market_response_too_large")
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise MarketDataError("market_response_too_large")
                    return bytes(body)
            except MarketDataError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_code = (
                    "market_timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "market_connect_error"
                )
                if attempt + 1 >= self.attempts:
                    raise MarketDataError(last_code) from None
                self._backoff(attempt)
            except httpx.RequestError:
                raise MarketDataError("market_transport_error") from None
        raise MarketDataError(last_code)

    def _backoff(self, attempt: int) -> None:
        pause = min(0.2 * (2**attempt), 0.8, self._deadline - self._monotonic())
        if pause > 0:
            self._sleep(pause)

    def capture(self) -> MarketQuoteSet:
        self._deadline = self._monotonic() + self.total_timeout_seconds
        context, context_received_at = self._metadata_and_contexts()
        quotes: list[MarketQuote] = []
        instruments = context[0]
        contexts = context[1]
        context_by_symbol = dict(zip((item.symbol for item in instruments), contexts, strict=True))

        for symbol in self.symbols:
            metadata = next((item for item in instruments if item.symbol == symbol), None)
            market_context = context_by_symbol.get(symbol)
            if metadata is None or market_context is None:
                continue
            try:
                book = _mapping(
                    self._request_json({"type": "l2Book", "coin": symbol, "nSigFigs": None})
                )
                if book.get("coin") != symbol:
                    raise MarketDataError("market_symbol_mismatch")
                source_at = _utc_from_millis(book.get("time"))
                levels = _sequence(book.get("levels"))
                if len(levels) != 2:
                    raise MarketDataError("invalid_market_book")
                bids, asks = _sequence(levels[0]), _sequence(levels[1])
                if not bids or not asks:
                    continue
                best_bid = _mapping(bids[0])
                best_ask = _mapping(asks[0])
                bid = _decimal(best_bid.get("px"), "bid", positive=True)
                ask = _decimal(best_ask.get("px"), "ask", positive=True)
                if bid > ask:
                    raise MarketDataError("crossed_market_book")
                received_at = self._clock()
                _aware_timestamp(received_at)
                quotes.append(
                    MarketQuote(
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        mark=_decimal(market_context.get("markPx"), "mark", positive=True),
                        funding_rate=_optional_decimal(market_context.get("funding")),
                        open_interest=_optional_decimal(market_context.get("openInterest")),
                        oracle_px=_optional_decimal(market_context.get("oraclePx")),
                        source_at=source_at,
                        received_at=received_at,
                        context_received_at=context_received_at,
                    )
                )
            except MarketDataError:
                continue

        captured_at = self._clock()
        _aware_timestamp(captured_at)
        return MarketQuoteSet(
            captured_at=captured_at,
            quotes=tuple(quotes),
            instruments=tuple(instruments),
            required_symbols=self.symbols,
        )

    def fetch_candles(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        interval: str = "3m",
    ) -> tuple[CandleBar, ...]:
        if symbol not in self.symbols:
            raise ValueError("symbol is outside the configured market universe")
        if interval != "3m":
            raise ValueError("only the baseline 3m candle interval is enabled")
        _aware_timestamp(start_at)
        _aware_timestamp(end_at)
        if start_at >= end_at:
            raise ValueError("candle start must precede end")
        self._deadline = self._monotonic() + self.total_timeout_seconds
        payload: dict[str, object] = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": _epoch_millis(start_at),
                "endTime": _epoch_millis(end_at),
            },
        }
        rows = _sequence(self._request_json(payload))
        received_at = self._clock()
        _aware_timestamp(received_at)
        candles = tuple(_candle_row(symbol, interval, _mapping(row), received_at) for row in rows)
        if any(
            left.open_at >= right.open_at for left, right in zip(candles, candles[1:], strict=False)
        ):
            raise MarketDataError("unordered_market_candles")
        return candles

    def fetch_funding_history(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[FundingRateRecord, ...]:
        """Fetch bounded hourly historical funding records; never substitutes predictions."""
        if symbol not in self.symbols:
            raise ValueError("symbol is outside the configured market universe")
        _aware_timestamp(start_at)
        _aware_timestamp(end_at)
        if start_at >= end_at or end_at - start_at > timedelta(hours=2):
            raise ValueError("funding history window must be positive and at most two hours")
        self._deadline = self._monotonic() + self.total_timeout_seconds
        response_bytes = self._request_bytes(
            {
                "type": "fundingHistory",
                "coin": symbol,
                "startTime": _epoch_millis(start_at),
                "endTime": _epoch_millis(end_at),
            }
        )
        if len(response_bytes) > MAX_FUNDING_EVIDENCE_BYTES:
            raise MarketDataError("funding_history_too_large")
        rows = _sequence(_parse_json(response_bytes))
        if len(rows) > 4:
            raise MarketDataError("funding_history_too_large")
        records: list[FundingRateRecord] = []
        for raw in rows:
            item = _mapping(raw)
            if _required_str(item, "coin") != symbol:
                raise MarketDataError("funding_symbol_mismatch")
            event_at = _utc_from_millis(item.get("time"))
            if event_at < start_at or event_at > end_at:
                raise MarketDataError("funding_event_outside_window")
            premium = (
                _decimal(item["premium"], "premium") if item.get("premium") is not None else None
            )
            records.append(
                FundingRateRecord(
                    symbol,
                    _decimal(item.get("fundingRate"), "funding_rate"),
                    event_at,
                    premium,
                    response_bytes,
                )
            )
        if any(
            left.event_at >= right.event_at
            for left, right in zip(records, records[1:], strict=False)
        ):
            raise MarketDataError("unordered_funding_history")
        return tuple(records)

    def _metadata_and_contexts(
        self,
    ) -> tuple[tuple[tuple[InstrumentSpec, ...], tuple[Mapping[str, Any], ...]], datetime]:
        response = _sequence(self._request_json({"type": "metaAndAssetCtxs"}))
        if len(response) != 2:
            raise MarketDataError("invalid_market_metadata")
        metadata = _mapping(response[0])
        universe = _sequence(metadata.get("universe"))
        contexts = tuple(_mapping(item) for item in _sequence(response[1]))
        if len(universe) != len(contexts):
            raise MarketDataError("invalid_market_metadata")
        by_symbol: dict[str, tuple[InstrumentSpec, Mapping[str, Any]]] = {}
        for raw_spec, raw_context in zip(universe, contexts, strict=True):
            spec_data = _mapping(raw_spec)
            symbol = _required_str(spec_data, "name")
            decimals = spec_data.get("szDecimals")
            max_leverage = spec_data.get("maxLeverage")
            if (
                isinstance(decimals, bool)
                or not isinstance(decimals, int)
                or isinstance(max_leverage, bool)
                or not isinstance(max_leverage, int)
            ):
                raise MarketDataError("invalid_instrument_metadata")
            if symbol in by_symbol:
                raise MarketDataError("duplicate_instrument_metadata")
            try:
                instrument = InstrumentSpec(symbol, decimals, max_leverage)
            except ValueError:
                raise MarketDataError("invalid_instrument_metadata") from None
            by_symbol[symbol] = (instrument, raw_context)
        missing = [symbol for symbol in self.symbols if symbol not in by_symbol]
        if missing:
            raise MarketDataError("market_instrument_missing")
        instruments = tuple(by_symbol[symbol][0] for symbol in self.symbols)
        ordered_contexts = tuple(by_symbol[symbol][1] for symbol in self.symbols)
        received_at = self._clock()
        _aware_timestamp(received_at)
        return (instruments, ordered_contexts), received_at


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, "optional_market_value")


def _aware_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")


def _epoch_millis(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) // 1000


def _candle_row(
    symbol: str,
    interval: str,
    row: Mapping[str, Any],
    source_received_at: datetime,
) -> CandleBar:
    if row.get("s") != symbol or row.get("i") != interval:
        raise MarketDataError("market_candle_symbol_mismatch")
    return CandleBar(
        symbol=symbol,
        interval=interval,
        open_at=_utc_from_millis(row.get("t")),
        close_at=_utc_from_millis(row.get("T")),
        source_received_at=source_received_at,
        open=_decimal(row.get("o"), "open", positive=True),
        high=_decimal(row.get("h"), "high", positive=True),
        low=_decimal(row.get("l"), "low", positive=True),
        close=_decimal(row.get("c"), "close", positive=True),
        volume=_decimal(row.get("v"), "volume"),
    )
