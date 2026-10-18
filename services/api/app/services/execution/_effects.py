from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.db.models import (
    Account as AccountRow,
)
from app.db.models import (
    Competition,
    DomainEvent,
    EquitySample,
    LedgerJournal,
    LedgerPosting,
    Order,
)
from app.db.models import (
    Fill as FillRow,
)
from app.db.models import (
    Position as PositionRow,
)
from app.engine.finance import Account, EngineResult, equity, unrealized_pnl
from app.services.execution._context import _Context
from sqlalchemy.orm import Session


def _persist_engine_result(
    db: Session,
    result: EngineResult,
    *,
    account_id: str,
    proposal_id: str | None,
    idempotency_key: str,
    kind: str,
    executed_at: datetime,
    quote_set_id: str,
    event_sequence: int,
) -> Order | None:
    if not result.fills:
        return None
    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        account_id=account_id,
        proposal_id=proposal_id,
        idempotency_key=idempotency_key,
        kind=kind,
        status="FILLED",
        quote_set_id=quote_set_id,
        event_sequence=event_sequence,
    )
    db.add(order)
    db.flush()
    for ordinal, fill in enumerate(result.fills):
        db.add(
            FillRow(
                id=str(uuid.uuid4()),
                order_id=order_id,
                symbol=fill.symbol,
                side=fill.side.value,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                executed_at=executed_at,
                ordinal=ordinal,
            )
        )
    journal_id = str(uuid.uuid4())
    db.add(LedgerJournal(id=journal_id, account_id=account_id, event_key=idempotency_key))
    db.flush()
    db.add_all(
        [
            LedgerPosting(
                id=str(uuid.uuid4()),
                journal_id=journal_id,
                bucket=posting.bucket,
                amount=posting.amount,
            )
            for posting in result.postings
        ]
    )
    return order


def _sync_position_rows(
    db: Session,
    account_id: str,
    positions: tuple[PositionRow, ...],
    account: Account,
    changed_symbol: str,
    now: datetime,
) -> tuple[PositionRow, ...]:
    row_by_symbol = {row.symbol: row for row in positions if row.state == "OPEN"}
    simulated = account.positions
    position = simulated.get(changed_symbol)
    row = row_by_symbol.get(changed_symbol)
    if position is None:
        if row is not None:
            row.state = "CLOSED"
            row.closed_at = now
        return positions
    if row is None:
        row = PositionRow(
            id=str(uuid.uuid4()),
            account_id=account_id,
            symbol=changed_symbol,
            side=position.side.value,
            quantity=position.quantity,
            average_entry=position.average_entry,
            reserved_margin=position.reserved_margin,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            state="OPEN",
            opened_at=now,
        )
        db.add(row)
        return (*positions, row)
    row.side = position.side.value
    row.quantity = position.quantity
    row.average_entry = position.average_entry
    row.reserved_margin = position.reserved_margin
    row.stop_loss = position.stop_loss
    row.take_profit = position.take_profit
    row.state = "OPEN"
    return positions


def _persist_account_and_equity(db: Session, context: _Context) -> None:
    account = context.account
    account_row = context.account_row
    _persist_account_row(account_row, account)
    if not context.quote_trusted:
        return
    marks = {symbol: quote.mark for symbol, quote in context.quotes.items()}
    current_equity = equity(account, context.quotes, context.instruments)
    unrealized = sum(
        (
            unrealized_pnl(position, marks[symbol], context.instruments[symbol].contract_multiplier)
            for symbol, position in account.positions.items()
        ),
        Decimal("0"),
    )
    db.add(
        EquitySample(
            id=str(uuid.uuid4()),
            account_id=account_row.id,
            round_index=context.round.round_index,
            logical_at=context.round.logical_at,
            equity=current_equity,
            realized_pnl=account.realized_pnl,
            unrealized_pnl=unrealized,
            fees=account.fees,
            funding=account.funding,
        )
    )


def _persist_account_row(account_row: AccountRow, account: Account) -> None:
    account_row.cash = account.cash
    account_row.realized_pnl = account.realized_pnl
    account_row.fees = account.fees
    account_row.funding = account.funding
    account_row.reserved_margin = account.reserved_margin
    account_row.halted = account.halted
    account_row.peak_equity = account.peak_equity
    account_row.daily_baseline_equity = account.daily_baseline_equity
    account_row.risk_day = account.risk_day
    account_row.version += 1


def _append_event(
    db: Session,
    competition: Competition,
    *,
    account_id: str | None,
    event_type: str,
    payload: dict[str, Any],
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
