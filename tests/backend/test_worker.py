from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import (
    Account,
    AgentRun,
    Base,
    Candle,
    Competition,
    DecisionRound,
    DomainEvent,
    InvocationAttempt,
    InvocationResult,
    LedgerPosting,
    MarketSnapshot,
    Order,
    Position,
    PromptVersion,
    RoundAgentJob,
    WorkerHeartbeat,
)
from app.llm.providers import ProviderConfig
from app.llm.smoke import SmokeRunError, _load_config
from app.market.hyperliquid import HyperliquidClient
from app.market.persistence import persist_quote_set
from app.market.types import (
    BASELINE_SYMBOLS,
    CandleBar,
    InstrumentSpec,
    MarketQuote,
    MarketQuoteSet,
)
from app.worker import (
    _create_due_rounds,
    _provider_config,
    _worst_case_reservation,
    capture_market_snapshot,
    run_once,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_demo_worker_modes_never_construct_external_clients() -> None:
    factory = _factory()

    def forbidden_client() -> HyperliquidClient:
        raise AssertionError("offline collector constructed an external client")

    report = run_once(
        "collector",
        session_factory=factory,
        environment={"APP_MODE": "demo", "MARKET_PROVIDER": "hyperliquid"},
        market_client_factory=forbidden_client,
    )
    assert report.state == "DISABLED"
    with factory() as db:
        heartbeat = db.get(WorkerHeartbeat, ("collector", report.worker))
        assert heartbeat is None
        rows = db.scalars(select(WorkerHeartbeat)).all()
        assert len(rows) == 1
        assert rows[0].state == "DISABLED"

    scheduler = run_once(
        "scheduler",
        session_factory=factory,
        environment={"APP_MODE": "demo", "ENABLE_INFERENCE": "true"},
    )
    executor = run_once(
        "executor",
        session_factory=factory,
        environment={"APP_MODE": "demo", "ENABLE_INFERENCE": "true"},
    )
    assert scheduler.state == executor.state == "DISABLED"


def test_live_capture_backfills_before_quote_and_freezes_bounded_candle_window() -> None:
    factory = _factory()
    call_order: list[str] = []

    class CandleClient:
        def fetch_candles(
            self,
            symbol: str,
            *,
            start_at: datetime,
            end_at: datetime,
            interval: str = "3m",
        ) -> tuple[CandleBar, ...]:
            call_order.append(f"candles:{symbol}")
            assert interval == "3m" and start_at < end_at
            first_open = end_at - timedelta(minutes=3 * 40)
            bars = []
            for index in range(40):
                opened = first_open + timedelta(minutes=3 * index)
                price = Decimal("100") + Decimal(index)
                bars.append(
                    CandleBar(
                        symbol=symbol,
                        interval=interval,
                        open_at=opened,
                        close_at=opened + timedelta(minutes=3) - timedelta(milliseconds=1),
                        source_received_at=datetime.now(UTC),
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=Decimal("5"),
                    )
                )
            return tuple(bars)

        def capture(self) -> MarketQuoteSet:
            call_order.append("quotes")
            captured = datetime.now(UTC)
            return MarketQuoteSet(
                captured,
                tuple(
                    MarketQuote(
                        symbol=symbol,
                        bid=Decimal("99"),
                        ask=Decimal("101"),
                        mark=Decimal("100"),
                        funding_rate=Decimal("0"),
                        open_interest=Decimal("10"),
                        source_at=captured,
                        received_at=captured,
                        context_received_at=captured,
                    )
                    for symbol in BASELINE_SYMBOLS
                ),
                tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
            )

    receipt, changes = capture_market_snapshot(CandleClient(), factory)
    assert changes == 240
    assert call_order[-1] == "quotes"
    assert call_order[:-1] == [f"candles:{symbol}" for symbol in BASELINE_SYMBOLS]
    with factory() as db:
        snapshot = db.get(MarketSnapshot, receipt.snapshot_id)
        assert snapshot is not None
        payload = json.loads(snapshot.canonical_bytes)
        windows = payload["candles"]
        assert len(windows) == len(BASELINE_SYMBOLS)
        assert all(len(window["bars"]) == 12 for window in windows)
        assert all(window["bars"][-1]["ema20"] is not None for window in windows)
        assert all(window["bars"][-1]["macd_signal"] is not None for window in windows)
        assert db.scalar(select(func.count()).select_from(Candle)) == 240


def test_round_scheduler_creates_one_snapshot_and_manifest_ordered_jobs_once() -> None:
    factory = _factory()
    now = datetime.now(UTC).replace(microsecond=0)
    quote_set = MarketQuoteSet(
        now - timedelta(seconds=1),
        tuple(
            MarketQuote(
                symbol=symbol,
                bid=Decimal("99"),
                ask=Decimal("101"),
                mark=Decimal("100"),
                funding_rate=Decimal("0"),
                open_interest=Decimal("10"),
                source_at=now - timedelta(seconds=1),
                received_at=now - timedelta(seconds=1),
                context_received_at=now - timedelta(seconds=1),
            )
            for symbol in BASELINE_SYMBOLS
        ),
        tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
    )
    rules = canonical_profile("alpha_2025_baseline")
    with factory() as db:
        receipt = persist_quote_set(db, quote_set)
        competition = Competition(
            id="competition-1",
            name="live-test",
            profile="alpha_2025_baseline",
            rules_bytes=canonical_json_bytes(rules),
            rules_sha256=sha256_hex(canonical_json_bytes(rules)),
            initial_balance=Decimal("10000"),
            state="RUNNING",
            source_label="test",
            started_at=now - timedelta(seconds=181),
            event_seq=0,
        )
        db.add(competition)
        prompt = b"Use only the supplied inputs."
        db.add(
            PromptVersion(
                id="prompt-1",
                name="baseline",
                version=1,
                template_bytes=prompt,
                sha256=sha256_hex(prompt),
            )
        )
        db.flush()
        for index, agent_id in enumerate(("agent-b", "agent-a")):
            settings = canonical_json_bytes({"adapter": "fixture"})
            db.add(
                AgentRun(
                    id=agent_id,
                    competition_id=competition.id,
                    manifest_order=1 - index,
                    name=agent_id,
                    provider="fixture",
                    model="fixture-v1",
                    model_settings_bytes=settings,
                    settings_sha256=sha256_hex(settings),
                    prompt_version_id="prompt-1",
                    status="ACTIVE",
                )
            )
        db.commit()

    assert _create_due_rounds(factory) == 1
    assert _create_due_rounds(factory) == 0
    with factory() as db:
        rounds = db.scalars(select(DecisionRound)).all()
        jobs = db.scalars(select(RoundAgentJob).order_by(RoundAgentJob.agent_run_id)).all()
        assert len(rounds) == 1
        assert rounds[0].snapshot_id == receipt.snapshot_id
        assert rounds[0].round_index == 1
        assert len(jobs) == 2
        assert [item.agent_run_id for item in jobs] == ["agent-a", "agent-b"]
        assert all(item.state == "PENDING" for item in jobs)
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 1


def test_provider_config_requires_fixed_adapter_and_explicit_positive_costs() -> None:
    valid = {
        "adapter": "opencode_go",
        "max_output_tokens": 400,
        "input_cost_per_million_usd": "0.25",
        "output_cost_per_million_usd": "0.5",
        "max_cost_per_request_usd": "0.02",
    }
    config = _provider_config("opencode_go", "glm-5.3-flash", valid)
    assert config.endpoint == "https://opencode.ai/inference/go/v1/chat/completions"
    assert config.input_cost_per_million == Decimal("0.25")
    try:
        _provider_config("custom", "model", {**valid, "adapter": "http://127.0.0.1:8000"})
    except Exception as exc:
        assert str(exc) == "PROVIDER_ADAPTER_NOT_APPROVED"
    else:
        raise AssertionError("unapproved provider endpoint was accepted")
    try:
        _provider_config("openai", "model", {"adapter": "openai_chat"})
    except Exception as exc:
        assert str(exc) == "PROVIDER_COST_UNCONFIGURED"
    else:
        raise AssertionError("provider without explicit cost was accepted")


def test_reservation_uses_exact_body_byte_upper_bound_and_full_output_cap() -> None:
    config = ProviderConfig(
        provider="opencode_go",
        model="glm-5.3-flash",
        endpoint="https://opencode.ai/inference/go/v1/chat/completions",
        max_output_tokens=1000,
        input_cost_per_million=Decimal("10"),
        output_cost_per_million=Decimal("30"),
    )
    assert _worst_case_reservation(config, b"x" * 20_000) == Decimal("0.23")


def test_live_smoke_config_is_fixed_to_two_approved_go_models(tmp_path: Path) -> None:
    config_path = Path(__file__).parents[2] / "configs/live-smoke.example.json"
    config = _load_config(config_path)
    assert config["max_rounds"] == 5
    assert {item["model"] for item in config["models"]} == {
        "mimo-v2.6-flash",
        "glm-5.3-flash",
    }
    invalid_path = tmp_path / "invalid-smoke.json"
    invalid_path.write_text(
        config_path.read_text("utf-8").replace("mimo-v2.6-flash", "unapproved-model"),
        encoding="utf-8",
    )
    try:
        _load_config(invalid_path)
    except SmokeRunError as exc:
        assert exc.code == "SMOKE_CONFIG_INVALID"
    else:
        raise AssertionError("unapproved model was accepted in live smoke config")


def test_offline_workers_complete_twenty_rounds_with_two_agents_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "worker-restart.sqlite"

    def open_factory() -> tuple[sessionmaker[Session], Engine]:
        engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine, expire_on_commit=False), engine

    factory, engine = open_factory()
    environment = {"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"}
    now = datetime.now(UTC).replace(microsecond=0)
    logical = now - timedelta(seconds=2)
    first_snapshot_time = logical - timedelta(seconds=1)
    first_set = MarketQuoteSet(
        first_snapshot_time,
        tuple(
            MarketQuote(
                symbol=symbol,
                bid=Decimal("999"),
                ask=Decimal("1001"),
                mark=Decimal("1000"),
                funding_rate=Decimal("0"),
                open_interest=Decimal("10"),
                source_at=first_snapshot_time,
                received_at=first_snapshot_time,
                context_received_at=first_snapshot_time,
            )
            for symbol in BASELINE_SYMBOLS
        ),
        tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
    )
    rules = canonical_profile("alpha_2025_baseline") | {
        "source": "DEMO REPLAY",
        "inference_budget_usd": "5",
    }
    rules_bytes = canonical_json_bytes(rules)
    with factory() as db:
        persist_quote_set(db, first_set)
        competition = Competition(
            id="mock-worker-competition",
            name="twenty-round-worker-proof",
            profile=rules["profile"],
            rules_bytes=rules_bytes,
            rules_sha256=sha256_hex(rules_bytes),
            initial_balance=Decimal("10000"),
            state="RUNNING",
            source_label="DEMO REPLAY · offline worker proof",
            started_at=logical - timedelta(seconds=1),
            event_seq=0,
        )
        db.add(competition)
        prompt = b"Use only your account and the canonical shared snapshot."
        db.add(
            PromptVersion(
                id="mock-worker-prompt",
                name="offline-proof",
                version=1,
                template_bytes=prompt,
                sha256=sha256_hex(prompt),
            )
        )
        db.flush()
        for order, agent_id in enumerate(("mock-agent-a", "mock-agent-b")):
            settings = canonical_json_bytes({"max_output_tokens": 128})
            db.add(
                AgentRun(
                    id=agent_id,
                    competition_id=competition.id,
                    manifest_order=order,
                    name=agent_id,
                    provider="MockLLMAdapter",
                    model="offline-v1",
                    model_settings_bytes=settings,
                    settings_sha256=sha256_hex(settings),
                    prompt_version_id="mock-worker-prompt",
                    status="ACTIVE",
                )
            )
        db.flush()
        for order, agent_id in enumerate(("mock-agent-a", "mock-agent-b")):
            db.add(
                Account(
                    id=f"mock-account-{order}",
                    agent_run_id=agent_id,
                    cash=Decimal("10000"),
                    realized_pnl=Decimal("0"),
                    fees=Decimal("0"),
                    funding=Decimal("0"),
                    reserved_margin=Decimal("0"),
                    halted=False,
                    version=0,
                )
            )
        db.commit()

    for round_index in range(1, 21):
        now = datetime.now(UTC).replace(microsecond=0)
        logical = now - timedelta(seconds=2)
        source_at = logical - timedelta(seconds=1)
        round_quotes = MarketQuoteSet(
            source_at,
            tuple(
                MarketQuote(
                    symbol=symbol,
                    bid=Decimal("999"),
                    ask=Decimal("1001"),
                    mark=Decimal("1000"),
                    funding_rate=Decimal("0"),
                    open_interest=Decimal("10"),
                    source_at=source_at,
                    received_at=source_at,
                    context_received_at=source_at,
                )
                for symbol in BASELINE_SYMBOLS
            ),
            tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
        )
        with factory() as db:
            persist_quote_set(db, round_quotes)
            existing_competition = db.get(Competition, "mock-worker-competition")
            assert existing_competition is not None
            existing_competition.started_at = logical - timedelta(
                seconds=180 * round_index
            )
            db.commit()

        scheduled = run_once("scheduler", session_factory=factory, environment=environment)
        assert scheduled.state == "READY"
        with factory() as db:
            round_row = db.scalar(
                select(DecisionRound).where(DecisionRound.round_index == round_index)
            )
            assert round_row is not None
            round_row.deadline_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=2)
            db.commit()

        execution_at = datetime.now(UTC).replace(microsecond=0)
        execution_set = MarketQuoteSet(
            execution_at,
            tuple(
                MarketQuote(
                    symbol=symbol,
                    bid=Decimal("999"),
                    ask=Decimal("1001"),
                    mark=Decimal("1000"),
                    funding_rate=Decimal("0"),
                    open_interest=Decimal("10"),
                    source_at=execution_at,
                    received_at=execution_at,
                    context_received_at=execution_at,
                )
                for symbol in BASELINE_SYMBOLS
            ),
            tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
        )
        with factory() as db:
            persist_quote_set(db, execution_set)
        for _ in range(2):
            report = run_once("executor", session_factory=factory, environment=environment)
            assert report.state == "READY"

        with factory() as db:
            round_row = db.scalar(
                select(DecisionRound).where(DecisionRound.round_index == round_index)
            )
            assert round_row is not None
            assert round_row.execution_quote_set_id is not None
            jobs = db.scalars(
                select(RoundAgentJob).where(RoundAgentJob.round_id == round_row.id)
            ).all()
            assert len(jobs) == 2 and all(job.state == "TERMINAL" for job in jobs)
            attempts = db.scalars(
                select(InvocationAttempt).where(InvocationAttempt.job_id.in_([j.id for j in jobs]))
            ).all()
            assert len(attempts) == 2
            assert all(attempt.prompt_bytes for attempt in attempts)
            assert db.scalar(
                select(func.count()).select_from(InvocationResult).where(
                    InvocationResult.attempt_id.in_([attempt.id for attempt in attempts])
                )
            ) == 2
        if round_index == 10:
            engine.dispose()
            factory, engine = open_factory()

    with factory() as db:
        rounds = db.scalars(
            select(DecisionRound).where(DecisionRound.competition_id == "mock-worker-competition")
        ).all()
        jobs = db.scalars(
            select(RoundAgentJob)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .where(DecisionRound.competition_id == "mock-worker-competition")
        ).all()
        attempts = db.scalars(select(InvocationAttempt)).all()
        assert len(rounds) == 20
        assert len(jobs) == 40 and all(job.state == "TERMINAL" for job in jobs)
        assert len(attempts) == 40
        assert db.scalar(select(func.count()).select_from(InvocationResult)) == 40
        order_count = db.scalar(select(func.count()).select_from(Order))
        event_count = db.scalar(select(func.count()).select_from(DomainEvent))
        assert order_count is not None and order_count >= 2
        assert event_count is not None and event_count > 0
        postings = db.scalars(select(LedgerPosting)).all()
        assert sum((posting.amount for posting in postings), Decimal("0")) == Decimal("0")
        open_positions = db.scalars(
            select(Position).where(Position.state == "OPEN")
        ).all()
        assert len(open_positions) == 2
    engine.dispose()
