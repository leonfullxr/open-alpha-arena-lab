from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from app.core.canonical import canonical_json_bytes
from app.llm.providers import ProviderConfig, build_request_bytes
from app.llm.schema import ProposalBatch
from app.market.indicators import INDICATOR_POLICY, INDICATOR_WARMUP_BARS
from app.market.types import BASELINE_SYMBOLS


class InputEvidenceError(ValueError):
    """A stable failure raised when a live model input lacks trusted market evidence."""

    code = "MARKET_INPUT_UNAVAILABLE"


def build_user_input(
    *,
    logical_at: datetime,
    frozen_rules: Mapping[str, object],
    frozen_rules_sha256: str,
    snapshot: Mapping[str, object],
    snapshot_sha256: str,
    own_account: Mapping[str, object],
) -> bytes:
    """Render the shared, bounded public model input envelope as canonical bytes."""
    if logical_at.tzinfo is None or logical_at.utcoffset() is None:
        raise ValueError("logical_at must be timezone-aware")
    if not frozen_rules_sha256 or not snapshot_sha256:
        raise ValueError("input evidence hashes are required")
    _validate_evidence_contract(frozen_rules, snapshot)
    return canonical_json_bytes(
        {
            "input_schema_version": 1,
            "proposal_schema_version": frozen_rules["proposal_schema_version"],
            "public_evidence_schema_version": frozen_rules["public_evidence_schema_version"],
            "market_window_candles": frozen_rules["market_window_candles"],
            "proposal_schema_json": json.dumps(
                ProposalBatch.model_json_schema(), sort_keys=True, separators=(",", ":")
            ),
            "valid_example": {
                "proposals": [
                    {
                        "action": "HOLD",
                        "symbol": "BTC",
                        "quantity": "0",
                        "leverage": "1",
                        "stop_loss": None,
                        "take_profit": None,
                        "confidence": "0.5",
                        "invalidation": "A stated market condition changes.",
                        "justification": "No trade is justified by the supplied evidence.",
                    }
                ]
            },
            "logical_at": logical_at.astimezone(UTC).isoformat(),
            "frozen_rules": dict(frozen_rules),
            "frozen_rules_sha256": frozen_rules_sha256,
            "snapshot": dict(snapshot),
            "snapshot_sha256": snapshot_sha256,
            "own_account": dict(own_account),
        }
    )


def _validate_evidence_contract(
    frozen_rules: Mapping[str, object], snapshot: Mapping[str, object]
) -> None:
    versions = {
        "snapshot_schema_version": 1,
        "proposal_schema_version": 1,
        "public_evidence_schema_version": 1,
    }
    for key, expected in versions.items():
        if frozen_rules.get(key) != expected:
            raise ValueError("frozen evidence schema version is unsupported")
    window = frozen_rules.get("market_window_candles")
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 40:
        raise ValueError("frozen market evidence window is invalid")
    if (
        frozen_rules.get("indicator_policy") != INDICATOR_POLICY
        or frozen_rules.get("indicator_warmup_bars") != INDICATOR_WARMUP_BARS
        or snapshot.get("indicator_policy") != frozen_rules.get("indicator_policy")
        or snapshot.get("indicator_warmup_bars") != frozen_rules.get("indicator_warmup_bars")
    ):
        raise ValueError("snapshot indicator policy does not match frozen rules")
    if snapshot.get("schema_version") != frozen_rules["snapshot_schema_version"]:
        raise ValueError("snapshot evidence schema does not match frozen rules")
    candles = snapshot.get("candles")
    if not isinstance(candles, list):
        raise ValueError("snapshot candle evidence is invalid")
    source = snapshot.get("source")
    if source == "hyperliquid":
        _require_live_candle_evidence(frozen_rules, snapshot, candles)
    elif source not in {"mock-worker", "DEMO REPLAY", "fixture-replay-v3"}:
        raise InputEvidenceError("live market input source is not approved")
    elif snapshot.get("candle_error") is not None:
        raise InputEvidenceError("fixture market input contains a candle failure")
    symbols: set[str] = set()
    for series in candles:
        if not isinstance(series, dict):
            raise ValueError("snapshot candle series is invalid")
        symbol = series.get("symbol")
        bars = series.get("bars")
        if (
            not isinstance(symbol, str)
            or symbol not in BASELINE_SYMBOLS
            or symbol in symbols
            or series.get("interval") != "3m"
            or not isinstance(bars, list)
            or len(bars) > window
        ):
            raise ValueError("snapshot candle series is outside the frozen window")
        symbols.add(symbol)


def _require_live_candle_evidence(
    frozen_rules: Mapping[str, object],
    snapshot: Mapping[str, object],
    candles: list[object],
) -> None:
    window = frozen_rules.get("market_window_candles")
    if (
        snapshot.get("candle_error") is not None
        or window != 12
        or len(candles) != len(BASELINE_SYMBOLS)
    ):
        raise InputEvidenceError("live market candle evidence is incomplete")
    by_symbol: dict[str, object] = {}
    for series in candles:
        if not isinstance(series, dict):
            raise InputEvidenceError("live market candle series is malformed")
        symbol = series.get("symbol")
        if (
            not isinstance(symbol, str)
            or symbol not in BASELINE_SYMBOLS
            or symbol in by_symbol
            or series.get("interval") != "3m"
        ):
            raise InputEvidenceError("live market candle symbols are incomplete")
        by_symbol[symbol] = series
    if set(by_symbol) != set(BASELINE_SYMBOLS):
        raise InputEvidenceError("live market candle symbols are incomplete")
    for symbol in BASELINE_SYMBOLS:
        series = by_symbol[symbol]
        if not isinstance(series, dict):
            raise InputEvidenceError("live market candle series is malformed")
        bars = series.get("bars")
        if not isinstance(bars, list) or len(bars) != window:
            raise InputEvidenceError("live market candle window is incomplete")
        for bar in bars:
            if not isinstance(bar, dict) or any(
                bar.get(feature) is None
                for feature in (
                    "ema20",
                    "rsi7",
                    "macd",
                    "macd_signal",
                    "macd_histogram",
                )
            ):
                raise InputEvidenceError("live market candle indicators are not warmed")


def build_agent_request_bytes(
    config: ProviderConfig,
    *,
    system_prompt_bytes: bytes,
    user_prompt_bytes: bytes,
) -> bytes:
    """Freeze the exact provider request body; secrets are transport headers only."""
    return build_request_bytes(
        config,
        system_prompt_bytes=system_prompt_bytes,
        user_prompt_bytes=user_prompt_bytes,
    )
