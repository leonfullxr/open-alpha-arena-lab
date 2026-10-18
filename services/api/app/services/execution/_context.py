from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.db.models import Account as AccountRow
from app.db.models import (
    Competition,
    DecisionRound,
    RoundAgentJob,
)
from app.db.models import (
    Position as PositionRow,
)
from app.engine.finance import Account, Instrument, Position, Quote, Rules, Side, rules_from_config
from sqlalchemy.orm import Session


@dataclass(slots=True)
class _Context:
    competition: Competition
    job: RoundAgentJob
    round: DecisionRound
    account_row: AccountRow
    account: Account
    positions: tuple[PositionRow, ...]
    rules: Rules
    symbols: tuple[str, ...]
    instruments: dict[str, Instrument]
    instrument_max_leverage: dict[str, int]
    quotes: dict[str, Quote]
    quote_trusted: bool
    quote_set_id: str
    now: datetime
    output: bytes
    protectively_closed_symbols: set[str] = field(default_factory=set)


def _account(
    row: AccountRow, positions: tuple[PositionRow, ...], initial_balance: Decimal
) -> Account:
    initial = initial_balance
    peak = initial
    return Account(
        initial_balance=initial,
        cash=row.cash,
        positions={
            position.symbol: Position(
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
        peak_equity=row.peak_equity or peak,
        daily_baseline_equity=row.daily_baseline_equity or initial,
        risk_day=row.risk_day,
    )


def _rules(data: dict[str, Any]) -> Rules:
    return rules_from_config(data)


def _instruments(
    snapshot_bytes: bytes, symbols: tuple[str, ...], rules: Rules
) -> tuple[dict[str, Instrument], dict[str, int]]:
    payload = _parse_json(snapshot_bytes)
    raw_instruments = payload.get("instruments", [])
    specs: dict[str, tuple[int, int]] = {}
    if isinstance(raw_instruments, list):
        for item in raw_instruments:
            if isinstance(item, dict) and isinstance(item.get("symbol"), str):
                decimals = item.get("size_decimals")
                max_leverage = item.get("max_leverage")
                if (
                    isinstance(decimals, int)
                    and not isinstance(decimals, bool)
                    and 0 <= decimals <= 18
                    and isinstance(max_leverage, int)
                    and not isinstance(max_leverage, bool)
                    and max_leverage >= 1
                ):
                    specs[item["symbol"]] = (decimals, max_leverage)
    instruments: dict[str, Instrument] = {}
    max_leverages: dict[str, int] = {}
    for symbol in symbols:
        decimals, max_leverage = specs.get(symbol, (6, int(rules.max_leverage)))
        step = Decimal(1).scaleb(-decimals)
        instruments[symbol] = Instrument(symbol, quantity_step=step, min_quantity=step)
        max_leverages[symbol] = max_leverage
    return instruments, max_leverages


def _parse_json(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("stored canonical JSON is invalid") from None
    if not isinstance(value, dict):
        raise ValueError("stored canonical JSON has an invalid shape")
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("competition symbol universe is invalid")
    return value


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timedelta_seconds(value: Any) -> Decimal:
    return Decimal(value.days * 86400 + value.seconds) + Decimal(value.microseconds) / Decimal(
        1_000_000
    )


def _timestamp_seconds(value: datetime) -> Decimal:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return _timedelta_seconds(_normalize_timestamp(value) - epoch)


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return
    with db.begin():
        yield
