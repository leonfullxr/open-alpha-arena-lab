from __future__ import annotations

import base64
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.public_schemas import PublicRulesDTO, RulesArtifactDTO
from app.db.models import Competition
from app.db.session import get_db

rules_router = APIRouter()
_REQUIRED_DECIMALS = (
    "initial_balance",
    "quote_max_age_seconds",
    "quote_set_max_skew_seconds",
    "leverage_max",
    "commission_rate",
    "slippage_bps",
    "maintenance_margin_rate",
    "max_daily_loss",
    "max_drawdown_fraction",
    "liquidation_fee_rate",
    "min_notional",
    "max_notional",
    "max_gross_exposure",
    "fixture_funding_rate_per_hour",
)
_REQUIRED_INTS = (
    "round_seconds",
    "response_deadline_seconds",
    "quantity_precision",
    "max_positions",
    "funding_interval_hours",
    "funding_history_max_offset_seconds",
    "snapshot_schema_version",
    "proposal_schema_version",
    "public_evidence_schema_version",
    "market_window_candles",
    "indicator_warmup_bars",
)
_REQUIRED_STRINGS = (
    "profile",
    "funding_mode",
    "funding_rate_basis",
    "funding_price_basis",
    "risk_policy_version",
    "indicator_policy",
)
_REQUIRED = set(
    (*_REQUIRED_DECIMALS, *_REQUIRED_INTS, *_REQUIRED_STRINGS, "symbols", "allow_pyramiding")
)
_OPTIONAL = {"inference_budget_usd", "fixture_source"}
_SYMBOLS = {"BTC", "ETH", "SOL", "BNB", "DOGE", "XRP"}


def _decimal_string(value: object, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"invalid public rules value: {name}")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid public rules value: {name}") from exc
    if not number.is_finite():
        raise ValueError(f"invalid public rules value: {name}")
    return format(number, "f")


def serialize_rules(competition: Competition) -> RulesArtifactDTO:
    exact_bytes = competition.rules_bytes
    if hashlib.sha256(exact_bytes).hexdigest() != competition.rules_sha256:
        raise ValueError("competition rules hash mismatch")
    try:
        source = json.loads(exact_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("competition rules are not valid JSON") from exc
    if not isinstance(source, dict) or not _REQUIRED.issubset(source):
        raise ValueError("competition rules do not match a supported public schema")
    if not set(source).issubset(_REQUIRED | _OPTIONAL):
        withheld = True
    else:
        withheld = False
    symbols = source["symbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(item, str) or not item for item in symbols)
        or len(set(symbols)) != len(symbols)
        or not set(symbols).issubset(_SYMBOLS)
    ):
        raise ValueError("competition rules contain an invalid symbol manifest")
    integers: dict[str, int] = {}
    for key in _REQUIRED_INTS:
        value = source[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"competition rules contain an invalid integer: {key}")
        integers[key] = value
    strings: dict[str, str] = {}
    for key in _REQUIRED_STRINGS:
        value = source[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"competition rules contain an invalid identifier: {key}")
        strings[key] = value
    if strings["profile"] not in {"alpha_2025_baseline", "research_extended"}:
        raise ValueError("competition rules contain an unsupported profile")
    if strings["funding_mode"] != "hourly_historical_rate":
        raise ValueError("competition rules contain an unsupported funding mode")
    if strings["funding_rate_basis"] != "funding_history":
        raise ValueError("competition rules contain an unsupported funding rate basis")
    if strings["funding_price_basis"] not in {"oracle_px", "oracle_px_paper_approximation"}:
        raise ValueError("competition rules contain an unsupported funding price basis")
    if strings["risk_policy_version"] != "risk-v1":
        raise ValueError("competition rules contain an unsupported risk policy")
    if strings["indicator_policy"] != "trailing_500_v1":
        raise ValueError("competition rules contain an unsupported indicator policy")
    if integers["indicator_warmup_bars"] != 500:
        raise ValueError("competition rules contain an unsupported indicator warmup")
    allow_pyramiding = source["allow_pyramiding"]
    if not isinstance(allow_pyramiding, bool):
        raise ValueError("competition rules contain an invalid pyramiding policy")
    public_values: dict[str, object] = {
        **strings,
        **integers,
        "symbols": symbols,
        "allow_pyramiding": allow_pyramiding,
    }
    public_values.update({key: _decimal_string(source[key], key) for key in _REQUIRED_DECIMALS})
    inference_budget = source.get("inference_budget_usd")
    public_values["inference_budget_usd"] = (
        _decimal_string(inference_budget, "inference_budget_usd")
        if inference_budget is not None
        else None
    )
    fixture_source = source.get("fixture_source")
    if fixture_source is not None and (
        not isinstance(fixture_source, str)
        or not fixture_source.startswith("fixture-replay-v")
        or not fixture_source.removeprefix("fixture-replay-v").isdigit()
    ):
        raise ValueError("competition rules contain an invalid fixture source")
    public_values["fixture_source"] = fixture_source
    public_rules = PublicRulesDTO.model_validate(public_values)
    return RulesArtifactDTO(
        sha256=competition.rules_sha256,
        bytes_base64=(base64.b64encode(exact_bytes).decode("ascii") if not withheld else None),
        bytes_withheld=withheld,
        public=public_rules,
        withheld_fields=withheld,
    )


@rules_router.get("/competitions/{competition_id}/rules", response_model=RulesArtifactDTO)
def competition_rules(
    competition_id: str, db: Annotated[Session, Depends(get_db)]
) -> RulesArtifactDTO:
    competition = db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    try:
        return serialize_rules(competition)
    except ValueError:
        raise HTTPException(
            status_code=503, detail="Competition rules evidence unavailable"
        ) from None
