from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Event

import pytest
from app.api.public import router as public_router
from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import (
    Account,
    AgentRun,
    Base,
    Competition,
    DomainEvent,
    FundingBoundaryTask,
    FundingPayment,
    LedgerJournal,
    LedgerPosting,
    MarketQuote,
    MarketSnapshot,
    Position,
    PromptVersion,
    QuoteSet,
)
from app.db.session import get_db
from app.services.funding import (
    claim_funding_oracle_capture,
    claim_funding_rate_poll,
    expire_missing_funding_rates,
    funding_status,
    list_due_funding_rate_polls,
    persist_oracle_capture,
    persist_rate_evidence,
    reschedule_funding_poll,
    settle_funding_boundary,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
PG_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")


def _id() -> str:
    return str(uuid.uuid4())


def _future_boundary() -> datetime:
    base = datetime.now(UTC) + timedelta(days=365 * 20)
    hour_offset = int(uuid.uuid4().hex[:12], 16) % (365 * 24 * 200)
    return base.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)


def _fixture(
    db: Session,
    *,
    boundary: datetime,
    rate_symbols: tuple[str, ...] = ("BTC", "ETH"),
    started_at: datetime | None = None,
    with_oracle: bool = True,
    close_btc_after: bool = True,
) -> tuple[str, str, str, str]:
    suffix = uuid.uuid4().hex
    competition_id, agent_id, prompt_id = _id(), _id(), _id()
    account_id, quote_set_id, snapshot_id = _id(), _id(), _id()
    rules = canonical_profile("alpha_2025_baseline")
    rules_bytes = canonical_json_bytes({**rules, "inference_budget_usd": "1"})
    db.add(
        Competition(
            id=competition_id,
            name=f"Funding fixture {suffix}",
            profile="alpha_2025_baseline",
            rules_bytes=rules_bytes,
            rules_sha256=sha256_hex(rules_bytes),
            initial_balance=Decimal("1000"),
            state="PAUSED",
            source_label="TEST FUNDING",
            started_at=started_at or boundary - timedelta(days=1),
            ended_at=None,
            event_seq=0,
        )
    )
    db.add(
        PromptVersion(
            id=prompt_id,
            name=f"funding-{suffix}",
            version=1,
            template_bytes=b"funding fixture",
            sha256=hashlib.sha256(b"funding fixture").hexdigest(),
        )
    )
    db.flush()
    db.add(
        AgentRun(
            id=agent_id,
            competition_id=competition_id,
            manifest_order=0,
            name="Funding Agent",
            provider="MockLLMAdapter",
            model="funding-test",
            model_settings_bytes=b"{}",
            settings_sha256="a" * 64,
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
            reserved_margin=Decimal("0"),
            halted=False,
            peak_equity=Decimal("1000"),
            daily_baseline_equity=Decimal("1000"),
            version=0,
        )
    )
    if with_oracle:
        db.add(
            QuoteSet(
                id=quote_set_id,
                source="hyperliquid",
                captured_at=boundary - timedelta(seconds=5),
                complete=True,
                max_age_ms=5_000,
                skew_ms=0,
            )
        )
        db.flush()
        payload = {
            "source": "hyperliquid",
            "test_fixture": suffix,
            "quotes": {
                symbol: {"oracle_px": str(price)}
                for symbol, price in (("BTC", 100), ("ETH", 50))
            },
        }
        raw_snapshot = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        db.add(
            MarketSnapshot(
                id=snapshot_id,
                canonical_bytes=raw_snapshot,
                sha256=hashlib.sha256(raw_snapshot).hexdigest(),
                source_label="hyperliquid",
                captured_at=boundary - timedelta(seconds=5),
                quote_set_id=quote_set_id,
            )
        )
        db.add_all(
            [
                MarketQuote(
                    quote_set_id=quote_set_id,
                    symbol=symbol,
                    bid=price - Decimal("1"),
                    ask=price + Decimal("1"),
                    mark=price,
                    funding_rate=None,
                    open_interest=None,
                    oracle_px=price,
                    source_at=boundary - timedelta(seconds=5),
                    received_at=boundary - timedelta(seconds=5),
                    context_received_at=boundary - timedelta(seconds=5),
                    source_at_basis="fixture",
                )
                for symbol, price in (("BTC", Decimal("100")), ("ETH", Decimal("50")))
                if symbol in rate_symbols or symbol == "BTC"
            ]
        )
    db.add(
        Position(
            id=_id(),
            account_id=account_id,
            symbol="BTC",
            side="LONG",
            quantity=Decimal("1"),
            average_entry=Decimal("100"),
            reserved_margin=Decimal("20"),
            state="CLOSED" if close_btc_after else "OPEN",
            opened_at=boundary - timedelta(days=2),
            closed_at=boundary + timedelta(minutes=1) if close_btc_after else None,
        )
    )
    db.add(
        Position(
            id=_id(),
            account_id=account_id,
            symbol="ETH",
            side="SHORT",
            quantity=Decimal("2"),
            average_entry=Decimal("50"),
            reserved_margin=Decimal("20"),
            state="OPEN",
            opened_at=boundary - timedelta(days=2),
            closed_at=None,
        )
    )
    db.add(
        FundingBoundaryTask(
            boundary_at=boundary,
            status="CAPTURE_PENDING",
            expected_symbols=list(rate_symbols),
            deadline_at=boundary + timedelta(minutes=30),
        )
    )
    db.flush()
    return competition_id, account_id, quote_set_id, snapshot_id


def _record_rates(db: Session, boundary: datetime) -> None:
    millis = int(boundary.timestamp()) * 1000
    raw = json.dumps(
        [
            {
                "coin": "BTC",
                "fundingRate": "0.01",
                "time": millis,
                "provider_internal": "SECRET_CANARY",
            },
            {"coin": "ETH", "fundingRate": "0.02", "time": millis},
        ],
        separators=(",", ":"),
    ).encode()
    for symbol, rate in (("BTC", Decimal("0.01")), ("ETH", Decimal("0.02"))):
        assert persist_rate_evidence(
            db,
            boundary_at=boundary,
            symbol=symbol,
            rate=rate,
            history_event_at=boundary,
            raw_record_bytes=raw,
        )


def test_funding_boundary_survives_restart_and_replay_pays_closed_after_boundary_once() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    with Session(engine) as db:
        competition_id, account_id, quote_set_id, snapshot_id = _fixture(
            db, boundary=boundary
        )
        db.commit()
    with Session(engine) as db:
        capture = persist_oracle_capture(
            db,
            boundary_at=boundary,
            quote_set_id=quote_set_id,
            snapshot_id=snapshot_id,
            context_received_at=boundary - timedelta(seconds=5),
        )
        assert capture.status == "PENDING"
    with Session(engine) as db:
        waiting = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=2),
        )
        assert waiting.status == "PENDING"
        assert db.scalar(
            select(func.count())
            .select_from(FundingPayment)
            .where(FundingPayment.event_at == boundary)
        ) == 0
    with Session(engine) as db:
        _record_rates(db, boundary)
    raw = json.dumps(
        [
            {
                "coin": "BTC",
                "fundingRate": "0.01",
                "time": int(boundary.timestamp()) * 1000,
                "provider_internal": "SECRET_CANARY",
            },
            {
                "coin": "ETH",
                "fundingRate": "0.02",
                "time": int(boundary.timestamp()) * 1000,
            },
        ],
        separators=(",", ":"),
    ).encode()
    with Session(engine) as db:
        assert not persist_rate_evidence(
            db,
            boundary_at=boundary,
            symbol="BTC",
            rate=Decimal("0.01"),
            history_event_at=boundary,
            raw_record_bytes=raw,
        )
        with pytest.raises(ValueError):
            persist_rate_evidence(
                db,
                boundary_at=boundary,
                symbol="BTC",
                rate=Decimal("0.03"),
                history_event_at=boundary,
                raw_record_bytes=raw,
            )
    with Session(engine) as db:
        receipt = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=2),
        )
        assert receipt.status == "SETTLED" and receipt.paid == 2 and receipt.skipped == 0
        account = db.get(Account, account_id)
        assert account is not None
        assert account.cash == Decimal("1001.000000000000000000")
        assert account.funding == Decimal("1.000000000000000000")
        payments = db.scalars(
            select(FundingPayment).where(FundingPayment.event_at == boundary)
        ).all()
        assert len(payments) == 2
        assert {payment.amount for payment in payments} == {
            Decimal("-1.000000000000000000"),
            Decimal("2.000000000000000000"),
        }
        journal = db.scalar(
            select(LedgerJournal).where(
                LedgerJournal.event_key == f"funding:{account_id}:{boundary.isoformat()}"
            )
        )
        assert journal is not None
        postings = db.scalars(
            select(LedgerPosting).where(LedgerPosting.journal_id == journal.id)
        ).all()
        assert sum((posting.amount for posting in postings), Decimal("0")) == 0
    with Session(engine) as db:
        replay = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=3),
        )
        assert replay.paid == replay.skipped == replay.pending == 0
        assert db.scalar(
            select(func.count()).select_from(FundingPayment).where(
                FundingPayment.event_at == boundary
            )
        ) == 2
        assert db.scalar(
            select(func.count()).select_from(DomainEvent).where(
                DomainEvent.competition_id == competition_id
            )
        ) == 1
    engine.dispose()


def test_funding_late_history_stays_pending_then_records_skipped_not_zero() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    with Session(engine) as db:
        competition_id, _, quote_set_id, snapshot_id = _fixture(db, boundary=boundary)
        db.commit()
        persist_oracle_capture(
            db,
            boundary_at=boundary,
            quote_set_id=quote_set_id,
            snapshot_id=snapshot_id,
                context_received_at=boundary - timedelta(seconds=5),
        )
        waiting = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=20),
        )
        assert waiting.status == "PENDING"
        assert db.scalar(
            select(func.count())
            .select_from(FundingPayment)
            .where(FundingPayment.event_at == boundary)
        ) == 0
        assert expire_missing_funding_rates(
            db, boundary_at=boundary, at=boundary + timedelta(minutes=31)
        ) == 2
        skipped = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=31),
        )
        assert skipped.status == "SETTLED" and skipped.skipped == 2
        payments = db.scalars(
            select(FundingPayment).where(FundingPayment.event_at == boundary)
        ).all()
        assert len(payments) == 2
        assert {payment.status for payment in payments} == {"SKIPPED"}
        assert {payment.reason for payment in payments} == {"rate_unavailable"}
        assert all(payment.amount is None for payment in payments)
    engine.dispose()


def test_settlement_expires_missing_rates_from_database_clock() -> None:
    assert PG_URL is not None
    schema = f"funding_clock_{uuid.uuid4().hex}"
    admin_engine = create_engine(PG_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        PG_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    boundary = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    try:
        with Session(engine) as db:
            competition_id, _, quote_set_id, snapshot_id = _fixture(db, boundary=boundary)
            db.commit()
        with Session(engine) as db:
            capture = persist_oracle_capture(
                db,
                boundary_at=boundary,
                quote_set_id=quote_set_id,
                snapshot_id=snapshot_id,
                context_received_at=boundary - timedelta(seconds=5),
            )
            assert capture.status == "PENDING"
            receipt = settle_funding_boundary(
                db, competition_id=competition_id, boundary_at=boundary
            )
            assert receipt.status == "SETTLED" and receipt.skipped == 2
            assert receipt.pending == 0
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_history_rate_accepts_millisecond_offset_through_five_seconds() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    event_at = boundary + timedelta(milliseconds=54)
    millis = int(boundary.timestamp()) * 1000 + 54
    raw = json.dumps({"coin": "BTC", "fundingRate": "0.0000026465", "time": millis}).encode()
    with Session(engine) as db:
        _fixture(db, boundary=boundary)
        task = db.get(FundingBoundaryTask, boundary)
        assert task is not None
        task.status = "PENDING"
        assert persist_rate_evidence(
            db,
            boundary_at=boundary,
            symbol="BTC",
            rate=Decimal("0.0000026465"),
            history_event_at=event_at,
            raw_record_bytes=raw,
        )
        at_limit = boundary + timedelta(seconds=5)
        at_limit_raw = json.dumps(
            {
                "coin": "ETH",
                "fundingRate": "0.0000013267",
                "time": int(boundary.timestamp()) * 1000 + 5000,
            }
        ).encode()
        assert persist_rate_evidence(
            db,
            boundary_at=boundary,
            symbol="ETH",
            rate=Decimal("0.0000013267"),
            history_event_at=at_limit,
            raw_record_bytes=at_limit_raw,
        )
        outside = boundary + timedelta(seconds=5, milliseconds=1)
        outside_raw = json.dumps(
            {
                "coin": "ETH",
                "fundingRate": "0.0000013267",
                "time": int(boundary.timestamp()) * 1000 + 5001,
            }
        ).encode()
        with pytest.raises(ValueError, match="within five seconds"):
            persist_rate_evidence(
                db,
                boundary_at=boundary,
                symbol="ETH",
                rate=Decimal("0.0000013267"),
                history_event_at=outside,
                raw_record_bytes=outside_raw,
            )
    engine.dispose()


def test_settlement_waits_for_oracle_capture_transaction() -> None:
    assert PG_URL is not None
    schema = f"funding_settle_lock_{uuid.uuid4().hex}"
    admin_engine = create_engine(PG_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        PG_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    boundary = _future_boundary()
    locked = Event()
    allow_commit = Event()
    settle_started = Event()
    try:
        with Session(engine) as db:
            competition_id, _, _, _ = _fixture(db, boundary=boundary)
            db.commit()

        def capture_transaction() -> None:
            with Session(engine) as db:
                task = db.scalar(
                    select(FundingBoundaryTask)
                    .where(FundingBoundaryTask.boundary_at == boundary)
                    .with_for_update()
                )
                assert task is not None
                task.status = "PENDING"
                task.next_poll_at = boundary + timedelta(seconds=1)
                locked.set()
                assert allow_commit.wait(timeout=5)
                db.commit()

        def settle() -> str:
            assert locked.wait(timeout=5)
            with Session(engine) as db:
                settle_started.set()
                return settle_funding_boundary(
                    db,
                    competition_id=competition_id,
                    boundary_at=boundary,
                    at=boundary + timedelta(seconds=2),
                ).status

        with ThreadPoolExecutor(max_workers=2) as pool:
            capture_future = pool.submit(capture_transaction)
            settlement_future = pool.submit(settle)
            assert settle_started.wait(timeout=5)
            allow_commit.set()
            capture_future.result(timeout=5)
            assert settlement_future.result(timeout=5) == "PENDING"
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_concurrent_first_oracle_capture_claim_has_one_winner(monkeypatch) -> None:
    assert PG_URL is not None
    schema = f"funding_claim_{uuid.uuid4().hex}"
    admin_engine = create_engine(PG_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        PG_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    boundary = (datetime.now(UTC) + timedelta(hours=1)).replace(
        minute=0, second=0, microsecond=0
    )
    monkeypatch.setattr(
        "app.services.funding._database_now", lambda _db: boundary - timedelta(seconds=5)
    )
    barrier = Barrier(2)

    def claim(worker_name: str) -> bool:
        barrier.wait(timeout=5)
        with Session(engine) as db:
            return claim_funding_oracle_capture(
                db,
                boundary_at=boundary,
                symbols=("BTC", "ETH"),
                worker_name=worker_name,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ("collector-a", "collector-b")))
        assert sorted(results) == [False, True]
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_competition_start_after_boundary_is_not_funded() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    with Session(engine) as db:
        competition_id, _, quote_set_id, snapshot_id = _fixture(
            db, boundary=boundary, started_at=boundary + timedelta(seconds=1)
        )
        db.commit()
        persist_oracle_capture(
            db,
            boundary_at=boundary,
            quote_set_id=quote_set_id,
            snapshot_id=snapshot_id,
                context_received_at=boundary - timedelta(seconds=5),
        )
        _record_rates(db, boundary)
        receipt = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=1),
        )
        assert receipt.status == "OUTSIDE_COMPETITION"
        assert (
            db.scalar(
                select(func.count())
                .select_from(FundingPayment)
                .where(FundingPayment.event_at == boundary)
            )
            == 0
        )
    engine.dispose()


def test_funding_evidence_is_immutable_and_capture_claims_are_bounded() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    with Session(engine) as db:
        competition_id, _, _, _ = _fixture(db, boundary=boundary)
        db.commit()
        # This boundary is far in the future, so it is durable but not yet claimable.
        assert not claim_funding_oracle_capture(
            db, boundary_at=boundary, symbols=("BTC", "ETH"), worker_name="collector-a"
        )
        assert not claim_funding_rate_poll(
            db, boundary_at=boundary, worker_name="poller-a"
        )
        assert list_due_funding_rate_polls(db, now=boundary + timedelta(seconds=2)) == []
        assert not reschedule_funding_poll(
            db, boundary_at=boundary, next_poll_at=boundary + timedelta(seconds=10)
        )
        assert funding_status(db, boundary) is not None
        assert competition_id
    engine.dispose()


def test_public_funding_history_evidence_and_export_are_bounded_and_explicit() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    with Session(engine) as db:
        competition_id, _, quote_set_id, snapshot_id = _fixture(db, boundary=boundary)
        db.commit()
    with Session(engine) as db:
        persist_oracle_capture(
            db,
            boundary_at=boundary,
            quote_set_id=quote_set_id,
            snapshot_id=snapshot_id,
            context_received_at=boundary - timedelta(seconds=5),
        )
        _record_rates(db, boundary)
        receipt = settle_funding_boundary(
            db,
            competition_id=competition_id,
            boundary_at=boundary,
            at=boundary + timedelta(minutes=1),
        )
        assert receipt.paid == 2

    app = FastAPI()
    app.include_router(public_router, prefix="/api/v1/public")

    def test_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(app) as client:
            root = f"/api/v1/public/competitions/{competition_id}"
            first_page = client.get(f"{root}/funding?limit=1")
            assert first_page.status_code == 200
            page = first_page.json()
            assert page["total"] == 2 and len(page["items"]) == 1
            item = page["items"][0]
            assert item["status"] == "PAID"
            assert item["evidence_sha256"]
            assert "raw_record_bytes" not in item
            filtered = client.get(f"{root}/funding?symbol=BTC")
            assert filtered.status_code == 200
            assert filtered.json()["total"] == 1
            evidence_response = client.get(
                f"/api/v1/public/funding/evidence/{item['evidence_id']}"
            )
            assert evidence_response.status_code == 200
            artifact = evidence_response.json()
            exact_bytes = base64.b64decode(artifact["exact_record_base64"], validate=True)
            assert hashlib.sha256(exact_bytes).hexdigest() == artifact["sha256"]
            assert b"fundingRate" in exact_bytes
            assert b"test_fixture" not in exact_bytes
            assert b"SECRET_CANARY" not in exact_bytes
            exported = client.get(f"{root}/export?limit=1")
            assert exported.status_code == 200
            export_body = exported.json()
            assert export_body["exported_funding_payments"] == 1
            assert len(export_body["funding"]) == 1
            assert export_body["truncated"] is True
            assert client.get(f"{root}/funding?limit=201").status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_settlement_rolls_back_account_payment_journal_and_event_together() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    boundary = _future_boundary()
    with Session(engine) as db:
        competition_id, account_id, quote_set_id, snapshot_id = _fixture(
            db, boundary=boundary
        )
        db.add(
            LedgerJournal(
                id=_id(),
                account_id=account_id,
                event_key=f"funding:{account_id}:{boundary.isoformat()}",
            )
        )
        db.commit()
        persist_oracle_capture(
            db,
            boundary_at=boundary,
            quote_set_id=quote_set_id,
            snapshot_id=snapshot_id,
                context_received_at=boundary - timedelta(seconds=5),
        )
        _record_rates(db, boundary)
        before = db.get(Account, account_id)
        assert before is not None
        prior_cash = before.cash
        with pytest.raises(IntegrityError):
            settle_funding_boundary(
                db,
                competition_id=competition_id,
                boundary_at=boundary,
                at=boundary + timedelta(minutes=1),
            )
        db.rollback()
        after = db.get(Account, account_id)
        assert after is not None and after.cash == prior_cash
        assert db.scalar(
            select(func.count()).select_from(FundingPayment).where(
                FundingPayment.event_at == boundary
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DomainEvent).where(
                DomainEvent.competition_id == competition_id
            )
        ) == 0
    engine.dispose()
