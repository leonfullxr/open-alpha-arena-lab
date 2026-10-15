from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PROFILE_FILES = {
    "alpha_2025_baseline": "alpha_2025_baseline.json",
    "research_extended": "research_extended.json",
}
_REQUIRED = {
    "profile",
    "symbols",
    "initial_balance",
    "round_seconds",
    "response_deadline_seconds",
    "quote_max_age_seconds",
    "quote_set_max_skew_seconds",
    "leverage_max",
    "commission_rate",
    "slippage_bps",
    "maintenance_margin_rate",
    "max_daily_loss",
    "max_drawdown_fraction",
    "liquidation_fee_rate",
    "quantity_precision",
    "min_notional",
    "max_notional",
    "max_gross_exposure",
    "max_positions",
    "allow_pyramiding",
    "funding_mode",
    "funding_interval_hours",
    "funding_history_max_offset_seconds",
    "funding_rate_basis",
    "funding_price_basis",
    "fixture_funding_rate_per_hour",
    "risk_policy_version",
    "snapshot_schema_version",
    "proposal_schema_version",
    "public_evidence_schema_version",
    "market_window_candles",
    "indicator_policy",
    "indicator_warmup_bars",
}


def canonical_profile(profile: str) -> dict[str, Any]:
    filename = _PROFILE_FILES.get(profile)
    if filename is None:
        raise ValueError("profile must be alpha_2025_baseline or research_extended")
    root = Path(__file__).resolve().parents[4]
    try:
        value = json.loads((root / "configs" / filename).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"canonical competition profile {profile} is unavailable") from exc
    if not isinstance(value, dict) or set(value) != _REQUIRED or value.get("profile") != profile:
        raise RuntimeError(f"canonical competition profile {profile} is invalid")
    return value
