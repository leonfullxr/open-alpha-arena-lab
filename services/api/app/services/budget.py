from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation, localcontext

from app.core.config import get_settings
from app.db.models import Competition, DailyBudget, SpendReservation
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


class BudgetRejected(ValueError):
    """The frozen or global inference budget cannot admit another provider call."""


def parse_frozen_competition_budget(rules_bytes: bytes) -> Decimal | None:
    try:
        rules = json.loads(rules_bytes)
        raw = rules.get("inference_budget_usd") if isinstance(rules, dict) else None
        amount = Decimal(str(raw)) if raw is not None else None
    except (json.JSONDecodeError, UnicodeDecodeError, InvalidOperation, ValueError):
        return None
    if amount is None or not amount.is_finite() or amount <= 0:
        return None
    bounded = _bounded(amount, rounding=ROUND_FLOOR)
    return bounded if bounded > 0 else None


def reserve_provider_spend(
    db: Session,
    *,
    competition: Competition,
    job_id: str,
    amount_usd: Decimal,
    reserved_at: datetime,
) -> bool:
    """Reserve worst-case cost before dispatch, in the caller's DB transaction.

    The caller already holds the competition and job row locks. This function then locks
    the global daily row, so separate competitions cannot overspend the same daily cap.
    Reservations are append-only and remain charged after uncertain provider outcomes.
    """
    amount = _bounded(amount_usd)
    if amount <= 0:
        raise BudgetRejected("reservation must be positive")
    competition_cap = parse_frozen_competition_budget(competition.rules_bytes)
    if competition_cap is None or amount > competition_cap:
        return False

    day = _utc(reserved_at).date()
    global_cap = _bounded(get_settings().max_daily_llm_spend_usd, rounding=ROUND_FLOOR)
    # Dispatch is PostgreSQL-only in production. SQLite unit tests bypass live-provider
    # reservations through the explicit offline adapter path.
    if db.bind is None or db.bind.dialect.name != "postgresql":
        raise RuntimeError("provider spend reservations require PostgreSQL")
    db.execute(
        insert(DailyBudget)
        .values(budget_date=day, cap_usd=global_cap, reserved_usd=Decimal("0"))
        .on_conflict_do_nothing(index_elements=[DailyBudget.budget_date])
    )
    daily = db.scalar(select(DailyBudget).where(DailyBudget.budget_date == day).with_for_update())
    if daily is None:
        raise RuntimeError("daily budget row could not be created")

    if daily.reserved_usd + amount > min(daily.cap_usd, global_cap):
        return False
    competition_reserved = db.scalar(
        select(func.coalesce(func.sum(SpendReservation.amount_usd), 0)).where(
            SpendReservation.competition_id == competition.id,
        )
    )
    if competition_reserved is None:
        competition_reserved = Decimal("0")
    if competition_reserved + amount > competition_cap:
        return False

    daily.reserved_usd = _bounded(daily.reserved_usd + amount)
    db.add(
        SpendReservation(
            id=str(uuid.uuid4()),
            job_id=job_id,
            competition_id=competition.id,
            budget_date=day,
            amount_usd=amount,
            reserved_at=_utc(reserved_at),
        )
    )
    db.flush()
    return True


def _bounded(value: Decimal, *, rounding: str = ROUND_CEILING) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise BudgetRejected("reservation must be a finite non-negative Decimal")
    try:
        with localcontext() as context:
            context.prec = 60
            amount = value.quantize(Decimal("0.000000000000000001"), rounding=rounding)
    except InvalidOperation as exc:
        raise BudgetRejected("reservation exceeds numeric(38,18) range") from exc
    if abs(amount) >= Decimal("1e20"):
        raise BudgetRejected("reservation exceeds numeric(38,18) range")
    return amount


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
