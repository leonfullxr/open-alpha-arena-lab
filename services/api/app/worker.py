from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.canonical import canonical_json_bytes
from app.db.models import (
    Account as AccountRow,
)
from app.db.models import (
    AgentRun,
    Competition,
    DecisionRound,
    MarketSnapshot,
    PromptVersion,
    QuoteSet,
    RoundAgentJob,
    WorkerHeartbeat,
)
from app.db.models import (
    Position as PositionRow,
)
from app.db.session import SessionLocal
from app.llm.providers import (
    OPENAI_CHAT_URL,
    OPENAI_RESPONSES_URL,
    OPENCODE_GO_CHAT_URL,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    ProviderResult,
    build_request_bytes,
)
from app.market.hyperliquid import HyperliquidClient, MarketDataError
from app.market.persistence import (
    SnapshotReceipt,
    load_candle_features,
    load_candles,
    persist_candles,
    persist_quote_set,
)
from app.market.types import BASELINE_SYMBOLS, CandleBar, MarketQuoteSet
from app.services.execution import (
    ExecutionReceipt,
    execute_job,
    run_protective_exit_cycle,
)
from app.services.invocation import (
    ClaimedJob,
    InvocationCompletion,
    PreparedDispatch,
    apply_invocation_result,
    claim_next_job,
    prepare_invocation_dispatch,
    terminalize_undispatched,
)

LOGGER = logging.getLogger("arena.worker")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_ADAPTER_ENDPOINTS = {
    "openai_chat": OPENAI_CHAT_URL,
    "openai_responses": OPENAI_RESPONSES_URL,
    "opencode_go": OPENCODE_GO_CHAT_URL,
}
_POLL_SECONDS = 1
_MAX_REQUEST_BYTES = 250_000
_CLAIM_LEASE_SECONDS = 130
_MAX_PARALLEL_DISPATCH = 4
_WORKER_INSTANCE = os.environ.get("WORKER_INSTANCE_ID") or str(uuid.uuid4())


class MarketCollectorClient(Protocol):
    def capture(self) -> MarketQuoteSet: ...

    def fetch_candles(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        interval: str = "3m",
    ) -> tuple[CandleBar, ...]: ...


@dataclass(frozen=True, slots=True)
class WorkerReport:
    worker: str
    state: str
    handled: int = 0
    detail: str = ""


def run_once(
    worker: str,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    environment: Mapping[str, str] | None = None,
    market_client_factory: Callable[[], HyperliquidClient] | None = None,
) -> WorkerReport:
    """Run one bounded worker cycle; demo mode never enables external requests."""
    env = environment or os.environ
    if worker not in {"collector", "scheduler", "executor"}:
        raise ValueError("unknown worker name")
    if worker == "collector":
        report = _collect_once(session_factory, env, market_client_factory)
    elif worker == "scheduler":
        report = _schedule_once(session_factory, env)
    else:
        report = _execute_once(session_factory, env)
    _heartbeat(session_factory, report)
    return report


def _collect_once(
    session_factory: sessionmaker[Session],
    env: Mapping[str, str],
    client_factory: Callable[[], HyperliquidClient] | None,
) -> WorkerReport:
    if env.get("APP_MODE", "demo") != "live" or env.get("MARKET_PROVIDER", "demo") != "hyperliquid":
        return WorkerReport("collector", "DISABLED", detail="live market collection is disabled")
    factory = client_factory or HyperliquidClient
    try:
        with factory() as client:
            receipt, candle_changes = capture_market_snapshot(client, session_factory)
        state = "READY" if receipt.trusted else "DEGRADED"
        return WorkerReport(
            "collector",
            state,
            handled=1 + candle_changes,
            detail="quote set and bounded candle backfill stored",
        )
    except MarketDataError as exc:
        LOGGER.warning("market collection failed code=%s", exc.code)
        return WorkerReport("collector", "ERROR", detail=exc.code)
    except Exception as exc:
        LOGGER.error("market collection failed error_class=%s", type(exc).__name__)
        return WorkerReport("collector", "ERROR", detail="MARKET_COLLECTION_FAILED")


def _collect_candles(
    client: MarketCollectorClient,
    session_factory: sessionmaker[Session],
    captured_at: datetime,
) -> int:
    changes = 0
    latest_complete = captured_at.replace(second=0, microsecond=0)
    latest_complete -= timedelta(minutes=latest_complete.minute % 3)
    for symbol in BASELINE_SYMBOLS:
        with session_factory() as db:
            existing = load_candles(db, symbol)
        if existing:
            start_at = max(
                existing[-1].open_at - timedelta(minutes=3), latest_complete - timedelta(days=9)
            )
        else:
            start_at = latest_complete - timedelta(days=9)
        if start_at >= latest_complete:
            continue
        fetched = client.fetch_candles(
            symbol,
            start_at=start_at,
            end_at=latest_complete,
            interval="3m",
        )
        by_open = {bar.open_at: bar for bar in (*existing, *fetched)}
        merged = tuple(by_open[key] for key in sorted(by_open))
        if merged:
            with session_factory() as db:
                changes += persist_candles(db, merged)
    return changes


def capture_market_snapshot(
    client: MarketCollectorClient,
    session_factory: sessionmaker[Session],
) -> tuple[SnapshotReceipt, int]:
    """Backfill before quote capture, then freeze completed candle features with quotes."""
    candle_changes = _collect_candles(client, session_factory, datetime.now(UTC))
    captured = client.capture()
    with session_factory() as db:
        features = load_candle_features(
            db,
            BASELINE_SYMBOLS,
            as_of=captured.captured_at,
            per_symbol_limit=12,
        )
    canonical_set = replace(captured, candle_features=features)
    with session_factory() as db:
        receipt = persist_quote_set(db, canonical_set)
    return receipt, candle_changes


def _schedule_once(session_factory: sessionmaker[Session], env: Mapping[str, str]) -> WorkerReport:
    live_enabled = (
        env.get("APP_MODE", "demo") == "live"
        and env.get("ENABLE_INFERENCE", "false").lower() == "true"
    )
    mock_enabled = (
        env.get("APP_MODE", "demo") == "demo"
        and env.get("ENABLE_MOCK_INFERENCE", "false").lower() == "true"
        and _mock_competitions_only(session_factory)
    )
    if not live_enabled and not mock_enabled:
        return WorkerReport("scheduler", "DISABLED", detail="live inference is disabled")
    created = _create_due_rounds(session_factory)
    try:
        claims = tuple(
            claim
            for _ in range(_MAX_PARALLEL_DISPATCH)
            if (claim := _claim_one(session_factory)) is not None
        )
        if not claims:
            return WorkerReport("scheduler", "IDLE", handled=created, detail="no dispatchable job")
        completed = 0
        with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_DISPATCH) as pool:
            futures = {
                pool.submit(_dispatch_claim, session_factory, claim, env): claim for claim in claims
            }
            for future in as_completed(futures):
                claim = futures[future]
                try:
                    completion = future.result()
                except Exception as exc:
                    LOGGER.error("provider dispatch failed error_class=%s", type(exc).__name__)
                    continue
                if completion is None:
                    continue
                with session_factory() as db:
                    apply_invocation_result(db, claim.job_id, claim.fence, completion)
                completed += 1
        return WorkerReport(
            "scheduler",
            "READY" if completed else "IDLE",
            handled=created + completed,
            detail=f"{completed} inference results recorded",
        )
    except ProviderError as exc:
        LOGGER.warning("provider dispatch failed code=%s", exc.code)
        return WorkerReport("scheduler", "ERROR", handled=created, detail=exc.code)
    except Exception as exc:
        LOGGER.error("scheduler cycle failed error_class=%s", type(exc).__name__)
        return WorkerReport("scheduler", "ERROR", handled=created, detail="SCHEDULER_FAILED")


def _create_due_rounds(session_factory: sessionmaker[Session]) -> int:
    created = 0
    with session_factory() as db:
        with db.begin():
            now = _db_now(db)
            competitions = db.scalars(
                select(Competition)
                .where(Competition.state == "RUNNING", Competition.kill_switch.is_(False))
                .order_by(Competition.id)
                .with_for_update()
            ).all()
            for competition in competitions:
                if competition.started_at is None:
                    continue
                rules = _json_object(competition.rules_bytes)
                interval = _positive_int(rules.get("round_seconds", 180), "round interval", 86400)
                last_index = (
                    db.scalar(
                        select(func.max(DecisionRound.round_index)).where(
                            DecisionRound.competition_id == competition.id
                        )
                    )
                    or 0
                )
                next_index = last_index + 1
                logical_at = _normalize_timestamp(competition.started_at) + timedelta(
                    seconds=next_index * interval
                )
                if logical_at > now:
                    continue
                snapshot = db.scalar(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.captured_at <= logical_at)
                    .order_by(MarketSnapshot.captured_at.desc(), MarketSnapshot.id)
                    .limit(1)
                )
                agents = db.scalars(
                    select(AgentRun)
                    .where(AgentRun.competition_id == competition.id, AgentRun.status == "ACTIVE")
                    .order_by(AgentRun.manifest_order, AgentRun.id)
                ).all()
                if snapshot is None or not agents:
                    continue
                round_id = str(uuid.uuid4())
                deadline_at = logical_at + timedelta(seconds=120)
                db.add(
                    DecisionRound(
                        id=round_id,
                        competition_id=competition.id,
                        round_index=next_index,
                        logical_at=logical_at,
                        snapshot_id=snapshot.id,
                        deadline_at=deadline_at,
                    )
                )
                db.flush()
                for agent in agents:
                    missed = deadline_at <= now
                    db.add(
                        RoundAgentJob(
                            id=str(uuid.uuid4()),
                            round_id=round_id,
                            agent_run_id=agent.id,
                            state="TERMINAL" if missed else "PENDING",
                            terminal_result="PROVIDER_TIMEOUT" if missed else None,
                            error_code="NOT_DISPATCHED" if missed else None,
                            fence=0,
                        )
                    )
                created += 1
    return created


def _claim_one(session_factory: sessionmaker[Session]) -> ClaimedJob | None:
    with session_factory() as db:
        return claim_next_job(
            db,
            worker_name=f"scheduler-{_WORKER_INSTANCE[:8]}",
            lease_seconds=_CLAIM_LEASE_SECONDS,
        )


def _dispatch_claim(
    session_factory: sessionmaker[Session], claim: ClaimedJob, env: Mapping[str, str]
) -> InvocationCompletion | None:
    with session_factory() as db:
        competition = db.scalar(
            select(Competition)
            .where(Competition.id == claim.competition_id)
            .with_for_update(of=Competition)
        )
        job = db.scalar(
            select(RoundAgentJob)
            .where(RoundAgentJob.id == claim.job_id)
            .with_for_update()
        )
        agent = db.get(AgentRun, claim.agent_run_id)
        round_row = db.get(DecisionRound, claim.round_id)
        if competition is None or job is None or agent is None or round_row is None:
            raise RuntimeError("claimed job context is missing")
        prompt = db.get(PromptVersion, agent.prompt_version_id)
        snapshot = db.get(MarketSnapshot, claim.snapshot_id)
        account = db.scalar(
            select(AccountRow)
            .where(AccountRow.agent_run_id == agent.id)
            .with_for_update()
        )
        if prompt is None or snapshot is None or account is None:
            raise RuntimeError("claimed job data is incomplete")
        positions: tuple[PositionRow, ...] = tuple(
            db.scalars(
                select(PositionRow)
                .where(
                    PositionRow.account_id == account.id,
                    PositionRow.state == "OPEN",
                )
                .order_by(PositionRow.symbol)
            ).all()
        )
        snapshot_json = _json_object(snapshot.canonical_bytes)
        system_prompt = prompt.template_bytes
        user_prompt = canonical_json_bytes(
            {
                "schema": {
                    "proposals": [
                        "action",
                        "symbol",
                        "quantity",
                        "leverage",
                        "stop_loss",
                        "take_profit",
                        "confidence",
                        "invalidation",
                        "justification",
                    ]
                },
                "logical_at": _normalize_timestamp(round_row.logical_at).isoformat(),
                "snapshot": snapshot_json,
                "snapshot_sha256": snapshot.sha256,
                "own_account": {
                    "version": account.version,
                    "cash": str(account.cash),
                    "realized_pnl": str(account.realized_pnl),
                    "fees": str(account.fees),
                    "funding": str(account.funding),
                    "positions": [
                        {
                            "symbol": item.symbol,
                            "side": item.side,
                            "quantity": str(item.quantity),
                            "average_entry": str(item.average_entry),
                            "reserved_margin": str(item.reserved_margin),
                            "stop_loss": str(item.stop_loss)
                            if item.stop_loss is not None
                            else None,
                            "take_profit": str(item.take_profit)
                            if item.take_profit is not None
                            else None,
                        }
                        for item in positions
                    ],
                },
            }
        )
        settings = _json_object(agent.model_settings_bytes)
        competition = db.get(Competition, claim.competition_id)
        if competition is None:
            raise RuntimeError("claimed competition is missing")
        # Capture the secret from the explicitly frozen environment name before
        # committing a billable attempt. Credentials never enter evidence rows.
        key_name = agent.api_key_env
        api_key = (env.get(key_name) or "") if key_name and _ENV_NAME.fullmatch(key_name) else ""
    try:
        mock_mode = agent.provider == "MockLLMAdapter"
        if mock_mode:
            if (
                env.get("APP_MODE", "demo") != "demo"
                or env.get("ENABLE_MOCK_INFERENCE", "false").lower() != "true"
                or not competition.source_label.startswith("DEMO REPLAY")
            ):
                _terminalize_claim(session_factory, claim, "PROVIDER_NOT_CONFIGURED")
                return None
            config = ProviderConfig(
                provider="MockLLMAdapter",
                model=agent.model,
                endpoint=OPENAI_CHAT_URL,
                max_output_tokens=_positive_int(
                    settings.get("max_output_tokens", 512), "max output tokens", 2000
                ),
                temperature=_optional_decimal(settings, "temperature", "0"),
            )
            reservation = None
        else:
            config = _provider_config(agent.provider, agent.model, settings)
            if not api_key:
                _terminalize_claim(session_factory, claim, "PROVIDER_NOT_CONFIGURED")
                return None
        request_body = build_request_bytes(
            config,
            system_prompt_bytes=system_prompt,
            user_prompt_bytes=user_prompt,
        )
        configured_max_bytes = settings.get("max_input_body_bytes", _MAX_REQUEST_BYTES)
        max_request_bytes = min(
            _MAX_REQUEST_BYTES,
            _positive_int(configured_max_bytes, "max input body bytes", _MAX_REQUEST_BYTES),
        )
        if len(request_body) > max_request_bytes:
            _terminalize_claim(session_factory, claim, "BUDGET_EXCEEDED")
            return None
        if not mock_mode:
            reservation = _worst_case_reservation(config, request_body)
            max_cost = _required_decimal(settings, "max_cost_per_request_usd")
            if reservation > max_cost:
                _terminalize_claim(session_factory, claim, "BUDGET_EXCEEDED")
                return None
    except (ProviderError, ValueError) as exc:
        source_code = exc.code if isinstance(exc, ProviderError) else "PROVIDER_SETTINGS_INVALID"
        code = (
            "BUDGET_NOT_CONFIGURED"
            if "COST" in source_code or "BUDGET" in source_code
            else "PROVIDER_NOT_CONFIGURED"
        )
        _terminalize_claim(session_factory, claim, code)
        LOGGER.warning("provider dispatch skipped code=%s", code)
        return None
    prepared = _prepare_dispatch(
        session_factory, claim, config, request_body, reservation
    )
    if prepared is None:
        return None
    if mock_mode:
        return _mock_completion(agent, round_row)
    session_id = hashlib.sha256(
        f"arena-conversation:{claim.competition_id}:{claim.agent_run_id}".encode()
    ).hexdigest()[:32]
    with OpenAICompatibleProvider(config, api_key=api_key, session_id=session_id) as provider:
        try:
            result = provider.invoke(request_bytes=request_body)
            return _completion(result, settings)
        except ProviderError as exc:
            metadata: dict[str, str | int] = {
                "adapter": settings.get("adapter", "openai_chat")
            }
            if exc.status_code is not None:
                metadata["status_code"] = exc.status_code
            return InvocationCompletion(
                output_bytes=b"",
                error_code=exc.code,
                public_metadata=metadata,
            )


def _prepare_dispatch(
    session_factory: sessionmaker[Session],
    claim: ClaimedJob,
    config: ProviderConfig,
    request_body: bytes,
    reservation: Decimal | None,
) -> PreparedDispatch | None:
    with session_factory() as db:
        return prepare_invocation_dispatch(
            db,
            job_id=claim.job_id,
            fence=claim.fence,
            provider=config.provider,
            model=config.model,
            prompt_bytes=request_body,
            reservation_amount=reservation,
            public_parameters={
                **config.public_parameters,
                **(
                    {"cost_reservation_usd": format(reservation, "f")}
                    if reservation is not None
                    else {"offline_fixture": True}
                ),
            },
        )


def _mock_completion(agent: AgentRun, round_row: DecisionRound) -> InvocationCompletion:
    if round_row.round_index == 1:
        action = "OPEN_LONG" if agent.manifest_order == 0 else "OPEN_SHORT"
        symbol = "BTC" if agent.manifest_order == 0 else "ETH"
        quantity = "0.01" if symbol == "BTC" else "0.1"
    else:
        action, symbol, quantity = "HOLD", "BTC", "0"
    output = (
        "{\"proposals\":[{"
        f'\"action\":\"{action}\",\"symbol\":\"{symbol}\",'
        f'\"quantity\":{quantity},\"leverage\":2,'
        '\"stop_loss\":null,\"take_profit\":null,\"confidence\":0.5,'
        '\"invalidation\":\"The supplied market evidence changes.\",'
        '\"justification\":\"Deterministic offline fixture response.\"}]}'
    ).encode()
    return InvocationCompletion(
        output_bytes=output,
        public_metadata={"adapter": "mock", "finish_reason": "fixture"},
    )


def _completion(result: ProviderResult, settings: dict[str, Any]) -> InvocationCompletion:
    estimated = result.estimated_cost
    if estimated is not None and estimated > Decimal(str(settings["max_cost_per_request_usd"])):
        return InvocationCompletion(
            output_bytes=result.output_bytes,
            usage=result.usage,
            latency_ms=result.latency_ms,
            estimated_cost_usd=estimated,
            error_code="PROVIDER_COST_LIMIT_EXCEEDED",
            public_metadata={"adapter": settings.get("adapter", "openai_chat")},
        )
    return InvocationCompletion(
        output_bytes=result.output_bytes,
        usage=result.usage,
        latency_ms=result.latency_ms,
        estimated_cost_usd=estimated,
        public_metadata={"adapter": settings.get("adapter", "openai_chat")},
    )


def _worst_case_reservation(config: ProviderConfig, request_body: bytes) -> Decimal:
    """Reserve for every request byte as a possible input token plus full output cap."""
    if config.input_cost_per_million is None or config.output_cost_per_million is None:
        raise ProviderError("PROVIDER_COST_UNCONFIGURED")
    input_tokens = len(request_body)
    output_tokens = config.max_output_tokens
    amount = (
        Decimal(input_tokens) * config.input_cost_per_million
        + Decimal(output_tokens) * config.output_cost_per_million
    ) / Decimal(1_000_000)
    if not amount.is_finite() or amount <= 0:
        raise ProviderError("PROVIDER_BUDGET_UNCONFIGURED")
    return amount


def _terminalize_claim(
    session_factory: sessionmaker[Session], claim: ClaimedJob, error_code: str
) -> None:
    with session_factory() as db:
        terminalize_undispatched(
            db,
            job_id=claim.job_id,
            fence=claim.fence,
            error_code=error_code,
        )


def _provider_config(provider: str, model: str, settings: dict[str, Any]) -> ProviderConfig:
    adapter = settings.get("adapter")
    endpoint = _ADAPTER_ENDPOINTS.get(adapter) if isinstance(adapter, str) else None
    if endpoint is None:
        raise ProviderError("PROVIDER_ADAPTER_NOT_APPROVED")
    input_rate = _required_decimal(settings, "input_cost_per_million_usd")
    output_rate = _required_decimal(settings, "output_cost_per_million_usd")
    if input_rate <= 0 or output_rate <= 0:
        raise ProviderError("PROVIDER_COST_UNCONFIGURED")
    _required_decimal(settings, "max_cost_per_request_usd")
    return ProviderConfig(
        provider=provider,
        model=model,
        endpoint=endpoint,
        max_output_tokens=_positive_int(
            settings.get("max_output_tokens", 512), "max output tokens", 2000
        ),
        temperature=_optional_decimal(settings, "temperature", "0"),
        input_cost_per_million=input_rate,
        output_cost_per_million=output_rate,
    )


def _execute_once(session_factory: sessionmaker[Session], env: Mapping[str, str]) -> WorkerReport:
    live_enabled = (
        env.get("APP_MODE", "demo") == "live"
        and env.get("ENABLE_INFERENCE", "false").lower() == "true"
    )
    mock_enabled = (
        env.get("APP_MODE", "demo") == "demo"
        and env.get("ENABLE_MOCK_INFERENCE", "false").lower() == "true"
        and _mock_competitions_only(session_factory)
    )
    if not live_enabled and not mock_enabled:
        return WorkerReport("executor", "DISABLED", detail="live execution is disabled")
    with session_factory() as db:
        now = _db_now(db)
        latest_quote_set = db.scalar(
            select(QuoteSet.id).order_by(QuoteSet.captured_at.desc(), QuoteSet.id).limit(1)
        )
        statement = (
            select(RoundAgentJob.id, RoundAgentJob.fence, DecisionRound.execution_quote_set_id)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .join(Competition, Competition.id == DecisionRound.competition_id)
            .where(
                RoundAgentJob.state == "RESPONDED",
                DecisionRound.deadline_at <= now,
                Competition.state == "RUNNING",
                Competition.kill_switch.is_(False),
            )
            .order_by(DecisionRound.deadline_at, DecisionRound.round_index, RoundAgentJob.id)
            .limit(1)
        )
        if mock_enabled:
            statement = statement.where(Competition.source_label.startswith("DEMO REPLAY"))
        due = db.execute(statement).first()
        job_id = due[0] if due is not None else None
        fence = due[1] if due is not None else None
        pinned_quote_set = due[2] if due is not None else None
        execution_quote_set = pinned_quote_set or latest_quote_set
    exits = 0
    if latest_quote_set is not None:
        try:
            with session_factory() as db:
                cycle = run_protective_exit_cycle(db, quote_set_id=latest_quote_set)
            exits = cycle.protective_exits
        except Exception as exc:
            LOGGER.error("protective cycle failed error_class=%s", type(exc).__name__)
    if job_id is None:
        return WorkerReport(
            "executor",
            "READY" if exits else "IDLE",
            handled=exits,
            detail="protective exits checked" if exits else "no due response",
        )
    if execution_quote_set is None or fence is None:
        return WorkerReport("executor", "IDLE", detail="no fresh market evidence")
    try:
        with session_factory() as db:
            receipt: ExecutionReceipt = execute_job(db, job_id, fence, execution_quote_set)
        state = "READY" if receipt.state in {"SUCCESS", "RISK_REJECTED"} else receipt.state
        return WorkerReport("executor", state, handled=1, detail="one response executed")
    except Exception as exc:
        LOGGER.error("executor cycle failed error_class=%s", type(exc).__name__)
        return WorkerReport("executor", "ERROR", detail="EXECUTOR_FAILED")


def _heartbeat(session_factory: sessionmaker[Session], report: WorkerReport) -> None:
    with session_factory() as db:
        with db.begin():
            row = db.get(WorkerHeartbeat, (report.worker, _WORKER_INSTANCE))
            if row is None:
                row = WorkerHeartbeat(
                    worker_name=report.worker,
                    instance_id=_WORKER_INSTANCE,
                    state=report.state,
                    last_seen_at=datetime.now(UTC),
                    detail={"handled": report.handled, "status": report.detail[:120]},
                )
                db.add(row)
            else:
                row.state = report.state
                row.last_seen_at = datetime.now(UTC)
                row.detail = {"handled": report.handled, "status": report.detail[:120]}


def _mock_competitions_only(session_factory: sessionmaker[Session]) -> bool:
    with session_factory() as db:
        count = db.scalar(
            select(func.count())
            .select_from(Competition)
            .where(
                Competition.state == "RUNNING",
                ~Competition.source_label.startswith("DEMO REPLAY"),
            )
        )
    return count == 0


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("stored JSON is invalid") from None
    if not isinstance(value, dict):
        raise ValueError("stored JSON object is invalid")
    return value


def _required_decimal(data: dict[str, Any], key: str) -> Decimal:
    value = data.get(key)
    if value is None:
        raise ProviderError("PROVIDER_COST_UNCONFIGURED")
    try:
        result = Decimal(str(value))
    except Exception:
        raise ProviderError("PROVIDER_SETTINGS_INVALID") from None
    if not result.is_finite() or result < 0:
        raise ProviderError("PROVIDER_SETTINGS_INVALID")
    return result


def _optional_decimal(data: dict[str, Any], key: str, default: str) -> Decimal:
    try:
        result = Decimal(str(data.get(key, default)))
    except Exception:
        raise ProviderError("PROVIDER_SETTINGS_INVALID") from None
    if not result.is_finite() or result < 0:
        raise ProviderError("PROVIDER_SETTINGS_INVALID")
    return result


def _positive_int(value: object, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be from 1 through {maximum}")
    return value


def _db_now(db: Session) -> datetime:
    value = db.scalar(select(func.now()))
    if value is None:
        raise RuntimeError("database clock unavailable")
    return _normalize_timestamp(value)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(prog="arena-worker")
    parser.add_argument("worker", choices=("collector", "scheduler", "executor"))
    parser.add_argument("--once", action="store_true", help="run one worker cycle and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    while True:
        report = run_once(args.worker)
        print(
            json.dumps(
                {
                    "worker": report.worker,
                    "state": report.state,
                    "handled": report.handled,
                    "detail": report.detail,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if args.once:
            return
        time.sleep(_POLL_SECONDS)


if __name__ == "__main__":
    main()
