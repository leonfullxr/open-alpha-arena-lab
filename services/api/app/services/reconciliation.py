from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, localcontext

from app.db.models import (
    Account,
    AgentRun,
    Competition,
    LedgerJournal,
    LedgerPosting,
    Position,
)
from app.engine.finance import ZERO, money
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ReconciliationMismatch:
    account_id: str | None
    category: str
    expected: str
    actual: str
    delta: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    competition_id: str | None
    accounts_checked: int
    journals_checked: int
    mismatches: tuple[ReconciliationMismatch, ...]

    @property
    def balanced(self) -> bool:
        return not self.mismatches


def reconcile_ledger(db: Session, *, competition_id: str | None = None) -> ReconciliationReport:
    """Read a locked financial snapshot and compare account projections to the ledger."""
    with _consistent_snapshot(db):
        competition_query = select(Competition).order_by(Competition.id).with_for_update()
        if competition_id is not None:
            competition_query = competition_query.where(Competition.id == competition_id)
        competitions = list(db.scalars(competition_query))
        if competition_id is not None and not competitions:
            raise LookupError("competition not found")
        initial_by_competition = {
            competition.id: competition.initial_balance for competition in competitions
        }
        account_query = (
            select(Account, AgentRun.competition_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .order_by(AgentRun.competition_id, Account.id)
            .with_for_update(of=Account)
        )
        if competition_id is not None:
            account_query = account_query.where(AgentRun.competition_id == competition_id)
        account_rows = db.execute(account_query).all()
        account_ids = [account.id for account, _ in account_rows]
        journal_sum = func.coalesce(func.sum(LedgerPosting.amount), ZERO)
        journal_mismatches = (
            db.execute(
                select(
                    LedgerJournal.account_id,
                    LedgerJournal.event_key,
                    journal_sum,
                )
                .outerjoin(LedgerPosting, LedgerPosting.journal_id == LedgerJournal.id)
                .where(LedgerJournal.account_id.in_(account_ids))
                .group_by(LedgerJournal.id, LedgerJournal.account_id, LedgerJournal.event_key)
                .having(journal_sum != ZERO)
                .order_by(LedgerJournal.account_id, LedgerJournal.id)
            ).all()
            if account_ids
            else []
        )
        journals_checked = (
            (
                db.scalar(
                    select(func.count())
                    .select_from(LedgerJournal)
                    .where(LedgerJournal.account_id.in_(account_ids))
                )
                or 0
            )
            if account_ids
            else 0
        )
        bucket_sums = (
            {
                (account_id, bucket): amount
                for account_id, bucket, amount in db.execute(
                    select(
                        LedgerJournal.account_id,
                        LedgerPosting.bucket,
                        func.coalesce(func.sum(LedgerPosting.amount), ZERO),
                    )
                    .join(LedgerPosting, LedgerPosting.journal_id == LedgerJournal.id)
                    .where(LedgerJournal.account_id.in_(account_ids))
                    .group_by(LedgerJournal.account_id, LedgerPosting.bucket)
                ).all()
            }
            if account_ids
            else {}
        )
        open_margin_by_account = (
            {
                account_id: amount
                for account_id, amount in db.execute(
                    select(
                        Position.account_id,
                        func.coalesce(func.sum(Position.reserved_margin), ZERO),
                    )
                    .where(Position.account_id.in_(account_ids), Position.state == "OPEN")
                    .group_by(Position.account_id)
                ).all()
            }
            if account_ids
            else {}
        )

        mismatches: list[ReconciliationMismatch] = []
        for account_id, event_key, amount in journal_mismatches:
            actual = money(amount)
            if actual != ZERO:
                mismatches.append(
                    _mismatch(
                        account_id,
                        f"journal:{event_key}",
                        ZERO,
                        actual,
                    )
                )

        for account, comp_id in account_rows:
            ledger = {
                bucket: money(bucket_sums.get((account.id, bucket), ZERO))
                for bucket in (
                    "cash",
                    "realized_pnl",
                    "fees_expense",
                    "funding_income",
                    "reserved_margin",
                )
            }
            initial = initial_by_competition[comp_id]
            expected_values = {
                "cash": _money_sum(initial, ledger["cash"]),
                "realized_pnl": money(ledger["realized_pnl"].copy_negate()),
                "fees": money(ledger["fees_expense"]),
                "funding": money(ledger["funding_income"].copy_negate()),
                "reserved_margin": money(ledger["reserved_margin"]),
                "open_position_margin": money(open_margin_by_account.get(account.id, ZERO)),
            }
            actual_values = {
                "cash": money(account.cash),
                "realized_pnl": money(account.realized_pnl),
                "fees": money(account.fees),
                "funding": money(account.funding),
                "reserved_margin": money(account.reserved_margin),
                "open_position_margin": money(account.reserved_margin),
            }
            for category, expected in expected_values.items():
                actual = actual_values[category]
                with localcontext() as context:
                    context.prec = 60
                    mismatch = expected != actual
                if mismatch:
                    mismatches.append(_mismatch(account.id, category, expected, actual))
        return ReconciliationReport(
            competition_id=competition_id,
            accounts_checked=len(account_rows),
            journals_checked=journals_checked,
            mismatches=tuple(mismatches),
        )


def _mismatch(
    account_id: str | None, category: str, expected: Decimal, actual: Decimal
) -> ReconciliationMismatch:
    return ReconciliationMismatch(
        account_id=account_id,
        category=category,
        expected=str(expected),
        actual=str(actual),
        delta=str(_money_sum(actual, expected.copy_negate())),
    )


def _money_sum(*values: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 60
        return money(sum(values, ZERO))


@contextmanager
def _consistent_snapshot(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
    else:
        with db.begin():
            yield
