from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Account,
    AgentRun,
    Competition,
    FundingBoundaryTask,
    FundingPayment,
)
from app.db.models import (
    Position as PositionRow,
)
from app.market.persistence import persist_quote_set
from app.market.types import BASELINE_SYMBOLS, FundingRateRecord, MarketQuoteSet
from app.services.funding import (
    claim_funding_oracle_capture,
    claim_funding_rate_poll,
    expire_missing_funding_rates,
    expire_stale_funding_oracle_capture,
    list_due_funding_rate_polls,
    list_stale_funding_oracle_captures,
    persist_oracle_capture,
    persist_rate_evidence,
    reschedule_funding_poll,
    settle_funding_boundary,
)

LOGGER = logging.getLogger("arena.market.funding")
_ORACLE_CAPTURE_SECONDS = 8
_FUNDING_HISTORY_MAX_OFFSET_SECONDS = 5
_POLL_INTERVAL_SECONDS = 30
_MAX_POLL_WORKERS = 6


class FundingHistoryClient(Protocol):
    def capture(self) -> MarketQuoteSet: ...

    def fetch_funding_history(
        self, symbol: str, *, start_at: datetime, end_at: datetime
    ) -> tuple[FundingRateRecord, ...]: ...


def capture_due_oracle(
    session_factory: sessionmaker[Session],
    client: FundingHistoryClient,
    *,
    now: datetime,
    worker_name: str,
) -> bool:
    """Pin one pre-boundary oracle snapshot; the network call is outside DB transactions."""
    now = _utc(now)
    floor = now.replace(minute=0, second=0, microsecond=0)
    upcoming = floor + timedelta(hours=1)
    boundary = (
        upcoming
        if timedelta(0) < upcoming - now <= timedelta(seconds=_ORACLE_CAPTURE_SECONDS)
        else floor
    )
    with session_factory() as db:
        with db.begin():
            claimed = claim_funding_oracle_capture(
                db,
                boundary_at=boundary,
                symbols=BASELINE_SYMBOLS,
                worker_name=worker_name,
                lease_seconds=30,
            )
    if not claimed:
        return False
    try:
        quote_set = client.capture()
    except Exception as exc:
        LOGGER.warning("funding oracle capture failed error_class=%s", type(exc).__name__)
        with session_factory() as db:
            with db.begin():
                persist_oracle_capture(
                    db,
                    boundary_at=boundary,
                    quote_set_id=None,
                    snapshot_id=None,
                    context_received_at=None,
                )
        return False
    with session_factory() as db:
        receipt = persist_quote_set(db, quote_set)
        context_received_at = _shared_context_time(quote_set)
        with db.begin():
            persist_oracle_capture(
                db,
                boundary_at=boundary,
                quote_set_id=receipt.quote_set_id,
                snapshot_id=receipt.snapshot_id,
                context_received_at=context_received_at,
            )
    return True


def poll_due_rates(
    session_factory: sessionmaker[Session],
    client: FundingHistoryClient,
    *,
    now: datetime,
    worker_name: str,
) -> int:
    """Fetch missing hourly rates with a durable per-boundary poll lease."""
    now = _utc(now)
    with session_factory() as db:
        expired = tuple(
            db.scalars(
                select(FundingBoundaryTask.boundary_at)
                .where(
                    FundingBoundaryTask.status == "PENDING",
                    FundingBoundaryTask.deadline_at < now,
                )
                .order_by(FundingBoundaryTask.boundary_at)
                .limit(100)
            ).all()
        )
        boundaries = list_due_funding_rate_polls(db, now=now, limit=20)
    for boundary in expired:
        with session_factory() as db:
            with db.begin():
                expire_missing_funding_rates(db, boundary_at=boundary, at=now)
    completed = 0
    for boundary in boundaries:
        with session_factory() as db:
            with db.begin():
                claimed = claim_funding_rate_poll(
                    db,
                    boundary_at=boundary,
                    worker_name=worker_name,
                    lease_seconds=120,
                )
                task = db.get(FundingBoundaryTask, boundary) if claimed else None
                symbols = tuple(task.expected_symbols) if task is not None else ()
        if not claimed:
            continue
        if not symbols:
            _reschedule(session_factory, boundary, now)
            continue
        start_at = boundary - timedelta(hours=1)
        end_at = min(now, boundary + timedelta(minutes=30))
        outcomes: list[tuple[str, tuple[FundingRateRecord, ...] | None]] = []
        try:
            with ThreadPoolExecutor(max_workers=_MAX_POLL_WORKERS) as pool:
                futures = {
                    pool.submit(
                        client.fetch_funding_history,
                        symbol,
                        start_at=start_at,
                        end_at=end_at,
                    ): symbol
                    for symbol in symbols
                }
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        outcomes.append((symbol, future.result()))
                    except Exception as exc:
                        LOGGER.warning(
                            "funding rate fetch failed symbol=%s error_class=%s",
                            symbol,
                            type(exc).__name__,
                        )
                        outcomes.append((symbol, None))
        except Exception as exc:
            LOGGER.warning("funding rate polling failed error_class=%s", type(exc).__name__)
            _reschedule(session_factory, boundary, now)
            continue

        received_any = False
        for symbol, records in outcomes:
            if records is None:
                continue
            record = next(
                (
                    item
                    for item in records
                    if _hour(item.event_at) == boundary
                    and 0
                    <= (item.event_at - boundary).total_seconds()
                    <= _FUNDING_HISTORY_MAX_OFFSET_SECONDS
                ),
                None,
            )
            if record is None:
                continue
            with session_factory() as db:
                with db.begin():
                    inserted = persist_rate_evidence(
                        db,
                        boundary_at=boundary,
                        symbol=symbol,
                        rate=record.rate,
                        history_event_at=record.event_at,
                        raw_record_bytes=record.raw_record_bytes,
                    )
            received_any = received_any or inserted
        current_time = _utc(datetime.now(UTC))
        if current_time >= boundary + timedelta(minutes=30):
            with session_factory() as db:
                with db.begin():
                    expire_missing_funding_rates(db, boundary_at=boundary, at=current_time)
        else:
            _reschedule(session_factory, boundary, current_time)
        completed += int(received_any)
    return completed


def settle_ready_boundaries(
    session_factory: sessionmaker[Session], *, now: datetime, limit: int = 48
) -> tuple[int, int]:
    """Apply pending per-position funding receipts without opening external I/O."""
    now = _utc(now)
    with session_factory() as db:
        stale_captures = tuple(list_stale_funding_oracle_captures(db, now=now, limit=20))
    for boundary in stale_captures:
        with session_factory() as db:
            with db.begin():
                expire_stale_funding_oracle_capture(db, boundary_at=boundary, at=now)

    with session_factory() as db:
        unpaid_position_for_boundary = exists(
            select(PositionRow.id)
            .join(Account, Account.id == PositionRow.account_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .join(Competition, Competition.id == AgentRun.competition_id)
            .where(
                Competition.started_at < FundingBoundaryTask.boundary_at,
                (Competition.ended_at.is_(None))
                | (Competition.ended_at >= FundingBoundaryTask.boundary_at),
                PositionRow.opened_at <= FundingBoundaryTask.boundary_at,
                (PositionRow.closed_at.is_(None))
                | (PositionRow.closed_at > FundingBoundaryTask.boundary_at),
                ~exists(
                    select(FundingPayment.id).where(
                        FundingPayment.position_id == PositionRow.id,
                        FundingPayment.event_at == FundingBoundaryTask.boundary_at,
                    )
                ),
            )
            .correlate(FundingBoundaryTask)
        )
        boundaries = tuple(
            db.scalars(
                select(FundingBoundaryTask.boundary_at)
                .where(
                    FundingBoundaryTask.status.in_(("READY", "UNAVAILABLE")),
                    FundingBoundaryTask.boundary_at <= now,
                    unpaid_position_for_boundary,
                )
                .order_by(FundingBoundaryTask.boundary_at)
                .limit(limit)
            ).all()
        )
    paid = skipped = 0
    for boundary in boundaries:
        with session_factory() as db:
            outstanding = exists(
                select(FundingPayment.id).where(
                    FundingPayment.position_id == PositionRow.id,
                    FundingPayment.event_at == boundary,
                )
            )
            competition_ids = tuple(
                db.scalars(
                    select(Competition.id)
                    .join(AgentRun, AgentRun.competition_id == Competition.id)
                    .join(Account, Account.agent_run_id == AgentRun.id)
                    .join(PositionRow, PositionRow.account_id == Account.id)
                    .where(
                        Competition.started_at <= boundary,
                        (Competition.ended_at.is_(None)) | (Competition.ended_at >= boundary),
                        PositionRow.opened_at <= boundary,
                        (PositionRow.closed_at.is_(None)) | (PositionRow.closed_at > boundary),
                        ~outstanding,
                    )
                    .distinct()
                    .order_by(Competition.id)
                ).all()
            )
        for competition_id in competition_ids:
            with session_factory() as db:
                with db.begin():
                    receipt = settle_funding_boundary(
                        db,
                        competition_id=competition_id,
                        boundary_at=boundary,
                        at=now,
                    )
            paid += receipt.paid
            skipped += receipt.skipped
    return paid, skipped


def _reschedule(session_factory: sessionmaker[Session], boundary: datetime, now: datetime) -> None:
    next_poll = min(
        now + timedelta(seconds=_POLL_INTERVAL_SECONDS),
        boundary + timedelta(minutes=30),
    )
    with session_factory() as db:
        with db.begin():
            if now >= boundary + timedelta(minutes=30):
                expire_missing_funding_rates(db, boundary_at=boundary, at=now)
            else:
                reschedule_funding_poll(db, boundary_at=boundary, next_poll_at=next_poll)


def _shared_context_time(quote_set: MarketQuoteSet) -> datetime | None:
    times = {item.context_received_at for item in quote_set.quotes}
    complete_context = len(times) == 1 and len(quote_set.quotes) == len(BASELINE_SYMBOLS)
    return next(iter(times)) if complete_context else None


def _hour(value: datetime) -> datetime:
    return _utc(value).replace(minute=0, second=0, microsecond=0)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("funding timestamps must be timezone-aware")
    return value.astimezone(UTC)
