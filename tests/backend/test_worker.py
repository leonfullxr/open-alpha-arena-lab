from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
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
from app.llm.inputs import InputEvidenceError, build_agent_request_bytes, build_user_input
from app.llm.providers import OPENAI_CHAT_URL, ProviderConfig
from app.llm.schema import ProposalOutputError, parse_proposal_output
from app.llm.smoke import SmokeRunError, _load_config, _validate_candle_warmup
from app.market.hyperliquid import HyperliquidClient
from app.market.indicators import INDICATOR_POLICY, INDICATOR_WARMUP_BARS
from app.market.persistence import persist_quote_set
from app.market.types import (
    BASELINE_SYMBOLS,
    CandleBar,
    InstrumentSpec,
    MarketQuote,
    MarketQuoteSet,
)
from app.services.invocation import ClaimedJob, InvocationCompletion
from app.worker import (
    _create_due_rounds,
    _provider_config,
    _schedule_once,
    _worst_case_reservation,
    build_agent_input,
    capture_market_snapshot,
    run_once,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
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


def test_scheduler_dispatches_all_six_baseline_agents_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    now = datetime.now(UTC)
    claims = iter(
        ClaimedJob(
            job_id=f"job-{index}",
            competition_id="competition",
            round_id="round",
            agent_run_id=f"agent-{index}",
            snapshot_id="snapshot",
            fence=1,
            lease_expires_at=now + timedelta(seconds=130),
        )
        for index in range(len(BASELINE_SYMBOLS))
    )
    all_started = Barrier(len(BASELINE_SYMBOLS))
    started: list[str] = []

    def dispatch(
        _factory: sessionmaker[Session],
        claim: ClaimedJob,
        _env: dict[str, str],
    ) -> InvocationCompletion:
        started.append(claim.agent_run_id)
        all_started.wait(timeout=3)
        return InvocationCompletion(output_bytes=b"{}")

    monkeypatch.setattr("app.worker._mock_competitions_only", lambda _factory: True)
    monkeypatch.setattr("app.worker._create_due_rounds", lambda _factory: 0)
    monkeypatch.setattr("app.worker._claim_one", lambda _factory: next(claims, None))
    monkeypatch.setattr("app.worker._dispatch_claim", dispatch)
    monkeypatch.setattr("app.worker.apply_invocation_result", lambda *_args: None)

    report = _schedule_once(
        factory,
        {"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"},
    )

    assert report.state == "READY"
    assert report.handled == len(BASELINE_SYMBOLS)
    assert len(started) == len(BASELINE_SYMBOLS)


def test_emitted_agent_input_contains_frozen_rules_and_parseable_public_schema() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    frozen_rules = canonical_profile("alpha_2025_baseline") | {"source": "test"}
    rules_bytes = canonical_json_bytes(frozen_rules)
    competition = Competition(
        id="input-competition",
        name="input-test",
        profile="alpha_2025_baseline",
        rules_bytes=rules_bytes,
        rules_sha256=sha256_hex(rules_bytes),
        initial_balance=Decimal("10000"),
        state="RUNNING",
        source_label="TEST",
        event_seq=0,
    )
    snapshot_bytes = canonical_json_bytes(
        {
            "schema_version": 1,
            "source": "mock-worker",
            "quotes": {"BTC": {"mark": "100"}},
            "candles": [],
            "indicator_policy": INDICATOR_POLICY,
            "indicator_warmup_bars": INDICATOR_WARMUP_BARS,
        }
    )
    snapshot = MarketSnapshot(
        id="input-snapshot",
        canonical_bytes=snapshot_bytes,
        sha256=sha256_hex(snapshot_bytes),
        source_label="TEST",
        captured_at=now,
        quote_set_id="input-quote-set",
    )
    account = Account(
        id="own-account",
        agent_run_id="own-agent",
        cash=Decimal("10000"),
        realized_pnl=Decimal("0"),
        fees=Decimal("0"),
        funding=Decimal("0"),
        reserved_margin=Decimal("0"),
        halted=False,
        version=0,
    )
    prompt = build_agent_input(
        logical_at=now,
        competition=competition,
        snapshot=snapshot,
        account=account,
        positions=(),
    )
    request = build_agent_request_bytes(
        ProviderConfig(provider="fixture", model="test-model", endpoint=OPENAI_CHAT_URL),
        system_prompt_bytes=b"frozen system instructions",
        user_prompt_bytes=prompt,
    )
    messages = json.loads(request)["messages"]
    assert messages[0]["content"] == "frozen system instructions"
    assert messages[1]["content"] == prompt.decode("utf-8")
    body = json.loads(messages[1]["content"])
    assert body["frozen_rules"] == frozen_rules
    assert body["frozen_rules_sha256"] == competition.rules_sha256
    assert body["snapshot_sha256"] == snapshot.sha256
    assert body["proposal_schema_version"] == frozen_rules["proposal_schema_version"]
    assert body["market_window_candles"] == frozen_rules["market_window_candles"]
    assert body["own_account"]["version"] == account.version
    schema = json.loads(body["proposal_schema_json"])
    assert schema["properties"]["proposals"]["minItems"] == 1
    assert set(schema["$defs"]["Proposal"]["properties"]) == {
        "action",
        "symbol",
        "quantity",
        "leverage",
        "stop_loss",
        "take_profit",
        "confidence",
        "invalidation",
        "justification",
    }
    parsed = parse_proposal_output(json.dumps(body["valid_example"]).encode())
    assert parsed.proposals[0].action.value == "HOLD"
    with pytest.raises(ProposalOutputError):
        parse_proposal_output(b'{"proposals":[]}')


def test_shared_input_rejects_snapshot_schema_mismatch() -> None:
    with pytest.raises(ValueError, match="schema"):
        build_user_input(
            logical_at=datetime.now(UTC),
            frozen_rules=canonical_profile("alpha_2025_baseline"),
            frozen_rules_sha256="frozen-rules-hash",
            snapshot={
                "schema_version": 2,
                "quotes": {},
                "candles": [],
                "indicator_policy": INDICATOR_POLICY,
                "indicator_warmup_bars": INDICATOR_WARMUP_BARS,
            },
            snapshot_sha256="snapshot-hash",
            own_account={"cash": "10000"},
        )


def test_shared_input_rejects_indicator_metadata_outside_frozen_rules() -> None:
    frozen_rules = canonical_profile("alpha_2025_baseline")
    with pytest.raises(ValueError, match="indicator policy"):
        build_user_input(
            logical_at=datetime.now(UTC),
            frozen_rules=frozen_rules,
            frozen_rules_sha256="frozen-rules-hash",
            snapshot={
                "schema_version": 1,
                "quotes": {},
                "candles": [],
                "indicator_policy": INDICATOR_POLICY,
                "indicator_warmup_bars": INDICATOR_WARMUP_BARS - 1,
            },
            snapshot_sha256="snapshot-hash",
            own_account={"cash": "10000"},
        )


def test_live_hyperliquid_input_requires_warmed_candles() -> None:
    with pytest.raises(InputEvidenceError) as error:
        build_user_input(
            logical_at=datetime.now(UTC),
            frozen_rules=canonical_profile("alpha_2025_baseline"),
            frozen_rules_sha256="frozen-rules-hash",
            snapshot={
                "schema_version": 1,
                "source": "hyperliquid",
                "quotes": {},
                "candles": [],
                "indicator_policy": INDICATOR_POLICY,
                "indicator_warmup_bars": INDICATOR_WARMUP_BARS,
                "candle_error": "market_candle_gap",
            },
            snapshot_sha256="snapshot-hash",
            own_account={"cash": "10000"},
        )
    assert error.value.code == "MARKET_INPUT_UNAVAILABLE"


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
            latest_complete = end_at.replace(second=0, microsecond=0)
            latest_complete -= timedelta(minutes=latest_complete.minute % 3)
            latest_closed_open = latest_complete - timedelta(minutes=3)
            first_open = latest_closed_open - timedelta(
                minutes=3 * (INDICATOR_WARMUP_BARS + 12 - 2)
            )
            bars = []
            for index in range(INDICATOR_WARMUP_BARS + 12 - 1):
                opened = first_open + timedelta(minutes=3 * index)
                if not start_at <= opened <= latest_closed_open:
                    continue
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
                source="mock-worker",
            )

    receipt, changes = capture_market_snapshot(CandleClient(), factory)
    assert changes == len(BASELINE_SYMBOLS) * (INDICATOR_WARMUP_BARS + 12 - 1)
    assert call_order[-1] == "quotes"
    assert call_order[:-1] == [f"candles:{symbol}" for symbol in BASELINE_SYMBOLS]
    second_receipt, second_changes = capture_market_snapshot(CandleClient(), factory)
    assert second_changes == 0
    assert second_receipt.snapshot_id != receipt.snapshot_id
    assert call_order.count("quotes") == 2
    assert sum(call.startswith("candles:") for call in call_order) == len(BASELINE_SYMBOLS)
    with factory() as db:
        snapshot = db.get(MarketSnapshot, receipt.snapshot_id)
        assert snapshot is not None
        payload = json.loads(snapshot.canonical_bytes)
        windows = payload["candles"]
        _validate_candle_warmup(payload, canonical_profile("alpha_2025_baseline"))
        assert len(windows) == len(BASELINE_SYMBOLS)
        assert all(len(window["bars"]) == 12 for window in windows)
        assert all(window["bars"][-1]["ema20"] is not None for window in windows)
        assert all(window["bars"][-1]["macd_signal"] is not None for window in windows)
        assert db.scalar(select(func.count()).select_from(Candle)) == len(BASELINE_SYMBOLS) * (
            INDICATOR_WARMUP_BARS + 12 - 1
        )


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
        source="mock-worker",
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


def test_dirty_ledger_prevents_provider_dispatch_and_records_no_attempt(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'dirty-ledger.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    source_at = now - timedelta(seconds=1)
    quote_set = MarketQuoteSet(
        source_at,
        tuple(
            MarketQuote(
                symbol=symbol,
                bid=Decimal("99"),
                ask=Decimal("101"),
                mark=Decimal("100"),
                funding_rate=Decimal("0"),
                open_interest=Decimal("10"),
                source_at=source_at,
                received_at=source_at,
                context_received_at=source_at,
            )
            for symbol in BASELINE_SYMBOLS
        ),
        tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
        source="mock-worker",
    )
    rules = canonical_profile("alpha_2025_baseline") | {
        "source": "DEMO REPLAY",
        "inference_budget_usd": "5",
    }
    rules_bytes = canonical_json_bytes(rules)
    with factory() as db:
        persist_quote_set(db, quote_set)
        db.add(
            Competition(
                id="dirty-ledger-competition",
                name="dirty-ledger-dispatch-gate",
                profile=rules["profile"],
                rules_bytes=rules_bytes,
                rules_sha256=sha256_hex(rules_bytes),
                initial_balance=Decimal("10000"),
                state="RUNNING",
                source_label="DEMO REPLAY · dirty ledger test",
                started_at=now - timedelta(seconds=181),
                event_seq=0,
            )
        )
        prompt = b"Use only your account and the shared market evidence."
        db.add(
            PromptVersion(
                id="dirty-ledger-prompt",
                name="dirty-ledger",
                version=1,
                template_bytes=prompt,
                sha256=sha256_hex(prompt),
            )
        )
        db.flush()
        settings = canonical_json_bytes({"max_output_tokens": 128})
        db.add(
            AgentRun(
                id="dirty-ledger-agent",
                competition_id="dirty-ledger-competition",
                manifest_order=0,
                name="offline-test-agent",
                provider="MockLLMAdapter",
                model="offline-v1",
                model_settings_bytes=settings,
                settings_sha256=sha256_hex(settings),
                prompt_version_id="dirty-ledger-prompt",
                status="ACTIVE",
            )
        )
        db.flush()
        db.add(
            Account(
                id="dirty-ledger-account",
                agent_run_id="dirty-ledger-agent",
                cash=Decimal("10001"),
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
                reserved_margin=Decimal("0"),
                halted=False,
                version=0,
            )
        )
        db.commit()

    report = run_once(
        "scheduler",
        session_factory=factory,
        environment={"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"},
    )

    assert report.state == "IDLE"
    with factory() as db:
        job = db.scalar(select(RoundAgentJob))
        assert job is not None and job.state == "TERMINAL"
        assert job.error_code == "NOT_DISPATCHED"
        assert db.scalar(select(func.count()).select_from(InvocationAttempt)) == 0
    engine.dispose()


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
        input_cost_per_million=Decimal("1"),
        output_cost_per_million=Decimal("3"),
    )
    assert _worst_case_reservation(config, b"x" * 80_000) == Decimal("0.083")


def test_live_smoke_config_is_fixed_to_two_approved_go_models(tmp_path: Path) -> None:
    config_path = Path(__file__).parents[2] / "configs/live-smoke.example.json"
    config = _load_config(config_path)
    assert config["max_rounds"] == 5
    assert config["max_input_body_bytes"] == 80_000
    assert config["input_rate"] == Decimal("1")
    assert config["output_rate"] == Decimal("3")
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


def _run_twenty_round_worker_lifecycle(
    tmp_path: Path,
    engine_builder: Callable[[str], Engine],
    *,
    after_restart: Callable[[], None] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    set_clock: Callable[[datetime], None] | None = None,
) -> None:
    database_path = tmp_path / "worker-restart.sqlite"

    def open_factory() -> tuple[sessionmaker[Session], Engine]:
        engine = engine_builder(str(database_path))
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine, expire_on_commit=False), engine

    factory, engine = open_factory()
    environment = {"APP_MODE": "demo", "ENABLE_MOCK_INFERENCE": "true"}
    now = clock().replace(microsecond=0)
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
        source="mock-worker",
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
        now = clock().replace(microsecond=0)
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
            source="mock-worker",
        )
        with factory() as db:
            persist_quote_set(db, round_quotes)
            existing_competition = db.get(Competition, "mock-worker-competition")
            assert existing_competition is not None
            existing_competition.started_at = logical - timedelta(seconds=180 * round_index)
            db.commit()

        while True:
            scheduled = run_once("scheduler", session_factory=factory, environment=environment)
            assert scheduled.state in {"READY", "IDLE"}
            with factory() as db:
                unresolved = db.scalar(
                    select(func.count())
                    .select_from(RoundAgentJob)
                    .where(RoundAgentJob.state.in_(("PENDING", "CLAIMED")))
                )
            if unresolved == 0:
                break
            assert scheduled.state == "READY"
        with factory() as db:
            round_row = db.scalar(
                select(DecisionRound).where(DecisionRound.round_index == round_index)
            )
            assert round_row is not None
            deadline_at = round_row.deadline_at
            if set_clock is None:
                round_row.deadline_at = datetime.now(UTC).replace(microsecond=0) - timedelta(
                    seconds=2
                )
                db.commit()

        if set_clock is not None:
            set_clock(deadline_at + timedelta(seconds=1))

        execution_at = clock().replace(microsecond=0)
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
            source="mock-worker",
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
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(InvocationResult)
                    .where(InvocationResult.attempt_id.in_([attempt.id for attempt in attempts]))
                )
                == 2
            )
        if round_index == 10:
            engine.dispose()
            factory, engine = open_factory()
            if after_restart is not None:
                after_restart()
        if set_clock is not None and round_index < 20:
            set_clock(now + timedelta(seconds=180))

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
        open_positions = db.scalars(select(Position).where(Position.state == "OPEN")).all()
        assert len(open_positions) == 2
    engine.dispose()


def test_offline_workers_complete_twenty_rounds_with_two_agents_across_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reconciliation import ReconciliationReport

    def sqlite_numeric_is_balanced(
        _db: Session, *, competition_id: str | None = None
    ) -> ReconciliationReport:
        return ReconciliationReport(competition_id, 0, 0, ())

    monkeypatch.setattr("app.worker._MAX_PARALLEL_DISPATCH", 1)
    monkeypatch.setattr("app.worker.reconcile_ledger", sqlite_numeric_is_balanced)
    monkeypatch.setattr("app.services.execution._jobs.reconcile_ledger", sqlite_numeric_is_balanced)
    _run_twenty_round_worker_lifecycle(tmp_path, lambda path: create_engine(f"sqlite:///{path}"))


_WORKER_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
_WORKER_PG_URL = (
    _WORKER_PG_URL if _WORKER_PG_URL and _WORKER_PG_URL.startswith("postgresql") else None
)


@pytest.mark.skipif(_WORKER_PG_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_postgres_workers_complete_twenty_rounds_after_process_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _WORKER_PG_URL is not None
    schema = f"arena_worker_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_WORKER_PG_URL, pool_pre_ping=True)
    engines: list[Engine] = []
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    isolated_url = make_url(_WORKER_PG_URL).set(
        drivername="postgresql+psycopg",
        query={"options": f"-csearch_path={schema},pg_catalog"},
    )
    migration_env = os.environ.copy()
    migration_env["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
    migration_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, ("services/api", migration_env.get("PYTHONPATH")))
    )
    migration = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "services/api/alembic.ini",
            "upgrade",
            "head",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=migration_env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert migration.returncode == 0, "isolated Alembic upgrade failed"

    clock_start = datetime.now(UTC).replace(microsecond=0)
    with admin.begin() as connection:
        connection.execute(
            text(f'CREATE TABLE "{schema}".test_clock (clock_at timestamptz NOT NULL)')
        )
        connection.execute(
            text(f'INSERT INTO "{schema}".test_clock(clock_at) VALUES (:clock_at)'),
            {"clock_at": clock_start},
        )
        connection.execute(
            text(
                f'''CREATE FUNCTION "{schema}".now() RETURNS timestamptz
                    LANGUAGE sql STABLE AS
                    'SELECT clock_at FROM "{schema}".test_clock LIMIT 1' '''
            )
        )

    def current_test_clock() -> datetime:
        with admin.connect() as connection:
            value = connection.scalar(text(f'SELECT clock_at FROM "{schema}".test_clock'))
        if not isinstance(value, datetime):
            raise AssertionError("isolated test clock is missing")
        return value

    def set_test_clock(value: datetime) -> None:
        with admin.begin() as connection:
            connection.execute(
                text(f'UPDATE "{schema}".test_clock SET clock_at = :clock_at'),
                {"clock_at": value},
            )

    def subprocess_restart_check() -> None:
        restart = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os\n"
                "from sqlalchemy import create_engine, text\n"
                "engine = create_engine(os.environ['DATABASE_URL'])\n"
                "with engine.connect() as connection:\n"
                "    print(connection.scalar(text('select count(*) from decision_rounds')))\n",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=migration_env,
            capture_output=True,
            check=False,
            text=True,
        )
        assert restart.returncode == 0, "isolated PostgreSQL restart check failed"
        assert restart.stdout.strip() == "10"

    def build_schema_engine(_ignored: str) -> Engine:
        engine = create_engine(isolated_url, pool_pre_ping=True)
        engines.append(engine)
        return engine

    try:
        _run_twenty_round_worker_lifecycle(
            tmp_path,
            build_schema_engine,
            after_restart=subprocess_restart_check,
            clock=current_test_clock,
            set_clock=set_test_clock,
        )
    finally:
        for engine in engines:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
