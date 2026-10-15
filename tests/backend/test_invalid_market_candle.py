from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.market.hyperliquid import HyperliquidClient, MarketDataError


def test_hyperliquid_invalid_candle_values_are_sanitized_at_http_boundary() -> None:
    start_at = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    start_ms = int(start_at.timestamp() * 1000)
    payload = [
        {
            "s": "BTC",
            "i": "3m",
            "t": start_ms,
            "T": start_ms + 179_999,
            "o": "100",
            "h": "99",
            "l": "98",
            "c": "100",
            "v": "1",
        }
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        provider = HyperliquidClient(
            symbols=("BTC",),
            client=client,
            clock=lambda: start_at + timedelta(seconds=2),
        )
        with pytest.raises(MarketDataError, match="invalid_market_candle") as failure:
            provider.fetch_candles("BTC", start_at=start_at, end_at=start_at + timedelta(minutes=3))
    assert str(failure.value) == "invalid_market_candle"
