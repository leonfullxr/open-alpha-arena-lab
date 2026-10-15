from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

from app.core.canonical import canonical_json_bytes
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DomainEvent,
    FundingBoundaryTask,
    FundingPayment,
    FundingRateEvidence,
    LedgerJournal,
    LedgerPosting,
    MarketQuote,
    MarketSnapshot,
    QuoteSet,
)
from app.db.models import (
    Position as PositionRow,
)
from app.engine.finance import (
    Account as EngineAccount,
)
from app.engine.finance import (
    Instrument,
    Side,
    apply_funding,
    funding_payment_amount,
    money,
    rules_from_config,
)
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

POLL_SECONDS = 30
RATE_DEADLINE = timedelta(minutes=30)
ORACLE_MAX_AGE = timedelta(seconds=10)
FUNDING_HISTORY_MAX_OFFSET = timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class FundingTaskReceipt:
    boundary_at: datetime
    status: str
    quote_set_id: str | None
    snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class FundingSettlementReceipt:
    competition_id: str
    boundary_at: datetime
    status: str
    paid: int
    skipped: int
    pending: int


def claim_funding_oracle_capture(
    db: Session,
    *,
    boundary_at: datetime,
    symbols: tuple[str, ...],
    worker_name: str,
    lease_seconds: int = 15,
) -> bool:
    boundary = _hour(boundary_at)
    if not 1 <= lease_seconds <= 30 or not worker_name or len(worker_name) > 80:
        raise ValueError("invalid funding capture lease")
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("funding capture symbols must be non-empty and unique")
    with _transaction(db):
        now = _database_now(db)
        task = db.scalar(
            select(FundingBoundaryTask)
            .where(FundingBoundaryTask.boundary_at == boundary)
            .with_for_update()
        )
        if task is None:
            values = {
                "boundary_at": boundary,
                "status": "CAPTURE_PENDING",
                "expected_symbols": list(symbols),
                "deadline_at": boundary + RATE_DEADLINE,
            }
            bind = db.get_bind()
            if bind.dialect.name == "postgresql":
                db.execute(
                    pg_insert(FundingBoundaryTask)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["boundary_at"])
                )
            elif bind.dialect.name == "sqlite":
                db.execute(
                    sqlite_insert(FundingBoundaryTask)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["boundary_at"])
                )
            else:
                db.add(FundingBoundaryTask(**values))
                db.flush()
            task = db.scalar(
                select(FundingBoundaryTask)
                .where(FundingBoundaryTask.boundary_at == boundary)
                .with_for_update()
            )
            if task is None:
                raise RuntimeError("funding task was not created")
        elif tuple(task.expected_symbols) != symbols:
            raise ValueError("funding boundary symbol manifest is frozen")
        if task.status != "CAPTURE_PENDING":
            return False
        if now < boundary - ORACLE_MAX_AGE:
            return False
        if task.capture_lease_expires_at is not None and _utc(task.capture_lease_expires_at) > now:
            return False
        if now > boundary:
            task.status = "UNAVAILABLE"
            task.next_poll_at = None
            return False
        task.capture_owner = worker_name
        task.capture_lease_expires_at = now + timedelta(seconds=lease_seconds)
        return True


def persist_oracle_capture(
    db: Session,
    *,
    boundary_at: datetime,
    quote_set_id: str | None,
    snapshot_id: str | None,
    context_received_at: datetime | None,
) -> FundingTaskReceipt:
    boundary = _hour(boundary_at)
    with _transaction(db):
        task = _task_for_update(db, boundary)
        if task.status != "CAPTURE_PENDING":
            return _task_receipt(task)
        now = _database_now(db)
        captured_at = _utc(context_received_at) if context_received_at is not None else None
        valid = (
            quote_set_id is not None
            and snapshot_id is not None
            and captured_at is not None
            and captured_at <= boundary
            and boundary - captured_at <= ORACLE_MAX_AGE
        )
        if valid:
            quote_set = db.get(QuoteSet, quote_set_id)
            snapshot = db.get(MarketSnapshot, snapshot_id)
            valid = (
                quote_set is not None
                and snapshot is not None
                and snapshot.quote_set_id == quote_set_id
                and snapshot.source_label == "hyperliquid"
            )
            if valid:
                quotes = {
                    row.symbol: row
                    for row in db.scalars(
                        select(MarketQuote).where(MarketQuote.quote_set_id == quote_set_id)
                    )
                }
                for symbol in task.expected_symbols:
                    row = quotes.get(symbol)
                    if (
                        row is None
                        or row.oracle_px is None
                        or row.oracle_px <= 0
                        or row.context_received_at is None
                        or _utc(row.context_received_at) != captured_at
                    ):
                        valid = False
                        break
        if not valid:
            task.status = "UNAVAILABLE"
            task.next_poll_at = None
            task.capture_owner = None
            task.capture_lease_expires_at = None
        else:
            task.oracle_quote_set_id = quote_set_id
            task.oracle_snapshot_id = snapshot_id
            if captured_at is None:
                raise RuntimeError("validated funding capture lacks its receive timestamp")
            task.context_received_at = captured_at
            task.status = "PENDING"
            task.next_poll_at = max(now, boundary + timedelta(seconds=1))
            task.capture_owner = None
            task.capture_lease_expires_at = None
        return _task_receipt(task)


def list_stale_funding_oracle_captures(
    db: Session, *, now: datetime, limit: int = 20
) -> list[datetime]:
    if not 1 <= limit <= 100:
        raise ValueError("funding capture limit must be in 1..100")
    at = _utc(now)
    return list(
        db.scalars(
            select(FundingBoundaryTask.boundary_at)
            .where(
                FundingBoundaryTask.status == "CAPTURE_PENDING",
                FundingBoundaryTask.boundary_at < at,
                or_(
                    FundingBoundaryTask.capture_lease_expires_at.is_(None),
                    FundingBoundaryTask.capture_lease_expires_at <= at,
                ),
            )
            .order_by(FundingBoundaryTask.boundary_at)
            .limit(limit)
        )
    )


def expire_stale_funding_oracle_capture(
    db: Session, *, boundary_at: datetime, at: datetime | None = None
) -> bool:
    boundary = _hour(boundary_at)
    with _transaction(db):
        task = _task_for_update(db, boundary)
        now = _utc(at) if at is not None else _database_now(db)
        if task.status != "CAPTURE_PENDING" or now <= boundary:
            return False
        if (
            task.capture_lease_expires_at is not None
            and _utc(task.capture_lease_expires_at) > now
        ):
            return False
        task.status = "UNAVAILABLE"
        task.next_poll_at = None
        task.capture_owner = None
        task.capture_lease_expires_at = None
        return True


def list_due_funding_rate_polls(
    db: Session, *, now: datetime, limit: int = 20
) -> list[datetime]:
    if not 1 <= limit <= 100:
        raise ValueError("funding poll limit must be in 1..100")
    at = _utc(now)
    return list(
        db.scalars(
            select(FundingBoundaryTask.boundary_at)
            .where(
                FundingBoundaryTask.status == "PENDING",
                FundingBoundaryTask.boundary_at <= at,
                FundingBoundaryTask.next_poll_at <= at,
                FundingBoundaryTask.deadline_at >= at,
            )
            .order_by(FundingBoundaryTask.boundary_at)
            .limit(limit)
        )
    )


def claim_funding_rate_poll(
    db: Session,
    *,
    boundary_at: datetime,
    worker_name: str,
    lease_seconds: int = POLL_SECONDS,
) -> bool:
    boundary = _hour(boundary_at)
    if not 1 <= lease_seconds <= 120 or not worker_name or len(worker_name) > 80:
        raise ValueError("invalid funding rate poll lease")
    with _transaction(db):
        now = _database_now(db)
        task = _task_for_update(db, boundary)
        if task.status != "PENDING" or _utc(task.deadline_at) < now:
            return False
        if task.next_poll_at is None or _utc(task.next_poll_at) > now:
            return False
        if task.poll_lease_expires_at is not None and _utc(task.poll_lease_expires_at) > now:
            return False
        expires = now + timedelta(seconds=lease_seconds)
        task.poll_owner = worker_name
        task.poll_lease_expires_at = expires
        task.next_poll_at = expires
        return True


def reschedule_funding_poll(
    db: Session, *, boundary_at: datetime, next_poll_at: datetime
) -> bool:
    boundary = _hour(boundary_at)
    retry_at = _utc(next_poll_at)
    with _transaction(db):
        task = _task_for_update(db, boundary)
        now = _database_now(db)
        if task.status != "PENDING" or now > _utc(task.deadline_at):
            return False
        task.next_poll_at = min(max(retry_at, now), _utc(task.deadline_at))
        task.poll_owner = None
        task.poll_lease_expires_at = None
        return True


def persist_rate_evidence(
    db: Session,
    *,
    boundary_at: datetime,
    symbol: str,
    rate: Decimal | None,
    history_event_at: datetime | None,
    raw_record_bytes: bytes | None,
) -> bool:
    boundary = _hour(boundary_at)
    if not symbol or len(symbol) > 32:
        raise ValueError("funding evidence symbol is invalid")
    with _transaction(db):
        task = _task_for_update(db, boundary)
        event_at: datetime | None = None
        safe_record: bytes | None = None
        if rate is None:
            if history_event_at is not None or raw_record_bytes is not None:
                raise ValueError("unavailable funding evidence cannot contain a rate record")
        else:
            if not isinstance(rate, Decimal) or not rate.is_finite():
                raise ValueError("funding rate must be a finite Decimal")
            if history_event_at is None or not raw_record_bytes:
                raise ValueError("ready funding evidence requires exact record bytes and time")
            event_at = _utc(history_event_at)
            if (
                event_at < boundary
                or event_at > boundary + FUNDING_HISTORY_MAX_OFFSET
                or event_at.microsecond % 1000 != 0
            ):
                raise ValueError("funding history event must be within five seconds after boundary")
            safe_record = _safe_rate_record(
                raw_record_bytes, symbol=symbol, rate=rate, event_at=event_at
            )
        existing = db.scalar(
            select(FundingRateEvidence).where(
                FundingRateEvidence.symbol == symbol,
                FundingRateEvidence.boundary_at == boundary,
            )
        )
        if existing is not None:
            if (
                existing.status == "UNAVAILABLE" and rate is None
            ) or (
                existing.status == "READY"
                and rate is not None
                and existing.rate == rate
                and existing.history_event_at == event_at
                and existing.raw_record_bytes == safe_record
            ):
                return False
            raise ValueError("funding evidence is immutable once recorded")
        if symbol not in task.expected_symbols:
            raise ValueError("funding evidence symbol is outside the frozen boundary manifest")
        now = _database_now(db)
        if task.status not in {"PENDING", "READY"} or now > _utc(task.deadline_at):
            raise ValueError("funding history evidence arrived after the boundary deadline")
        if rate is None:
            evidence = FundingRateEvidence(
                id=str(uuid.uuid4()),
                symbol=symbol,
                boundary_at=boundary,
                status="UNAVAILABLE",
            )
        else:
            if event_at is None or safe_record is None:
                raise RuntimeError("validated funding evidence is incomplete")
            evidence = FundingRateEvidence(
                id=str(uuid.uuid4()),
                symbol=symbol,
                boundary_at=boundary,
                status="READY",
                rate=money(rate),
                history_event_at=event_at,
                raw_record_bytes=safe_record,
                sha256=hashlib.sha256(safe_record).hexdigest(),
            )
        db.add(evidence)
        db.flush()
        _update_task_completion(db, task)
        return True


def expire_missing_funding_rates(
    db: Session, *, boundary_at: datetime, at: datetime | None = None
) -> int:
    boundary = _hour(boundary_at)
    with _transaction(db):
        task = _task_for_update(db, boundary)
        now = _utc(at) if at is not None else _database_now(db)
        if task.status in {"READY", "UNAVAILABLE"} or now < _utc(task.deadline_at):
            return 0
        existing_symbols = set(
            db.scalars(
                select(FundingRateEvidence.symbol).where(
                    FundingRateEvidence.boundary_at == boundary
                )
            )
        )
        missing = sorted(set(task.expected_symbols) - existing_symbols)
        db.add_all(
            [
                FundingRateEvidence(
                    id=str(uuid.uuid4()),
                    symbol=symbol,
                    boundary_at=boundary,
                    status="UNAVAILABLE",
                )
                for symbol in missing
            ]
        )
        task.status = "UNAVAILABLE" if task.oracle_quote_set_id is None else "READY"
        task.next_poll_at = None
        task.poll_owner = None
        task.poll_lease_expires_at = None
        return len(missing)


def settle_funding_boundary(
    db: Session,
    *,
    competition_id: str,
    boundary_at: datetime,
    at: datetime | None = None,
) -> FundingSettlementReceipt:
    boundary = _hour(boundary_at)
    with _transaction(db):
        competition = db.scalar(
            select(Competition).where(Competition.id == competition_id).with_for_update()
        )
        if competition is None:
            raise LookupError("competition not found")
        task = db.scalar(
            select(FundingBoundaryTask)
            .where(FundingBoundaryTask.boundary_at == boundary)
            .with_for_update()
        )
        if task is None:
            return FundingSettlementReceipt(competition_id, boundary, "PENDING", 0, 0, 0)
        settle_at = _utc(at) if at is not None else _database_now(db)
        if task.status == "CAPTURE_PENDING" and settle_at > boundary:
            if (
                task.capture_lease_expires_at is not None
                and _utc(task.capture_lease_expires_at) > settle_at
            ):
                return FundingSettlementReceipt(
                    competition_id, boundary, "PENDING", 0, 0, 0
                )
            task.status = "UNAVAILABLE"
            task.capture_owner = None
            task.capture_lease_expires_at = None
        if task.status == "PENDING" and settle_at >= _utc(task.deadline_at):
            expire_missing_funding_rates(db, boundary_at=boundary, at=at)
            db.refresh(task)
        if task.status == "CAPTURE_PENDING" or (
            task.status == "PENDING" and _utc(task.deadline_at) >= settle_at
        ):
            return FundingSettlementReceipt(competition_id, boundary, "PENDING", 0, 0, 0)
        started = _utc(competition.started_at) if competition.started_at else None
        ended = _utc(competition.ended_at) if competition.ended_at else None
        if started is None or boundary <= started or (ended is not None and boundary > ended):
            return FundingSettlementReceipt(
                competition_id, boundary, "OUTSIDE_COMPETITION", 0, 0, 0
            )

        accounts = db.scalars(
            select(Account)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .where(AgentRun.competition_id == competition_id)
            .order_by(Account.id)
            .with_for_update()
        ).all()
        account_ids = [account.id for account in accounts]
        positions = db.scalars(
            select(PositionRow)
            .where(
                PositionRow.account_id.in_(account_ids),
                PositionRow.opened_at <= boundary,
                (PositionRow.closed_at.is_(None)) | (PositionRow.closed_at > boundary),
            )
            .order_by(PositionRow.account_id, PositionRow.symbol, PositionRow.id)
            .with_for_update()
        ).all() if account_ids else []
        existing_payment_positions = set(
            db.scalars(
                select(FundingPayment.position_id).where(FundingPayment.event_at == boundary)
            )
        )
        evidence = {
            row.symbol: row
            for row in db.scalars(
                select(FundingRateEvidence).where(FundingRateEvidence.boundary_at == boundary)
            )
        }
        oracle_quotes: dict[str, MarketQuote] = {}
        if task.oracle_quote_set_id is not None:
            oracle_quotes = {
                row.symbol: row
                for row in db.scalars(
                    select(MarketQuote).where(
                        MarketQuote.quote_set_id == task.oracle_quote_set_id
                    )
                )
            }
        ready_by_account: dict[str, list[tuple[PositionRow, FundingRateEvidence, Decimal]]] = {}
        paid = skipped = pending = 0
        now = settle_at
        processed_positions = set(existing_payment_positions)
        for position in positions:
            if position.id in processed_positions:
                continue
            rate_evidence = evidence.get(position.symbol)
            quote = oracle_quotes.get(position.symbol)
            quote_valid = task.context_received_at is not None and (
                _utc(task.context_received_at) <= boundary
                and boundary - _utc(task.context_received_at) <= ORACLE_MAX_AGE
            )
            if not quote_valid:
                _skip_payment(
                    db, position, boundary, rate_evidence, None, "oracle_unavailable", now
                )
                processed_positions.add(position.id)
                _append_event(
                    db,
                    competition,
                    position.account_id,
                    "funding.skipped",
                    {"boundary_at": boundary.isoformat(), "reason": "oracle_unavailable"},
                    now,
                )
                skipped += 1
                continue
            if quote is None or quote.oracle_px is None or quote.oracle_px <= 0:
                _skip_payment(
                    db, position, boundary, rate_evidence, None, "oracle_unavailable", now
                )
                processed_positions.add(position.id)
                skipped += 1
                continue
            if rate_evidence is None:
                pending += 1
                continue
            if rate_evidence.status == "UNAVAILABLE":
                _skip_payment(
                    db,
                    position,
                    boundary,
                    rate_evidence,
                    quote.oracle_px,
                    "rate_unavailable",
                    now,
                )
                processed_positions.add(position.id)
                _append_event(
                    db,
                    competition,
                    position.account_id,
                    "funding.skipped",
                    {"boundary_at": boundary.isoformat(), "reason": "rate_unavailable"},
                    now,
                )
                skipped += 1
                continue
            ready_by_account.setdefault(position.account_id, []).append(
                (position, rate_evidence, quote.oracle_px)
            )

        account_by_id = {account.id: account for account in accounts}
        for account_id, settlements in ready_by_account.items():
            account_row = account_by_id[account_id]
            rows_for_account = [row for row in positions if row.account_id == account_id]
            engine_account = _engine_account(
                account_row, rows_for_account, competition.initial_balance
            )
            rates = {row.symbol: ev.rate for row, ev, _ in settlements if ev.rate is not None}
            prices = {row.symbol: px for row, _, px in settlements}
            instruments = {row.symbol: Instrument(row.symbol) for row, _, _ in settlements}
            rules_data = _json_object(competition.rules_bytes)
            rules = rules_from_config(rules_data)
            if (
                rules.funding_mode != "hourly_historical_rate"
                or rules.funding_rate_basis != "funding_history"
                or rules.funding_price_basis != "oracle_px_paper_approximation"
            ):
                raise ValueError("competition has no supported frozen paper funding policy")
            result = apply_funding(
                engine_account,
                {},
                instruments,
                rates,
                rules,
                as_of=now.date(),
                funding_prices=prices,
            )
            account_row.cash = result.account.cash
            account_row.funding = result.account.funding
            account_row.halted = result.account.halted
            account_row.peak_equity = result.account.peak_equity
            account_row.daily_baseline_equity = result.account.daily_baseline_equity
            account_row.risk_day = result.account.risk_day
            account_row.version += 1
            total = Decimal("0")
            for position, rate_row, oracle_px in settlements:
                rate = rate_row.rate
                if rate is None:
                    raise RuntimeError("ready funding evidence has no rate")
                engine_position = engine_account.positions[position.symbol]
                amount = funding_payment_amount(
                    engine_position,
                    rate,
                    oracle_px,
                    instruments[position.symbol].contract_multiplier,
                )
                with localcontext() as context:
                    context.prec = 60
                    total = money(total + amount)
                db.add(
                    FundingPayment(
                        id=str(uuid.uuid4()),
                        account_id=account_id,
                        position_id=position.id,
                        symbol=position.symbol,
                        rate=rate,
                        amount=amount,
                        event_at=boundary,
                        source="HYPERLIQUID_FUNDING_HISTORY",
                        oracle_px=oracle_px,
                        evidence_id=rate_row.id,
                        status="PAID",
                    )
                )
                paid += 1
            journal_id = str(uuid.uuid4())
            db.add(
                LedgerJournal(
                    id=journal_id,
                    account_id=account_id,
                    event_key=f"funding:{account_id}:{boundary.isoformat()}",
                )
            )
            db.flush()
            db.add_all(
                [
                    LedgerPosting(
                        id=str(uuid.uuid4()), journal_id=journal_id, bucket="cash", amount=total
                    ),
                    LedgerPosting(
                        id=str(uuid.uuid4()),
                        journal_id=journal_id,
                        bucket="funding_income",
                        amount=total.copy_negate(),
                    ),
                ]
            )
            _append_event(
                db,
                competition,
                account_id,
                "funding.settled",
                {"boundary_at": boundary.isoformat(), "position_count": len(settlements)},
                now,
            )
        for position in positions:
            if position.id in processed_positions:
                continue
            if position.symbol not in evidence and pending == 0:
                _skip_payment(db, position, boundary, None, None, "rate_unavailable", now)
                processed_positions.add(position.id)
                _append_event(
                    db,
                    competition,
                    position.account_id,
                    "funding.skipped",
                    {"boundary_at": boundary.isoformat(), "reason": "rate_unavailable"},
                    now,
                )
                skipped += 1
        db.flush()
        status = "SETTLED" if pending == 0 else "PENDING"
        return FundingSettlementReceipt(competition_id, boundary, status, paid, skipped, pending)


def funding_status(db: Session, boundary_at: datetime) -> FundingTaskReceipt | None:
    task = db.get(FundingBoundaryTask, _hour(boundary_at))
    return _task_receipt(task) if task is not None else None


def _skip_payment(
    db: Session,
    position: PositionRow,
    boundary: datetime,
    evidence: FundingRateEvidence | None,
    oracle_px: Decimal | None,
    reason: str,
    now: datetime,
) -> None:
    db.add(
        FundingPayment(
            id=str(uuid.uuid4()),
            account_id=position.account_id,
            position_id=position.id,
            symbol=position.symbol,
            rate=evidence.rate if evidence and evidence.status == "READY" else None,
            amount=None,
            event_at=boundary,
            source="HYPERLIQUID_FUNDING_HISTORY",
            oracle_px=oracle_px,
            evidence_id=evidence.id if evidence else None,
            status="SKIPPED",
            reason=reason,
        )
    )


def _engine_account(row: Account, positions: list[PositionRow], initial: Decimal) -> EngineAccount:
    from app.engine.finance import Position as EnginePosition

    return EngineAccount(
        initial_balance=initial,
        cash=row.cash,
        positions={
            position.symbol: EnginePosition(
                position.symbol,
                Side(position.side),
                position.quantity,
                position.average_entry,
                position.reserved_margin,
                position.stop_loss,
                position.take_profit,
            )
            for position in positions
        },
        realized_pnl=row.realized_pnl,
        fees=row.fees,
        funding=row.funding,
        halted=row.halted,
        peak_equity=row.peak_equity or initial,
        daily_baseline_equity=row.daily_baseline_equity or initial,
        risk_day=row.risk_day,
    )


def _append_event(
    db: Session,
    competition: Competition,
    account_id: str,
    event_type: str,
    payload: dict[str, str | int],
    at: datetime,
) -> None:
    competition.event_seq += 1
    db.add(
        DomainEvent(
            id=str(uuid.uuid4()),
            competition_id=competition.id,
            sequence=competition.event_seq,
            account_id=account_id,
            event_type=event_type,
            payload=payload,
            event_at=at,
        )
    )


def _update_task_completion(db: Session, task: FundingBoundaryTask) -> None:
    count = db.scalar(
        select(func.count()).select_from(FundingRateEvidence).where(
            FundingRateEvidence.boundary_at == task.boundary_at
        )
    )
    if count == len(task.expected_symbols):
        task.status = "READY"
        task.next_poll_at = None
        task.poll_owner = None
        task.poll_lease_expires_at = None
    else:
        now = _database_now(db)
        task.status = "PENDING"
        task.next_poll_at = min(now + timedelta(seconds=POLL_SECONDS), _utc(task.deadline_at))
        task.poll_owner = None
        task.poll_lease_expires_at = None


def _task_for_update(db: Session, boundary: datetime) -> FundingBoundaryTask:
    task = db.scalar(
        select(FundingBoundaryTask)
        .where(FundingBoundaryTask.boundary_at == boundary)
        .with_for_update()
    )
    if task is None:
        raise LookupError("funding boundary task not found")
    return task


def _task_receipt(task: FundingBoundaryTask) -> FundingTaskReceipt:
    return FundingTaskReceipt(
        _utc(task.boundary_at), task.status, task.oracle_quote_set_id, task.oracle_snapshot_id
    )


def _hour(value: datetime) -> datetime:
    boundary = _utc(value)
    if boundary.minute or boundary.second or boundary.microsecond:
        raise ValueError("funding boundary must be aligned to a UTC hour")
    return boundary


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _database_now(db: Session) -> datetime:
    value = db.scalar(select(func.now()))
    if value is None:
        raise RuntimeError("database clock unavailable")
    return _utc(value)


def _json_object(value: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("competition rules are invalid") from exc
    if not isinstance(parsed, dict):
        raise ValueError("competition rules must be a JSON object")
    return parsed


def _safe_rate_record(
    raw_bytes: bytes, *, symbol: str, rate: Decimal, event_at: datetime
) -> bytes:
    if not raw_bytes or len(raw_bytes) > 2_000_000:
        raise ValueError("funding history response is empty or exceeds its size limit")
    try:
        decoded = json.loads(raw_bytes, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("funding history response is not valid JSON") from exc
    records = decoded if isinstance(decoded, list) else [decoded]
    matching: list[dict[str, object]] = []
    for item in records:
        if not isinstance(item, dict) or item.get("coin") != symbol:
            continue
        if item.get("time") != _epoch_milliseconds(event_at):
            continue
        matching.append(item)
    if len(matching) != 1:
        raise ValueError("funding history bytes do not identify exactly one matching record")
    source = matching[0]
    raw_time = source.get("time")
    if isinstance(raw_time, bool) or not isinstance(raw_time, int):
        raise ValueError("funding history record has an invalid event time")
    raw_rate = source.get("fundingRate")
    if isinstance(raw_rate, bool) or not isinstance(raw_rate, (str, int, Decimal)):
        raise ValueError("funding history record has an invalid rate")
    try:
        recorded_rate = Decimal(str(raw_rate))
    except Exception as exc:
        raise ValueError("funding history record has an invalid rate") from exc
    if not recorded_rate.is_finite() or recorded_rate != rate:
        raise ValueError("funding history rate does not match the supplied rate")
    safe: dict[str, str | int] = {
        "coin": symbol,
        "fundingRate": str(recorded_rate),
        "time": raw_time,
    }
    premium = source.get("premium")
    if premium is not None:
        if isinstance(premium, bool) or not isinstance(premium, (str, int, Decimal)):
            raise ValueError("funding history record has an invalid premium")
        parsed_premium = Decimal(str(premium))
        if not parsed_premium.is_finite():
            raise ValueError("funding history record has an invalid premium")
        safe["premium"] = str(parsed_premium)
    return canonical_json_bytes(safe)


def _epoch_milliseconds(value: datetime) -> int:
    utc_value = _utc(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = utc_value - epoch
    return (elapsed.days * 86_400 + elapsed.seconds) * 1000 + elapsed.microseconds // 1000


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
    else:
        with db.begin():
            yield
