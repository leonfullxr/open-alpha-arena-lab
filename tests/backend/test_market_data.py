from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from app.market.hyperliquid import HyperliquidClient, MarketDataError, _utc_from_millis
from app.market.types import BASELINE_SYMBOLS, CandleBar, MarketQuote, MarketQuoteSet

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)


def metadata() -> list[object]:
    return [
        {
            "universe": [
                {"name": symbol, "szDecimals": 4, "maxLeverage": 20} for symbol in BASELINE_SYMBOLS
            ]
        },
        [
            {
                "markPx": "100",
                "oraclePx": "98.5",
                "funding": "0.0001",
                "openInterest": "42",
            }
            for _ in BASELINE_SYMBOLS
        ],
    ]


def book(symbol: str, *, time_ms: int = NOW_MS) -> dict[str, object]:
    return {
        "coin": symbol,
        "time": time_ms,
        "levels": [[{"px": "99", "sz": "1"}], [{"px": "101", "sz": "2"}]],
    }


def make_quote(symbol: str, *, source_at: datetime = NOW) -> MarketQuote:
    return MarketQuote(
        symbol=symbol,
        bid=Decimal("99"),
        ask=Decimal("101"),
        mark=Decimal("100"),
        funding_rate=Decimal("0.0001"),
        open_interest=Decimal("42"),
        oracle_px=Decimal("98.5"),
        source_at=source_at,
        received_at=NOW,
        context_received_at=NOW,
    )


def test_capture_uses_fixed_endpoint_and_returns_complete_fresh_set() -> None:
    seen: list[tuple[str, str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append((request.method, str(request.url), payload))
        data = metadata() if payload == {"type": "metaAndAssetCtxs"} else book(payload["coin"])
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(handle)
    with httpx.Client(transport=transport) as client:
        market = HyperliquidClient(client=client, clock=lambda: NOW, sleep=lambda _: None)
        quote_set = market.capture()

    assert quote_set.health().trusted
    assert quote_set.health().max_age_ms == 0
    assert len(quote_set.quotes) == 6
    assert len(quote_set.instruments) == 6
    assert quote_set.quotes[0].funding_rate == Decimal("0.0001")
    assert quote_set.quotes[0].open_interest == Decimal("42")
    assert quote_set.quotes[0].oracle_px == Decimal("98.5")
    assert len(seen) == 7
    assert all(
        method == "POST" and url == "https://api.hyperliquid.xyz/info" for method, url, _ in seen
    )
    assert seen[0][2] == {"type": "metaAndAssetCtxs"}


def test_capture_marks_missing_or_invalid_books_incomplete_without_fabrication() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["type"] == "metaAndAssetCtxs":
            return httpx.Response(200, json=metadata())
        if payload["coin"] == "ETH":
            return httpx.Response(200, json=book("BTC"))
        if payload["coin"] == "SOL":
            return httpx.Response(200, json={"coin": "SOL", "time": NOW_MS, "levels": [[], []]})
        return httpx.Response(200, json=book(payload["coin"]))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = HyperliquidClient(client=client, clock=lambda: NOW, sleep=lambda _: None).capture()
    assert {quote.symbol for quote in result.quotes} == {"BTC", "BNB", "DOGE", "XRP"}
    assert not result.health().complete
    assert not result.health().trusted


def test_quote_set_freshness_and_skew_boundaries_are_exact() -> None:
    quotes = tuple(
        make_quote(symbol, source_at=NOW - timedelta(seconds=10) + timedelta(milliseconds=index))
        for index, symbol in enumerate(BASELINE_SYMBOLS)
    )
    result = MarketQuoteSet(captured_at=NOW, quotes=quotes, instruments=())
    assert result.health(now=NOW).trusted
    assert result.health(now=NOW + timedelta(milliseconds=1)).trusted is False

    skewed = tuple(
        make_quote(symbol, source_at=NOW + timedelta(milliseconds=1000 * index))
        for index, symbol in enumerate(BASELINE_SYMBOLS)
    )
    assert MarketQuoteSet(captured_at=NOW, quotes=skewed, instruments=()).health().trusted is False


def test_engine_quote_conversion_preserves_event_time_and_age() -> None:
    quote = make_quote("BTC", source_at=NOW - timedelta(milliseconds=250))
    converted = MarketQuoteSet(NOW, (quote,), ()).to_engine_quotes(NOW)["BTC"]
    assert converted.age_seconds == Decimal("0.25")
    assert converted.event_seconds == Decimal(str(NOW.timestamp())) - Decimal("0.25")


def test_candle_backfill_parses_order_and_received_timestamp() -> None:
    candle_payload = [
        {
            "s": "BTC",
            "i": "3m",
            "t": NOW_MS,
            "T": NOW_MS + 179_999,
            "o": "1",
            "h": "3",
            "l": "1",
            "c": "2",
            "v": "8",
        },
        {
            "s": "BTC",
            "i": "3m",
            "t": NOW_MS + 180_000,
            "T": NOW_MS + 359_999,
            "o": "2",
            "h": "4",
            "l": "2",
            "c": "3",
            "v": "9",
        },
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=candle_payload))
    ) as client:
        result = HyperliquidClient(
            client=client, clock=lambda: NOW, sleep=lambda _: None
        ).fetch_candles("BTC", start_at=NOW, end_at=NOW + timedelta(minutes=6))
    assert len(result) == 2
    assert result[0].source_received_at == NOW
    assert result[0].open_at < result[1].open_at


def test_funding_history_parses_hourly_historical_rate_without_prediction_fallback() -> None:
    requests: list[dict[str, object]] = []
    response_bodies: list[bytes] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        response = httpx.Response(
            200,
            json=[
                {
                    "coin": "BTC",
                    "fundingRate": "0.0000125",
                    "premium": "0.0000025",
                    "time": NOW_MS,
                }
            ],
        )
        response_bodies.append(response.content)
        return response

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        rows = HyperliquidClient(client=client, clock=lambda: NOW).fetch_funding_history(
            "BTC",
            start_at=NOW - timedelta(seconds=1),
            end_at=NOW + timedelta(seconds=1),
        )

    assert len(rows) == 1
    assert rows[0].symbol == "BTC"
    assert rows[0].rate == Decimal("0.0000125")
    assert rows[0].premium == Decimal("0.0000025")
    assert rows[0].event_at == NOW
    assert rows[0].raw_record_bytes == response_bodies[0]
    assert requests == [
        {
            "type": "fundingHistory",
            "coin": "BTC",
            "startTime": NOW_MS - 1000,
            "endTime": NOW_MS + 1000,
        }
    ]


def test_funding_history_rejects_bad_symbol_timestamp_and_unbounded_windows() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json=[
                    {
                        "coin": "ETH",
                        "fundingRate": "0.001",
                        "premium": "0",
                        "time": NOW_MS,
                    }
                ],
            )
        )
    ) as client:
        market = HyperliquidClient(client=client, sleep=lambda _: None)
        with pytest.raises(MarketDataError, match="funding_symbol_mismatch"):
            market.fetch_funding_history(
                "BTC", start_at=NOW - timedelta(seconds=1), end_at=NOW + timedelta(seconds=1)
            )
        with pytest.raises(ValueError, match="at most two hours"):
            market.fetch_funding_history("BTC", start_at=NOW, end_at=NOW + timedelta(hours=3))


def test_duplicate_metadata_and_out_of_order_candles_fail_closed() -> None:
    duplicate = [
        {
            "universe": [
                {"name": symbol, "szDecimals": 4, "maxLeverage": 20} for symbol in BASELINE_SYMBOLS
            ]
            + [{"name": "BTC", "szDecimals": 4, "maxLeverage": 20}]
        },
        [{"markPx": "100", "funding": "0", "openInterest": "1"} for _ in range(7)],
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=duplicate))
    ) as client:
        market = HyperliquidClient(client=client, clock=lambda: NOW, sleep=lambda _: None)
        with pytest.raises(MarketDataError, match="duplicate_instrument_metadata"):
            market.capture()

    assert _utc_from_millis(NOW_MS) == NOW
    with pytest.raises(MarketDataError, match="invalid_market_timestamp"):
        _utc_from_millis(True)


def test_temporary_http_failures_retry_but_bad_payload_does_not() -> None:
    attempts = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json=metadata())

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        market = HyperliquidClient(client=client, clock=lambda: NOW, sleep=lambda _: None)
        market._deadline = 100
        market._monotonic = lambda: 0
        assert market._request_json({"type": "metaAndAssetCtxs"}) == metadata()
    assert attempts == 3

    attempts = 0

    def malformed(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, content=b"not-json")

    with httpx.Client(transport=httpx.MockTransport(malformed)) as client:
        market = HyperliquidClient(client=client, sleep=lambda _: None)
        market._deadline = 100
        market._monotonic = lambda: 0
        with pytest.raises(MarketDataError, match="invalid_market_json"):
            market._request_json({"type": "metaAndAssetCtxs"})
    assert attempts == 1


def _candle(index: int, close: str) -> CandleBar:
    open_at = NOW + timedelta(minutes=3 * index)
    value = Decimal(close)
    return CandleBar(
        symbol="BTC",
        interval="3m",
        open_at=open_at,
        close_at=open_at + timedelta(minutes=3) - timedelta(milliseconds=1),
        source_received_at=NOW,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1"),
    )


def test_fixed_universe_and_precise_feature_warmups() -> None:
    assert BASELINE_SYMBOLS == ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
    from app.market.indicators import calculate_features

    features = calculate_features(tuple(_candle(i, str(100 + i)) for i in range(40)))
    assert features[18].ema20 is None
    assert features[19].ema20 == Decimal("109.5")
    assert features[6].rsi7 is None
    assert features[7].rsi7 == Decimal("100")
    assert features[32].macd_signal is None
    assert features[33].macd_signal is not None
    assert features[33].macd_histogram is not None
