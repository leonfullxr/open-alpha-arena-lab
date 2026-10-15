from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.canonical import canonical_json_bytes, sha256_hex
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    InvocationAttempt,
    InvocationResult,
    MarketSnapshot,
    Position,
    PromptVersion,
    RoundAgentJob,
)
from app.db.session import SessionLocal
from app.llm.inputs import build_agent_request_bytes
from app.market.hyperliquid import HyperliquidClient
from app.market.persistence import SnapshotReceipt
from app.market.types import BASELINE_SYMBOLS
from app.worker import (
    WorkerReport,
    _provider_config,
    _worst_case_reservation,
    build_agent_input,
    capture_market_snapshot,
    run_once,
)

_APPROVED_MODELS = {"mimo-v2.6-flash", "glm-5.3-flash"}
_MAX_ROUNDS = 5
_ROUND_SECONDS = 180
_RESPONSE_SECONDS = 120


class SmokeRunError(RuntimeError):
    """A safe live-smoke setup or lifecycle failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SmokeJobResult:
    model: str
    state: str
    error_code: str | None
    output_sha256: str | None


@dataclass(frozen=True, slots=True)
class SmokeRoundResult:
    round_index: int
    logical_at: str
    snapshot_id: str
    shared_execution_quote_set_id: str | None
    jobs: tuple[SmokeJobResult, ...]


@dataclass(frozen=True, slots=True)
class SmokeReport:
    competition_id: str
    rounds: tuple[SmokeRoundResult, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def run_live_smoke(
    config_path: str | Path,
    rounds: int = 1,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    market_client_factory: type[HyperliquidClient] = HyperliquidClient,
    environment: dict[str, str] | None = None,
) -> SmokeReport:
    """Run at most five real-model rounds through the ordinary worker and execution paths.

    This function performs real public Hyperliquid reads and billable provider requests.
    The caller must explicitly invoke it and provide the named key in process environment.
    """
    env = environment if environment is not None else dict(os.environ)
    config = _load_config(config_path)
    if isinstance(rounds, bool) or not 1 <= rounds <= min(config["max_rounds"], _MAX_ROUNDS):
        raise SmokeRunError("SMOKE_ROUND_LIMIT")
    key_name = config["api_key_env"]
    if not env.get(key_name):
        raise SmokeRunError("PROVIDER_NOT_CONFIGURED")
    live_env = {**env, "APP_MODE": "live", "ENABLE_INFERENCE": "true"}

    with market_client_factory() as client:
        first_snapshot = _store_current_quotes(session_factory, client)
        competition_id = _create_competition(session_factory, config, first_snapshot)
        try:
            _preflight_smoke_inputs(
                session_factory, competition_id, first_snapshot, config, rounds
            )
            results = _run_rounds(
                session_factory,
                client,
                competition_id,
                config,
                rounds,
                first_snapshot,
                live_env,
            )
            return SmokeReport(competition_id=competition_id, rounds=tuple(results))
        finally:
            _finish_competition(session_factory, competition_id)


def _load_config(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SmokeRunError("SMOKE_CONFIG_INVALID") from None
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "max_rounds",
        "max_input_body_bytes",
        "max_output_tokens",
        "max_spend_usd",
        "max_cost_per_request_usd",
        "reservation_price_assumption_usd_per_million",
        "api_key_env",
        "models",
    }:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    if raw["schema_version"] != 1:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    max_rounds = _bounded_integer(raw["max_rounds"], 1, _MAX_ROUNDS)
    max_body = _bounded_integer(raw["max_input_body_bytes"], 1, 80_000)
    max_output = _bounded_integer(raw["max_output_tokens"], 1, 1_000)
    api_key_env = raw["api_key_env"]
    if api_key_env != "OPENCODE_API_KEY":
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    max_spend = _positive_decimal(raw["max_spend_usd"])
    max_cost = _positive_decimal(raw["max_cost_per_request_usd"])
    if max_cost > max_spend:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    prices = raw["reservation_price_assumption_usd_per_million"]
    if not isinstance(prices, dict) or set(prices) != {"input", "output"}:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    input_rate = _positive_decimal(prices["input"])
    output_rate = _positive_decimal(prices["output"])
    models = raw["models"]
    if not isinstance(models, list) or len(models) != 2:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    normalized: list[dict[str, str]] = []
    names: set[str] = set()
    model_ids: set[str] = set()
    for item in models:
        if not isinstance(item, dict) or set(item) != {"name", "provider", "model"}:
            raise SmokeRunError("SMOKE_CONFIG_INVALID")
        name = item["name"]
        provider = item["provider"]
        model = item["model"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or provider != "opencode_go"
            or model not in _APPROVED_MODELS
        ):
            raise SmokeRunError("SMOKE_CONFIG_INVALID")
        if name in names or model in model_ids:
            raise SmokeRunError("SMOKE_CONFIG_INVALID")
        names.add(name)
        model_ids.add(model)
        normalized.append({"name": name, "provider": provider, "model": model})
    if model_ids != _APPROVED_MODELS:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    return {
        "max_rounds": max_rounds,
        "max_input_body_bytes": max_body,
        "max_output_tokens": max_output,
        "max_spend_usd": max_spend,
        "max_cost_per_request_usd": max_cost,
        "input_rate": input_rate,
        "output_rate": output_rate,
        "api_key_env": api_key_env,
        "models": normalized,
    }


def _create_competition(
    session_factory: sessionmaker[Session], config: dict[str, Any], snapshot: SnapshotReceipt
) -> str:
    root = Path(__file__).resolve().parents[4]
    try:
        rules = json.loads((root / "configs/alpha_2025_baseline.json").read_text("utf-8"))
        prompt = (root / "prompts/baseline-v1.md").read_bytes()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SmokeRunError("SMOKE_BASELINE_UNAVAILABLE") from None
    rules["inference_budget_usd"] = format(config["max_spend_usd"], "f")
    rules_bytes = canonical_json_bytes(rules)
    competition_id = str(uuid.uuid4())
    prompt_id = str(uuid.uuid4())
    started_at = _utc(_snapshot_time(session_factory, snapshot.snapshot_id)) - timedelta(
        seconds=_ROUND_SECONDS
    )
    competition = Competition(
        id=competition_id,
        name=f"Live smoke {competition_id[:8]}",
        profile=rules["profile"],
        rules_bytes=rules_bytes,
        rules_sha256=sha256_hex(rules_bytes),
        initial_balance=Decimal(str(rules["initial_balance"])),
        state="RUNNING",
        source_label="LIVE DATA · PAPER · LIVE SMOKE · bounded two-model run",
        started_at=started_at,
        event_seq=0,
    )
    with session_factory() as db:
        with db.begin():
            db.add(competition)
            db.add(
                PromptVersion(
                    id=prompt_id,
                    name=f"live-smoke-{competition_id}",
                    version=1,
                    template_bytes=prompt,
                    sha256=sha256_hex(prompt),
                )
            )
            db.flush()
            for order, model in enumerate(config["models"]):
                agent_id = str(uuid.uuid4())
                settings = {
                    "adapter": "opencode_go",
                    "max_output_tokens": config["max_output_tokens"],
                    "max_input_body_bytes": config["max_input_body_bytes"],
                    "temperature": "0",
                    "input_cost_per_million_usd": format(config["input_rate"], "f"),
                    "output_cost_per_million_usd": format(config["output_rate"], "f"),
                    "max_cost_per_request_usd": format(config["max_cost_per_request_usd"], "f"),
                }
                settings_bytes = canonical_json_bytes(settings)
                db.add(
                    AgentRun(
                        id=agent_id,
                        competition_id=competition_id,
                        manifest_order=order,
                        name=model["name"],
                        provider=model["provider"],
                        model=model["model"],
                        model_settings_bytes=settings_bytes,
                        settings_sha256=sha256_hex(settings_bytes),
                        prompt_version_id=prompt_id,
                        api_key_env=config["api_key_env"],
                        status="ACTIVE",
                    )
                )
                db.add(
                    Account(
                        id=str(uuid.uuid4()),
                        agent_run_id=agent_id,
                        cash=competition.initial_balance,
                        realized_pnl=Decimal("0"),
                        fees=Decimal("0"),
                        funding=Decimal("0"),
                        reserved_margin=Decimal("0"),
                        halted=False,
                        version=0,
                    )
                )
    return competition_id


def _preflight_smoke_inputs(
    session_factory: sessionmaker[Session],
    competition_id: str,
    snapshot_receipt: SnapshotReceipt,
    config: dict[str, Any],
    rounds: int,
) -> None:
    if not snapshot_receipt.trusted:
        raise SmokeRunError("SMOKE_MARKET_UNTRUSTED")
    with session_factory() as db:
        competition = db.get(Competition, competition_id)
        snapshot = db.get(MarketSnapshot, snapshot_receipt.snapshot_id)
        if competition is None or competition.started_at is None or snapshot is None:
            raise SmokeRunError("SMOKE_BASELINE_UNAVAILABLE")
        rules = _json_object(competition.rules_bytes)
        payload = _json_object(snapshot.canonical_bytes)
        _validate_candle_warmup(payload, rules)
        agents = db.scalars(
            select(AgentRun)
            .where(AgentRun.competition_id == competition_id)
            .order_by(AgentRun.manifest_order)
        ).all()
        if len(agents) != 2:
            raise SmokeRunError("SMOKE_BASELINE_UNAVAILABLE")
        prompt = db.get(PromptVersion, agents[0].prompt_version_id)
        if prompt is None or any(agent.prompt_version_id != prompt.id for agent in agents):
            raise SmokeRunError("SMOKE_BASELINE_UNAVAILABLE")
        total_reservation = Decimal("0")
        logical_at = _utc(competition.started_at) + timedelta(seconds=_ROUND_SECONDS)
        for agent in agents:
            account = db.scalar(select(Account).where(Account.agent_run_id == agent.id))
            if account is None:
                raise SmokeRunError("SMOKE_BASELINE_UNAVAILABLE")
            positions = tuple(
                db.scalars(
                    select(Position)
                    .where(Position.account_id == account.id, Position.state == "OPEN")
                    .order_by(Position.symbol)
                ).all()
            )
            settings = _json_object(agent.model_settings_bytes)
            provider_config = _provider_config(agent.provider, agent.model, settings)
            body = build_agent_request_bytes(
                provider_config,
                system_prompt_bytes=prompt.template_bytes,
                user_prompt_bytes=build_agent_input(
                    logical_at=logical_at,
                    competition=competition,
                    snapshot=snapshot,
                    account=account,
                    positions=positions,
                ),
            )
            if len(body) > config["max_input_body_bytes"]:
                raise SmokeRunError("SMOKE_INPUT_BODY_LIMIT")
            reservation = _worst_case_reservation(provider_config, body)
            if reservation > config["max_cost_per_request_usd"]:
                raise SmokeRunError("SMOKE_REQUEST_RESERVATION_LIMIT")
            total_reservation += reservation * rounds
        if total_reservation > config["max_spend_usd"]:
            raise SmokeRunError("SMOKE_TOTAL_RESERVATION_LIMIT")


def _validate_candle_warmup(payload: dict[str, Any], rules: dict[str, Any]) -> None:
    expected_window = rules.get("market_window_candles")
    windows = payload.get("candles")
    if (
        payload.get("schema_version") != rules.get("snapshot_schema_version")
        or rules.get("proposal_schema_version") != 1
        or rules.get("public_evidence_schema_version") != 1
        or isinstance(expected_window, bool)
        or not isinstance(expected_window, int)
        or not 1 <= expected_window <= 40
        or not isinstance(windows, list)
    ):
        raise SmokeRunError("SMOKE_EVIDENCE_SCHEMA_UNSUPPORTED")
    by_symbol = {
        row.get("symbol"): row for row in windows if isinstance(row, dict)
    }
    if set(by_symbol) != set(BASELINE_SYMBOLS):
        raise SmokeRunError("SMOKE_CANDLE_WARMUP_UNAVAILABLE")
    for symbol in BASELINE_SYMBOLS:
        series = by_symbol[symbol]
        bars = series.get("bars")
        if series.get("interval") != "3m" or not isinstance(bars, list):
            raise SmokeRunError("SMOKE_CANDLE_WARMUP_UNAVAILABLE")
        if len(bars) != expected_window or not isinstance(bars[-1], dict):
            raise SmokeRunError("SMOKE_CANDLE_WARMUP_UNAVAILABLE")
        latest = bars[-1]
        if any(
            latest.get(field) is None
            for field in ("ema20", "rsi7", "macd", "macd_signal", "macd_histogram")
        ):
            raise SmokeRunError("SMOKE_CANDLE_WARMUP_UNAVAILABLE")


def _run_rounds(
    session_factory: sessionmaker[Session],
    client: HyperliquidClient,
    competition_id: str,
    config: dict[str, Any],
    rounds: int,
    first_snapshot: SnapshotReceipt,
    environment: dict[str, str],
) -> list[SmokeRoundResult]:
    results = []
    current_snapshot = first_snapshot
    for round_index in range(1, rounds + 1):
        print(
            f"live-smoke round {round_index}/{rounds} starting; two fixed models, paper mode",
            flush=True,
        )
        if round_index > 1:
            logical_at = _round_logical_at(session_factory, competition_id, round_index)
            _wait_until(logical_at - timedelta(seconds=8))
            current_snapshot = _store_current_quotes(session_factory, client)
            captured_at = _snapshot_time(session_factory, current_snapshot.snapshot_id)
            if captured_at > logical_at:
                raise SmokeRunError("SMOKE_MISSED_CANONICAL_INTERVAL")
            if (logical_at - captured_at).total_seconds() > 10:
                raise SmokeRunError("SMOKE_SNAPSHOT_TOO_OLD")
            _wait_until(logical_at)

        _drive_dispatches(session_factory, environment, competition_id, round_index)
        round_row = _get_round(session_factory, competition_id, round_index)
        if round_row is None:
            raise SmokeRunError("SMOKE_ROUND_NOT_CREATED")
        _wait_until(_utc(round_row.deadline_at))
        execution_snapshot = _store_current_quotes(session_factory, client)
        _drive_executions(session_factory, environment, competition_id, round_index)
        result = _round_result(
            session_factory,
            competition_id,
            round_index,
            current_snapshot,
            execution_snapshot,
        )
        results.append(result)
        states = ",".join(job.state for job in result.jobs)
        print(f"live-smoke round {round_index}/{rounds} complete; job_states={states}", flush=True)
    return results


def _drive_dispatches(
    session_factory: sessionmaker[Session],
    environment: dict[str, str],
    competition_id: str,
    round_index: int,
) -> None:
    round_row = _get_round(session_factory, competition_id, round_index)
    if round_row is None:
        initial_report = run_once(
            "scheduler", session_factory=session_factory, environment=environment
        )
        if initial_report.state in {"ERROR", "DISABLED"}:
            raise SmokeRunError("SMOKE_SCHEDULER_FAILED")
        round_row = _get_round(session_factory, competition_id, round_index)
    if round_row is None:
        raise SmokeRunError("SMOKE_ROUND_NOT_CREATED")
    deadline = _utc(round_row.deadline_at)
    while True:
        report: WorkerReport = run_once(
            "scheduler", session_factory=session_factory, environment=environment
        )
        if report.state == "ERROR":
            raise SmokeRunError("SMOKE_SCHEDULER_FAILED")
        with session_factory() as db:
            states = db.scalars(
                select(RoundAgentJob.state).where(RoundAgentJob.round_id == round_row.id)
            ).all()
        if len(states) == 2 and all(state in {"RESPONDED", "TERMINAL"} for state in states):
            return
        if datetime.now(UTC) >= deadline:
            return
        time.sleep(0.5)


def _drive_executions(
    session_factory: sessionmaker[Session],
    environment: dict[str, str],
    competition_id: str,
    round_index: int,
) -> None:
    round_row = _get_round(session_factory, competition_id, round_index)
    if round_row is None:
        raise SmokeRunError("SMOKE_ROUND_NOT_CREATED")
    with session_factory() as db:
        jobs = db.scalars(
            select(RoundAgentJob.id)
            .where(RoundAgentJob.round_id == round_row.id, RoundAgentJob.state == "RESPONDED")
            .order_by(RoundAgentJob.agent_run_id)
        ).all()
    for _job_id in jobs:
        report = run_once("executor", session_factory=session_factory, environment=environment)
        if report.state == "ERROR":
            raise SmokeRunError("SMOKE_EXECUTOR_FAILED")


def _round_result(
    session_factory: sessionmaker[Session],
    competition_id: str,
    round_index: int,
    prompt_snapshot: SnapshotReceipt,
    execution_snapshot: SnapshotReceipt,
) -> SmokeRoundResult:
    round_row = _get_round(session_factory, competition_id, round_index)
    if round_row is None:
        raise SmokeRunError("SMOKE_ROUND_NOT_CREATED")
    jobs: list[SmokeJobResult] = []
    with session_factory() as db:
        rows = db.execute(
            select(AgentRun.model, RoundAgentJob.state, RoundAgentJob.error_code, InvocationResult)
            .join(RoundAgentJob, RoundAgentJob.agent_run_id == AgentRun.id)
            .outerjoin(InvocationAttempt, InvocationAttempt.job_id == RoundAgentJob.id)
            .outerjoin(InvocationResult, InvocationResult.attempt_id == InvocationAttempt.id)
            .where(RoundAgentJob.round_id == round_row.id)
            .order_by(AgentRun.manifest_order)
        ).all()
        for model, state, error, result in rows:
            jobs.append(
                SmokeJobResult(
                    model=model,
                    state=state,
                    error_code=error,
                    output_sha256=result.output_sha256 if result is not None else None,
                )
            )
    return SmokeRoundResult(
        round_index=round_index,
        logical_at=_utc(round_row.logical_at).isoformat(),
        snapshot_id=prompt_snapshot.snapshot_id,
        shared_execution_quote_set_id=execution_snapshot.quote_set_id,
        jobs=tuple(jobs),
    )


def _store_current_quotes(
    session_factory: sessionmaker[Session], client: HyperliquidClient
) -> SnapshotReceipt:
    receipt, _ = capture_market_snapshot(client, session_factory)
    return receipt


def _round_logical_at(
    session_factory: sessionmaker[Session], competition_id: str, round_index: int
) -> datetime:
    with session_factory() as db:
        competition = db.get(Competition, competition_id)
        if competition is None or competition.started_at is None:
            raise SmokeRunError("SMOKE_COMPETITION_MISSING")
        return _utc(competition.started_at) + timedelta(seconds=_ROUND_SECONDS * round_index)


def _get_round(
    session_factory: sessionmaker[Session], competition_id: str, round_index: int
) -> DecisionRound | None:
    with session_factory() as db:
        return db.scalar(
            select(DecisionRound).where(
                DecisionRound.competition_id == competition_id,
                DecisionRound.round_index == round_index,
            )
        )


def _snapshot_time(session_factory: sessionmaker[Session], snapshot_id: str) -> datetime:
    with session_factory() as db:
        row = db.get(MarketSnapshot, snapshot_id)
        if row is None:
            raise SmokeRunError("SMOKE_SNAPSHOT_MISSING")
        return _utc(row.captured_at)


def _finish_competition(session_factory: sessionmaker[Session], competition_id: str) -> None:
    with session_factory() as db:
        with db.begin():
            competition = db.get(Competition, competition_id)
            if competition is not None and competition.state == "RUNNING":
                competition.state = "FINISHED"
                competition.ended_at = datetime.now(UTC)


def _wait_until(deadline: datetime) -> None:
    while True:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))


def _bounded_integer(value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    return value


def _positive_decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SmokeRunError("SMOKE_CONFIG_INVALID") from None
    if not result.is_finite() or result <= 0:
        raise SmokeRunError("SMOKE_CONFIG_INVALID")
    return result


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SmokeRunError("SMOKE_STORED_EVIDENCE_INVALID") from None
    if not isinstance(value, dict):
        raise SmokeRunError("SMOKE_STORED_EVIDENCE_INVALID")
    return value


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
