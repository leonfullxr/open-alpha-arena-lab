from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import Account, AgentRun, Competition, PromptVersion, ProviderProfile
from sqlalchemy import select
from sqlalchemy.orm import Session

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_PROVIDERS = {
    "openai_chat": "https://api.openai.com/v1/chat/completions",
    "openai_responses": "https://api.openai.com/v1/responses",
    "opencode_go": "https://opencode.ai/inference/go/v1/chat/completions",
}


class AdminInputError(ValueError):
    pass


def create_provider_profile(db: Session, payload: dict[str, object]) -> ProviderProfile:
    adapter = _text(payload, "adapter", 32)
    endpoint = _PROVIDERS.get(adapter)
    if endpoint is None:
        raise AdminInputError("provider adapter is not approved")
    name = _text(payload, "name", 120)
    model = _text(payload, "model", 120)
    key_ref = _text(payload, "api_key_env", 80)
    if not _ENV_NAME.fullmatch(key_ref):
        raise AdminInputError("api_key_env must be an environment variable name")
    input_rate = _positive_decimal(payload.get("input_cost_per_million"))
    output_rate = _positive_decimal(payload.get("output_cost_per_million"))
    output_tokens = _bounded_int(payload.get("max_output_tokens"), 1, 2000)
    input_bytes = _bounded_int(payload.get("max_input_body_bytes", 250000), 1, 250000)
    temperature = _decimal(payload.get("temperature", "0"))
    if temperature < 0 or temperature > 2:
        raise AdminInputError("temperature must be between 0 and 2")
    max_call_cost = _positive_decimal(payload.get("max_cost_per_request_usd"))
    # Refuse a bound that cannot cover the full configured request budget.
    worst_case = (
        Decimal(input_bytes) * input_rate + Decimal(output_tokens) * output_rate
    ) / Decimal(1_000_000)
    if worst_case > max_call_cost:
        raise AdminInputError("per-request cap is below the configured worst-case cost")
    version = _bounded_int(payload.get("version", 1), 1, 2_147_483_647)
    settings = {
        "adapter": adapter,
        "input_cost_per_million_usd": format(input_rate, "f"),
        "output_cost_per_million_usd": format(output_rate, "f"),
        "max_output_tokens": output_tokens,
        "max_input_body_bytes": input_bytes,
        "max_cost_per_request_usd": format(max_call_cost, "f"),
        "temperature": format(temperature, "f"),
    }
    digest = sha256_hex(canonical_json_bytes(settings))
    if db.scalar(
        select(ProviderProfile.id).where(
            ProviderProfile.name == name, ProviderProfile.version == version
        )
    ):
        raise AdminInputError("provider profile version already exists")
    row = ProviderProfile(
        id=str(uuid.uuid4()),
        name=name,
        version=version,
        adapter=adapter,
        model=model,
        endpoint=endpoint,
        api_key_env=key_ref,
        input_cost_per_million=input_rate,
        output_cost_per_million=output_rate,
        max_input_body_bytes=input_bytes,
        max_cost_per_request_usd=max_call_cost,
        max_output_tokens=output_tokens,
        temperature=temperature,
        settings_sha256=digest,
        active=True,
    )
    db.add(row)
    db.commit()
    return row


def create_prompt_version(db: Session, *, name: str, template: str, version: int) -> PromptVersion:
    if not name or len(name) > 120 or not template or len(template.encode("utf-8")) > 100_000:
        raise AdminInputError("prompt name or template is empty or too large")
    if version < 1 or version > 2_147_483_647:
        raise AdminInputError("prompt version is invalid")
    existing = db.scalar(
        select(PromptVersion.id).where(PromptVersion.name == name, PromptVersion.version == version)
    )
    if existing:
        raise AdminInputError("prompt version already exists")
    data = template.encode("utf-8")
    row = PromptVersion(
        id=str(uuid.uuid4()),
        name=name,
        version=version,
        template_bytes=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )
    db.add(row)
    db.commit()
    return row


def create_competition(db: Session, payload: dict[str, object]) -> Competition:
    name = _text(payload, "name", 120)
    profile = payload.get("profile", "alpha_2025_baseline")
    if profile not in {"alpha_2025_baseline", "research_extended"}:
        raise AdminInputError("profile must be alpha_2025_baseline or research_extended")
    canonical_rules = canonical_profile(str(profile))
    balance = _positive_decimal(canonical_rules["initial_balance"])
    requested_balance = payload.get("initial_balance", canonical_rules["initial_balance"])
    if _positive_decimal(requested_balance) != balance:
        raise AdminInputError("initial balance is frozen by the competition profile")
    inference_budget = _positive_decimal(payload.get("inference_budget_usd"))
    agents = payload.get("agents")
    if not isinstance(agents, list) or not 1 <= len(agents) <= 6:
        raise AdminInputError("competition requires 1..6 agents")
    prompt_ids = {spec.get("prompt_version_id") for spec in agents if isinstance(spec, dict)}
    if len(prompt_ids) != 1 or len(prompt_ids) != len(agents):
        raise AdminInputError("all agents must use one shared prompt version")
    rules = {**canonical_rules, "inference_budget_usd": format(inference_budget, "f")}
    rules_bytes = canonical_json_bytes(rules)
    competition = Competition(
        id=str(uuid.uuid4()),
        name=name,
        profile=str(profile),
        rules_bytes=rules_bytes,
        rules_sha256=sha256_hex(rules_bytes),
        initial_balance=balance,
        state="DRAFT",
        source_label="LIVE · awaiting start",
        kill_switch=False,
        event_seq=0,
    )
    db.add(competition)
    db.flush()
    for order, spec in enumerate(agents):
        if not isinstance(spec, dict):
            raise AdminInputError("each agent must be an object")
        agent_name = _text(spec, "name", 80)
        provider_id = _text(spec, "provider_profile_id", 36)
        prompt_id = _text(spec, "prompt_version_id", 36)
        provider = db.get(ProviderProfile, provider_id)
        prompt = db.get(PromptVersion, prompt_id)
        if provider is None or not provider.active:
            raise AdminInputError("provider profile is missing or inactive")
        if prompt is None:
            raise AdminInputError("prompt version does not exist")
        settings = {
            "adapter": provider.adapter,
            "input_cost_per_million_usd": format(provider.input_cost_per_million, "f"),
            "output_cost_per_million_usd": format(provider.output_cost_per_million, "f"),
            "max_output_tokens": provider.max_output_tokens,
            "max_input_body_bytes": provider.max_input_body_bytes,
            "max_cost_per_request_usd": format(provider.max_cost_per_request_usd, "f"),
            "temperature": format(provider.temperature, "f"),
            "provider_profile_version": provider.version,
            "provider_settings_sha256": provider.settings_sha256,
        }
        settings_bytes = canonical_json_bytes(settings)
        run = AgentRun(
            id=str(uuid.uuid4()),
            competition_id=competition.id,
            manifest_order=order,
            name=agent_name,
            provider=provider.adapter,
            model=provider.model,
            provider_profile_id=provider.id,
            model_settings_bytes=settings_bytes,
            settings_sha256=sha256_hex(settings_bytes),
            prompt_version_id=prompt.id,
            api_key_env=provider.api_key_env,
            status="ACTIVE",
        )
        db.add(run)
        db.flush()
        db.add(
            Account(
                id=str(uuid.uuid4()),
                agent_run_id=run.id,
                cash=balance,
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
                reserved_margin=Decimal("0"),
                halted=False,
                peak_equity=balance,
                daily_baseline_equity=balance,
                risk_day=datetime.now(UTC).date(),
                version=0,
            )
        )
    db.commit()
    db.refresh(competition)
    return competition


def validate_competition_start(db: Session, competition: Competition) -> None:
    agents = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.competition_id == competition.id)
            .order_by(AgentRun.manifest_order)
        )
    )
    if not agents:
        raise AdminInputError("competition has no agent manifest")
    for agent in agents:
        if not agent.api_key_env or not _ENV_NAME.fullmatch(agent.api_key_env):
            raise AdminInputError("provider credential reference is invalid")
        if not os.environ.get(agent.api_key_env):
            raise AdminInputError("provider credential is not configured")
        try:
            rules = json.loads(competition.rules_bytes)
            agent_settings = json.loads(agent.model_settings_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AdminInputError("frozen settings are invalid") from exc
        if not rules.get("inference_budget_usd") or not agent_settings.get(
            "max_cost_per_request_usd"
        ):
            raise AdminInputError("frozen inference budget is not configured")


def _text(payload: dict[str, object], key: str, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AdminInputError(f"{key} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _decimal(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AdminInputError("amount must be a Decimal-compatible value") from exc
    if not amount.is_finite() or amount < 0 or amount >= Decimal("1e20"):
        raise AdminInputError("amount is outside numeric(38,18) range")
    return amount


def _positive_decimal(value: object) -> Decimal:
    amount = _decimal(value)
    if amount <= 0:
        raise AdminInputError("amount must be positive")
    return amount


def _bounded_int(value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AdminInputError(f"value must be an integer from {minimum} through {maximum}")
    return value
