from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import (
    Account,
    AgentRun,
    Base,
    Competition,
    FundingBoundaryTask,
    FundingPayment,
    FundingRateEvidence,
    LedgerJournal,
    MarketSnapshot,
    Position,
    PromptVersion,
    QuoteSet,
)
from app.db.models import (
    MarketQuote as MarketQuoteRow,
)
from app.market import funding as funding_runtime
from app.market.types import (
    BASELINE_SYMBOLS,
    FundingRateRecord,
    InstrumentSpec,
    MarketQuote,
    MarketQuoteSet,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _quote_set(context_at: datetime) -> MarketQuoteSet:
    return MarketQuoteSet(
        captured_at=context_at + timedelta(seconds=2),
        quotes=tuple(
            MarketQuote(
                symbol=symbol,
                bid=Decimal("99"),
                ask=Decimal("101"),
                mark=Decimal("100"),
                funding_rate=Decimal("0.01"),
                open_interest=Decimal("10"),
                source_at=context_at,
                received_at=context_at + timedelta(seconds=1),
                context_received_at=context_at,
                oracle_px=Decimal("98.5"),
            )
            for symbol in BASELINE_SYMBOLS
        ),
        instruments=tuple(InstrumentSpec(symbol, 4, 20) for symbol in BASELINE_SYMBOLS),
    )


def test_oracle_capture_uses_preboundary_context_and_persists_immutable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=1, seconds=-8
    )
    boundary = now + timedelta(seconds=8)
    quote_set = _quote_set(boundary - timedelta(seconds=3))
    claimed: list[datetime] = []
    receipts: list[tuple[str | None, str | None, datetime | None]] = []

    def claim(_db: Session, *, boundary_at: datetime, **_kwargs: object) -> bool:
        claimed.append(boundary_at)
        return True

    def pinned(
        _db: Session,
        *,
        quote_set_id: str | None,
        snapshot_id: str | None,
        context_received_at: datetime | None,
        **_kwargs: object,
    ) -> None:
        receipts.append((quote_set_id, snapshot_id, context_received_at))

    monkeypatch.setattr(funding_runtime, "claim_funding_oracle_capture", claim)
    monkeypatch.setattr(funding_runtime, "persist_oracle_capture", pinned)

    class Client:
        def capture(self) -> MarketQuoteSet:
            return quote_set

        def fetch_funding_history(
            self, symbol: str, *, start_at: datetime, end_at: datetime
        ) -> tuple[FundingRateRecord, ...]:
            return ()

    assert funding_runtime.capture_due_oracle(
        factory, Client(), now=now, worker_name="collector-test"
    )
    assert claimed == [boundary]
    assert len(receipts) == 1
    quote_set_id, snapshot_id, context_at = receipts[0]
    assert quote_set_id is not None and snapshot_id is not None
    assert context_at == boundary - timedelta(seconds=3)


def test_rate_poll_persists_actual_matching_hourly_record_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    now = datetime.now(UTC)
    boundary = now.replace(minute=0, second=0, microsecond=0)
    with factory() as db:
        db.add(
            FundingBoundaryTask(
                boundary_at=boundary,
                status="PENDING",
                expected_symbols=["BTC"],
                deadline_at=boundary + timedelta(minutes=30),
                next_poll_at=boundary + timedelta(seconds=1),
            )
        )
        db.commit()
    persisted: list[tuple[str, Decimal, datetime, bytes]] = []
    monkeypatch.setattr(
        funding_runtime,
        "list_due_funding_rate_polls",
        lambda _db, *, now, limit: [boundary],
    )
    monkeypatch.setattr(funding_runtime, "claim_funding_rate_poll", lambda *_args, **_kwargs: True)

    def persist(
        _db: Session,
        *,
        symbol: str,
        rate: Decimal,
        history_event_at: datetime,
        raw_record_bytes: bytes,
        **_kwargs: object,
    ) -> bool:
        persisted.append((symbol, rate, history_event_at, raw_record_bytes))
        return True

    monkeypatch.setattr(funding_runtime, "persist_rate_evidence", persist)
    monkeypatch.setattr(
        funding_runtime,
        "reschedule_funding_poll",
        lambda *_args, **_kwargs: True,
    )

    class Client:
        def capture(self) -> MarketQuoteSet:
            return _quote_set(boundary)

        def fetch_funding_history(
            self, symbol: str, *, start_at: datetime, end_at: datetime
        ) -> tuple[FundingRateRecord, ...]:
            assert symbol == "BTC"
            assert start_at == boundary - timedelta(hours=1)
            raw = json.dumps(
                {
                    "coin": "BTC",
                    "fundingRate": "0.0125",
                    "time": int(boundary.timestamp() * 1000),
                },
                separators=(",", ":"),
            ).encode()
            return (
                FundingRateRecord(
                    symbol="BTC",
                    rate=Decimal("0.99"),
                    event_at=boundary + timedelta(seconds=6),
                    raw_record_bytes=b"outside-jitter-window",
                ),
                FundingRateRecord(
                    symbol="BTC",
                    rate=Decimal("0.0125"),
                    event_at=boundary,
                    raw_record_bytes=raw,
                ),
            )

    count = funding_runtime.poll_due_rates(
        factory, Client(), now=now + timedelta(minutes=2), worker_name="collector-test"
    )
    assert count == 1
    assert persisted == [
        (
            "BTC",
            Decimal("0.0125"),
            boundary,
            json.dumps(
                {
                    "coin": "BTC",
                    "fundingRate": "0.0125",
                    "time": int(boundary.timestamp() * 1000),
                },
                separators=(",", ":"),
            ).encode(),
        )
    ]


def test_settlement_cycle_expires_stale_oracle_capture_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    now = datetime.now(UTC)
    stale_boundary = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    expired: list[datetime] = []
    monkeypatch.setattr(
        funding_runtime,
        "list_stale_funding_oracle_captures",
        lambda _db, *, now, limit: [stale_boundary],
    )
    def expire(_db: Session, *, boundary_at: datetime, at: datetime) -> bool:
        expired.append(boundary_at)
        return True

    monkeypatch.setattr(funding_runtime, "expire_stale_funding_oracle_capture", expire)

    paid, skipped = funding_runtime.settle_ready_boundaries(factory, now=now)

    assert (paid, skipped) == (0, 0)
    assert expired == [stale_boundary]


def test_ready_boundary_settles_once_through_worker_wrapper() -> None:
    factory = _session_factory()
    now = datetime.now(UTC)
    boundary = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    context_at = boundary - timedelta(seconds=5)
    quote_set_id = "funding-runtime-quote-set"
    snapshot_id = "funding-runtime-snapshot"
    competition_id = "funding-runtime-competition"
    prompt_id = "funding-runtime-prompt"
    agent_id = "funding-runtime-agent"
    account_id = "funding-runtime-account"
    position_id = "funding-runtime-position"
    rules = canonical_profile("alpha_2025_baseline") | {"inference_budget_usd": "1"}
    rules_bytes = canonical_json_bytes(rules)
    snapshot_bytes = canonical_json_bytes(
        {"source": "hyperliquid", "quotes": {"BTC": {"oracle_px": "100"}}}
    )
    raw_evidence = json.dumps(
        {
            "coin": "BTC",
            "fundingRate": "0.01",
            "time": int(boundary.timestamp() * 1000),
        },
        separators=(",", ":"),
    ).encode()
    with factory() as db:
        db.add(
            Competition(
                id=competition_id,
                name="funding-runtime-test",
                profile="alpha_2025_baseline",
                rules_bytes=rules_bytes,
                rules_sha256=sha256_hex(rules_bytes),
                initial_balance=Decimal("1000"),
                state="PAUSED",
                source_label="TEST FUNDING",
                started_at=boundary - timedelta(days=1),
                event_seq=0,
            )
        )
        db.add(
            PromptVersion(
                id=prompt_id,
                name="funding-runtime",
                version=1,
                template_bytes=b"funding fixture",
                sha256=sha256_hex(b"funding fixture"),
            )
        )
        db.flush()
        db.add(
            AgentRun(
                id=agent_id,
                competition_id=competition_id,
                manifest_order=0,
                name="funding-runtime-agent",
                provider="MockLLMAdapter",
                model="fixture",
                model_settings_bytes=b"{}",
                settings_sha256=sha256_hex(b"{}"),
                prompt_version_id=prompt_id,
                status="ACTIVE",
            )
        )
        db.flush()
        db.add(
            Account(
                id=account_id,
                agent_run_id=agent_id,
                cash=Decimal("1000"),
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
                reserved_margin=Decimal("20"),
                halted=False,
                version=0,
            )
        )
        db.add(
            QuoteSet(
                id=quote_set_id,
                source="hyperliquid",
                captured_at=context_at,
                complete=True,
                max_age_ms=5000,
                skew_ms=0,
            )
        )
        db.flush()
        db.add(
            MarketSnapshot(
                id=snapshot_id,
                canonical_bytes=snapshot_bytes,
                sha256=sha256_hex(snapshot_bytes),
                source_label="hyperliquid",
                captured_at=context_at,
                quote_set_id=quote_set_id,
            )
        )
        db.add(
            MarketQuoteRow(
                quote_set_id=quote_set_id,
                symbol="BTC",
                bid=Decimal("99"),
                ask=Decimal("101"),
                mark=Decimal("100"),
                funding_rate=None,
                open_interest=None,
                oracle_px=Decimal("100"),
                source_at=context_at,
                received_at=context_at,
                context_received_at=context_at,
                source_at_basis="fixture",
            )
        )
        db.add(
            Position(
                id=position_id,
                account_id=account_id,
                symbol="BTC",
                side="LONG",
                quantity=Decimal("1"),
                average_entry=Decimal("100"),
                reserved_margin=Decimal("20"),
                state="OPEN",
                opened_at=boundary - timedelta(days=1),
            )
        )
        db.add(
            FundingBoundaryTask(
                boundary_at=boundary,
                status="READY",
                expected_symbols=["BTC"],
                oracle_quote_set_id=quote_set_id,
                oracle_snapshot_id=snapshot_id,
                context_received_at=context_at,
                deadline_at=boundary + timedelta(minutes=30),
            )
        )
        for hours_ago in range(25, 74):
            old_boundary = boundary - timedelta(hours=hours_ago)
            db.add(
                FundingBoundaryTask(
                    boundary_at=old_boundary,
                    status="READY",
                    expected_symbols=["BTC"],
                    oracle_quote_set_id=quote_set_id,
                    oracle_snapshot_id=snapshot_id,
                    context_received_at=context_at,
                    deadline_at=old_boundary + timedelta(minutes=30),
                )
            )
        db.add(
            FundingRateEvidence(
                id="funding-runtime-evidence",
                symbol="BTC",
                boundary_at=boundary,
                status="READY",
                rate=Decimal("0.01"),
                history_event_at=boundary,
                raw_record_bytes=raw_evidence,
                sha256=hashlib.sha256(raw_evidence).hexdigest(),
            )
        )
        db.commit()

    first = funding_runtime.settle_ready_boundaries(factory, now=now)
    second = funding_runtime.settle_ready_boundaries(factory, now=now)
    assert first == (1, 0)
    assert second == (0, 0)
    with factory() as db:
        payment = db.scalar(select(FundingPayment).where(FundingPayment.position_id == position_id))
        assert payment is not None
        assert payment.status == "PAID" and payment.rate == Decimal("0.01")
        assert db.scalar(select(LedgerJournal).where(LedgerJournal.event_key.like("funding:%")))
        account = db.get(Account, account_id)
        assert account is not None and account.funding < Decimal("0")
