from __future__ import annotations

import os
import uuid

import pytest
from app.db.models import Account, AgentRun, Base, Position
from app.services.demo import seed_demo
from app.services.reconciliation import reconcile_ledger
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
PG_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")


def test_seeded_demo_ledger_reconciles_and_projection_drift_is_reported() -> None:
    assert PG_URL is not None
    schema = f"reconcile_{uuid.uuid4().hex}"
    admin_engine = create_engine(PG_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        PG_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            competition_id = seed_demo(db, 20)
            initial = reconcile_ledger(db, competition_id=competition_id)
            assert initial.balanced, initial.mismatches
            assert initial.accounts_checked == 6
            assert initial.journals_checked > 0

            account = db.scalar(
                select(Account)
                .join(AgentRun, AgentRun.id == Account.agent_run_id)
                .where(AgentRun.competition_id == competition_id)
                .order_by(Account.id)
            )
            assert account is not None
            position = Position(
                id=str(uuid.uuid4()),
                account_id=account.id,
                symbol="AUDIT",
                side="LONG",
                quantity=1,
                average_entry=1,
                reserved_margin=0,
                state="OPEN",
            )
            db.add(position)
            db.flush()
            account.cash += 1
            account.fees += 2
            account.reserved_margin += 3
            position.reserved_margin += 4

            drifted = reconcile_ledger(db, competition_id=competition_id)
            assert not drifted.balanced
            categories = {mismatch.category for mismatch in drifted.mismatches}
            assert {"cash", "fees", "reserved_margin", "open_position_margin"}.issubset(categories)
            assert all(mismatch.account_id == account.id for mismatch in drifted.mismatches)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
