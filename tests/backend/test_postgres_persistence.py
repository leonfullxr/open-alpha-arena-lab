from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.db.models import (
    Account,
    AgentRun,
    DecisionRound,
    EquitySample,
    InvocationAttempt,
    InvocationResult,
    LedgerJournal,
    LedgerPosting,
    MarketSnapshot,
    RoundAgentJob,
)
from app.services.demo import seed_demo
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
DATABASE_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


def test_postgres_demo_hashes_immutability_balanced_ledger_and_process_restart() -> None:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as db:
        competition_id = seed_demo(db, 20)
        snapshots = list(
            db.scalars(
                select(MarketSnapshot)
                .join(DecisionRound, DecisionRound.snapshot_id == MarketSnapshot.id)
                .where(DecisionRound.competition_id == competition_id)
                .order_by(MarketSnapshot.id)
            )
        )
        attempts = list(
            db.scalars(
                select(InvocationAttempt)
                .join(RoundAgentJob, RoundAgentJob.id == InvocationAttempt.job_id)
                .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
                .where(DecisionRound.competition_id == competition_id)
                .order_by(InvocationAttempt.id)
            )
        )
        results = list(
            db.scalars(
                select(InvocationResult)
                .join(InvocationAttempt, InvocationAttempt.id == InvocationResult.attempt_id)
                .join(RoundAgentJob, RoundAgentJob.id == InvocationAttempt.job_id)
                .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
                .where(DecisionRound.competition_id == competition_id)
                .order_by(InvocationResult.id)
            )
        )
        assert len(snapshots) == 20
        assert len(attempts) == len(results) == 120
        assert all(
            hashlib.sha256(row.canonical_bytes).hexdigest() == row.sha256 for row in snapshots
        )
        assert all(
            hashlib.sha256(row.prompt_bytes).hexdigest() == row.prompt_sha256 for row in attempts
        )
        assert all(
            hashlib.sha256(row.output_bytes).hexdigest() == row.output_sha256 for row in results
        )
        account_rows = list(
            db.execute(
                select(Account, AgentRun)
                .join(AgentRun, AgentRun.id == Account.agent_run_id)
                .where(AgentRun.competition_id == competition_id)
                .order_by(AgentRun.manifest_order)
            )
        )
        assert [agent.name for _, agent in account_rows] == [
            "Atlas",
            "Vector",
            "Grok (simulated)",
            "Gemini (simulated)",
            "Claude (simulated)",
            "Codex (simulated)",
        ]
        accounts = [account for account, _ in account_rows]
        initial_samples = db.scalar(
            select(func.count()).select_from(EquitySample).where(EquitySample.round_index == 0)
        )
        assert initial_samples == 6
        assert all(str(row.cash) != "10000.000000000000000000" for row in accounts)
        snapshot_id, original_hash = snapshots[0].id, snapshots[0].sha256
        account_id = accounts[0].id

        nested = db.begin_nested()
        with pytest.raises(DBAPIError):
            db.execute(
                text("UPDATE market_snapshots SET sha256 = :bad WHERE id = :snapshot_id"),
                {"bad": "0" * 64, "snapshot_id": snapshot_id},
            )
            db.flush()
        nested.rollback()
        db.rollback()
        assert db.get(MarketSnapshot, snapshot_id).sha256 == original_hash

        nested = db.begin_nested()
        journal_id = "integration-unbalanced-journal"
        db.add(LedgerJournal(id=journal_id, account_id=account_id, event_key=journal_id))
        db.flush()
        db.add(
            LedgerPosting(
                id="integration-unbalanced-posting",
                journal_id=journal_id,
                bucket="cash",
                amount=1,
            )
        )
        db.flush()
        with pytest.raises(DBAPIError, match="unbalanced"):
            db.execute(text("SET CONSTRAINTS ledger_journal_must_balance IMMEDIATE"))
        nested.rollback()
        db.rollback()

        equity_count = (
            select(func.count())
            .select_from(EquitySample)
            .join(Account, Account.id == EquitySample.account_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .where(AgentRun.competition_id == competition_id)
        )
        result_count = (
            select(func.count())
            .select_from(InvocationResult)
            .join(InvocationAttempt, InvocationAttempt.id == InvocationResult.attempt_id)
            .join(RoundAgentJob, RoundAgentJob.id == InvocationAttempt.job_id)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .where(DecisionRound.competition_id == competition_id)
        )
        counts_before = (db.scalar(equity_count), db.scalar(result_count))

    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ, DATABASE_URL=DATABASE_URL, PYTHONPATH=str(repo / "services/api"))
    subprocess.run(
        [sys.executable, "-m", "app.cli", "run-demo", "--rounds", "20"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with Session(engine) as db:
        counts_after = (db.scalar(equity_count), db.scalar(result_count))
        assert counts_after == counts_before
    engine.dispose()
