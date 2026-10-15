"""Independent stop/target checks against each account's trusted held-symbol mark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from app.db.models import (
    Account as AccountRow,
)
from app.db.models import (
    AgentRun,
    Competition,
    MarketQuote,
    MarketSnapshot,
    QuoteSet,
)
from app.db.models import (
    Position as PositionRow,
)
from app.engine.finance import (
    Account,
    Instrument,
    Quote,
    Rules,
    protective_exit,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.execution import _Context


@dataclass(frozen=True, slots=True)
class ProtectionCycleReceipt:
    checked_accounts: int
    protective_exits: int


def run_protective_exit_cycle(db: Session, *, quote_set_id: str) -> ProtectionCycleReceipt:
    """Check open positions even when no inference result or complete quote universe exists."""
    from app.services.execution import (
        _account,
        _instruments,
        _normalize_timestamp,
        _parse_json,
        _rules,
        _string_list,
        _transaction,
    )

    checked = exits = 0
    with _transaction(db):
        now_value = db.scalar(select(func.now()))
        if now_value is None:
            raise RuntimeError("database time is unavailable")
        now = _normalize_timestamp(now_value)
        quote_set = db.get(QuoteSet, quote_set_id)
        if quote_set is None:
            raise LookupError("protective quote set not found")
        quote_rows = tuple(
            db.scalars(
                select(MarketQuote)
                .where(MarketQuote.quote_set_id == quote_set_id)
                .order_by(MarketQuote.symbol)
            ).all()
        )
        snapshot = db.scalar(
            select(MarketSnapshot).where(MarketSnapshot.quote_set_id == quote_set_id)
        )
        if snapshot is None:
            raise ValueError("protective quote snapshot is missing")
        quote_by_symbol = {row.symbol: row for row in quote_rows}
        competition_ids = db.scalars(
            select(Competition.id)
            .join(AgentRun, AgentRun.competition_id == Competition.id)
            .join(AccountRow, AccountRow.agent_run_id == AgentRun.id)
            .join(PositionRow, PositionRow.account_id == AccountRow.id)
            .where(
                Competition.state.in_(("RUNNING", "PAUSED")),
                PositionRow.state == "OPEN",
            )
            .distinct()
            .order_by(Competition.id)
        ).all()
        for competition_id in competition_ids:
            competition = db.scalar(
                select(Competition).where(Competition.id == competition_id).with_for_update()
            )
            if competition is None:
                continue
            rules_data = _parse_json(competition.rules_bytes)
            rules = _rules(rules_data)
            symbols = tuple(_string_list(rules_data.get("symbols")))
            instruments, _ = _instruments(snapshot.canonical_bytes, symbols, rules)
            agent_ids = db.scalars(
                select(AgentRun.id)
                .where(AgentRun.competition_id == competition.id)
                .order_by(AgentRun.id)
            ).all()
            accounts = db.scalars(
                select(AccountRow)
                .where(AccountRow.agent_run_id.in_(agent_ids))
                .order_by(AccountRow.id)
                .with_for_update()
            ).all()
            for account_row in accounts:
                positions = tuple(
                    db.scalars(
                        select(PositionRow)
                        .where(
                            PositionRow.account_id == account_row.id,
                            PositionRow.state == "OPEN",
                        )
                        .order_by(PositionRow.symbol)
                        .with_for_update()
                    ).all()
                )
                if not positions:
                    continue
                account = _account(account_row, positions, competition.initial_balance)
                quotes = _held_quotes(positions, quote_by_symbol, now)
                count, account, positions = _apply_triggers(
                    db,
                    competition=competition,
                    account_row=account_row,
                    account=account,
                    positions=positions,
                    rules=rules,
                    instruments=instruments,
                    quotes=quotes,
                    quote_set_id=quote_set_id,
                    now=now,
                )
                if count:
                    _persist_account(account_row, account)
                    exits += count
                checked += 1
    return ProtectionCycleReceipt(checked, exits)


def apply_context_protection(
    db: Session, context: _Context
) -> tuple[int, Account, tuple[PositionRow, ...]]:
    """Apply stops using the same accounting path as the independent protection cycle."""
    return _apply_triggers(
        db,
        competition=context.competition,
        account_row=context.account_row,
        account=context.account,
        positions=context.positions,
        rules=context.rules,
        instruments=context.instruments,
        quotes=context.quotes,
        quote_set_id=context.quote_set_id,
        now=context.now,
    )


def _apply_triggers(
    db: Session,
    *,
    competition: Competition,
    account_row: AccountRow,
    account: Account,
    positions: tuple[PositionRow, ...],
    rules: Rules,
    instruments: dict[str, Instrument],
    quotes: dict[str, Quote],
    quote_set_id: str,
    now: datetime,
) -> tuple[int, Account, tuple[PositionRow, ...]]:
    from app.services.execution import (
        _append_event as append_event,
    )
    from app.services.execution import (
        _persist_engine_result as persist_engine_result,
    )
    from app.services.execution import (
        _sync_position_rows as sync_position_rows,
    )

    count = 0
    for row in positions:
        quote = quotes.get(row.symbol)
        instrument = instruments.get(row.symbol)
        if quote is None or instrument is None or row.symbol not in account.positions:
            continue
        if quote.age_seconds < 0 or quote.age_seconds > rules.max_quote_age_seconds:
            continue
        fresh_quotes = {
            symbol: held_quote
            for symbol, held_quote in quotes.items()
            if Decimal("0") <= held_quote.age_seconds <= rules.max_quote_age_seconds
        }
        fresh_instruments = {
            symbol: instruments[symbol] for symbol in fresh_quotes if symbol in instruments
        }
        action_result = protective_exit(
            account,
            symbol=row.symbol,
            quote=quote,
            instrument=instrument,
            rules=rules,
            idempotency_key=f"protective:{row.id}:{quote_set_id}",
            current_quotes=fresh_quotes,
            current_instruments=fresh_instruments,
            as_of=now.date(),
        )
        if action_result is None:
            continue
        event_name, event_detail = action_result.events[0]
        persist_engine_result(
            db,
            action_result,
            account_id=account_row.id,
            proposal_id=None,
            idempotency_key=f"protective:{row.id}:{quote_set_id}",
            kind="PROTECTIVE_EXIT",
        )
        append_event(
            db,
            competition,
            account_id=account_row.id,
            event_type="position.protective_exit",
            payload={
                "symbol": row.symbol,
                "trigger": event_detail.get("trigger"),
                "reason": event_name,
            },
            at=now,
        )
        account = action_result.account
        positions = sync_position_rows(db, account_row.id, positions, account, row.symbol, now)
        count += 1
    return count, account, positions


def _held_quotes(
    positions: tuple[PositionRow, ...],
    rows: dict[str, MarketQuote],
    now: datetime,
) -> dict[str, Quote]:
    held_symbols = {position.symbol for position in positions}
    quotes = {
        symbol: _engine_quote(row, now) for symbol, row in rows.items() if symbol in held_symbols
    }
    return quotes


def _engine_quote(row: MarketQuote, now: datetime) -> Quote:
    source_at = _normalize(row.source_at)
    return Quote(
        row.symbol,
        row.bid,
        row.ask,
        row.mark,
        _seconds(now - source_at),
        _seconds(source_at - datetime(1970, 1, 1, tzinfo=UTC)),
    )


def _persist_account(row: AccountRow, account: Account) -> None:
    row.cash = account.cash
    row.realized_pnl = account.realized_pnl
    row.fees = account.fees
    row.funding = account.funding
    row.reserved_margin = account.reserved_margin
    row.halted = account.halted
    row.peak_equity = account.peak_equity
    row.daily_baseline_equity = account.daily_baseline_equity
    row.risk_day = account.risk_day
    row.version += 1


def _normalize(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _seconds(value: timedelta) -> Decimal:
    return Decimal(value.days * 86400 + value.seconds) + Decimal(value.microseconds) / Decimal(
        1_000_000
    )
