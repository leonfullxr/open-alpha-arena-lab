from __future__ import annotations

import os

import pytest
from app.db.models import (
    Account,
    DomainEvent,
    EquitySample,
    Fill,
    LedgerJournal,
    Order,
    Position,
    RoundAgentJob,
    TradeProposal,
)
from app.services.execution import execute_job
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_execution import _setup
from test_execution_evidence import _migrated_schema

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
_PG_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None


@pytest.mark.skipif(_PG_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_execution_respects_caller_owned_transaction_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema, admin_engine, engine = _migrated_schema(monkeypatch)
    db: Session | None = None
    try:
        db, job_id, fence, quote_set_id, account_id = _setup(engine=engine)
        outer_transaction = db.begin()

        receipt = execute_job(db, job_id, fence, quote_set_id)

        assert receipt.state == "SUCCESS"
        assert db.scalar(select(func.count()).select_from(TradeProposal)) == 1
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.scalar(select(func.count()).select_from(Fill)) == 1
        assert db.scalar(select(func.count()).select_from(LedgerJournal)) == 1
        assert db.scalar(select(func.count()).select_from(Position)) == 1
        assert db.scalar(select(func.count()).select_from(EquitySample)) == 1
        assert outer_transaction.is_active

        outer_transaction.rollback()

        assert db.scalar(select(func.count()).select_from(TradeProposal)) == 0
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(func.count()).select_from(Fill)) == 0
        assert db.scalar(select(func.count()).select_from(LedgerJournal)) == 0
        assert db.scalar(select(func.count()).select_from(Position)) == 0
        assert db.scalar(select(func.count()).select_from(EquitySample)) == 0
        assert db.scalar(select(func.count()).select_from(DomainEvent)) == 0
        account = db.get(Account, account_id)
        assert account is not None
        assert account.cash == 10_000
        assert account.version == 0
        job = db.get(RoundAgentJob, job_id)
        assert job is not None
        assert job.state == "RESPONDED"
        assert job.terminal_result is None
    finally:
        if db is not None:
            db.close()
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
