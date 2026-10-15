"""Deterministic linear perpetual paper accounting; no provider or DB dependencies."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum

ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.000000000000000001")


class FinanceError(ValueError):
    """An invalid or unsafe paper trade."""


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class Action(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_POSITION = "CLOSE_POSITION"
    HOLD = "HOLD"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    quantity_step: Decimal = Decimal("0.000001")
    min_quantity: Decimal = Decimal("0.000001")
    min_notional: Decimal = Decimal("10")
    contract_multiplier: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    mark: Decimal
    age_seconds: Decimal = ZERO
    event_seconds: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class Rules:
    commission_rate: Decimal = Decimal("0.0005")
    slippage_bps: Decimal = Decimal("2")
    max_leverage: Decimal = Decimal("5")
    max_order_notional: Decimal = Decimal("25000")
    max_gross_exposure: Decimal = Decimal("40000")
    maintenance_margin_rate: Decimal = Decimal("0.01")
    max_positions: int = 6
    max_quote_age_seconds: Decimal = Decimal("10")
    max_quote_skew_seconds: Decimal = Decimal("5")
    max_daily_loss: Decimal = Decimal("10000")
    max_drawdown_fraction: Decimal = Decimal("1")
    allow_pyramiding: bool = False
    liquidation_fee_rate: Decimal = Decimal("0.005")


@dataclass(slots=True)
class Position:
    symbol: str
    side: Side
    quantity: Decimal
    average_entry: Decimal
    reserved_margin: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


@dataclass(slots=True)
class Account:
    initial_balance: Decimal
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    halted: bool = False
    peak_equity: Decimal | None = None

    @classmethod
    def create(cls, initial_balance: Decimal) -> Account:
        _positive(initial_balance, "initial balance")
        return cls(
            initial_balance=initial_balance, cash=initial_balance, peak_equity=initial_balance
        )

    @property
    def reserved_margin(self) -> Decimal:
        return sum((p.reserved_margin for p in self.positions.values()), ZERO)


@dataclass(frozen=True, slots=True)
class Posting:
    bucket: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class Fill:
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    action: str


@dataclass(frozen=True, slots=True)
class EngineResult:
    account: Account
    fills: tuple[Fill, ...]
    postings: tuple[Posting, ...]
    events: tuple[tuple[str, dict[str, str]], ...]
    equity: Decimal


def _decimal(value: Decimal, label: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FinanceError(f"{label} must be a finite Decimal")
    return value


def _positive(value: Decimal, label: str) -> None:
    if _decimal(value, label) <= ZERO:
        raise FinanceError(f"{label} must be positive")


def money(value: Decimal) -> Decimal:
    _decimal(value, "money")
    try:
        rounded = value.quantize(MONEY_QUANTUM)
    except InvalidOperation as exc:
        raise FinanceError("money exceeds numeric(38,18) range") from exc
    if len(rounded.as_tuple().digits) > 38 or abs(rounded) >= Decimal("1e20"):
        raise FinanceError("money exceeds numeric(38,18) range")
    return rounded


def unrealized_pnl(
    position: Position, mark: Decimal, multiplier: Decimal = Decimal("1")
) -> Decimal:
    _positive(mark, "mark")
    delta = mark - position.average_entry
    if position.side is Side.SHORT:
        delta = -delta
    return money(position.quantity * delta * multiplier)


def gross_exposure(
    account: Account, marks: dict[str, Decimal], instruments: dict[str, Instrument]
) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return money(
            sum(
                (
                    p.quantity * marks[p.symbol] * instruments[p.symbol].contract_multiplier
                    for p in account.positions.values()
                ),
                ZERO,
            )
        )


def equity(
    account: Account, quotes: dict[str, Quote], instruments: dict[str, Instrument]
) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return money(
            account.cash
            + sum(
                (
                    unrealized_pnl(p, quotes[s].mark, instruments[s].contract_multiplier)
                    for s, p in account.positions.items()
                ),
                ZERO,
            )
        )


def available_collateral(
    account: Account, quotes: dict[str, Quote], instruments: dict[str, Instrument]
) -> Decimal:
    # Reserved initial margin remains in equity; subtract it once to find free collateral.
    return money(equity(account, quotes, instruments) - account.reserved_margin)


def quote_set_is_trusted(quotes: Iterable[Quote], required_symbols: set[str], rules: Rules) -> bool:
    materialized = tuple(quotes)
    by_symbol = {q.symbol: q for q in materialized}
    if (
        not required_symbols
        or len(materialized) != len(by_symbol)
        or set(by_symbol) != required_symbols
    ):
        return False
    try:
        for q in materialized:
            for value, label in (
                (q.bid, "bid"),
                (q.ask, "ask"),
                (q.mark, "mark"),
                (q.age_seconds, "quote age"),
                (q.event_seconds, "event time"),
            ):
                _decimal(value, label)
            if q.bid <= ZERO or q.ask < q.bid or q.mark <= ZERO:
                return False
            if q.age_seconds < ZERO or q.age_seconds > rules.max_quote_age_seconds:
                return False
    except FinanceError:
        return False
    times = [q.event_seconds for q in materialized]
    return max(times) - min(times) <= rules.max_quote_skew_seconds


def apply_action(
    account: Account,
    *,
    action: Action,
    symbol: str,
    quantity: Decimal,
    leverage: Decimal,
    quote: Quote,
    instrument: Instrument,
    rules: Rules,
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
    idempotency_key: str,
    current_quotes: dict[str, Quote] | None = None,
    current_instruments: dict[str, Instrument] | None = None,
) -> EngineResult:
    """Apply one baseline order to a detached account value and return balanced journal postings."""
    account = deepcopy(account)
    with localcontext() as ctx:
        ctx.prec = 60
        _decimal(quantity, "quantity")
        for value, label in (
            (quote.bid, "bid"),
            (quote.ask, "ask"),
            (quote.mark, "mark"),
            (quote.age_seconds, "quote age"),
        ):
            _decimal(value, label)
        _positive(leverage, "leverage")
        if leverage > rules.max_leverage:
            raise FinanceError("leverage exceeds competition maximum")
        if (
            quote.symbol != symbol
            or quote.age_seconds < ZERO
            or quote.age_seconds > rules.max_quote_age_seconds
        ):
            raise FinanceError("execution quote is stale or mismatched")
        if quote.bid <= ZERO or quote.ask < quote.bid or quote.mark <= ZERO:
            raise FinanceError("invalid execution quote")
        if account.halted:
            raise FinanceError("account is halted")
        if action in (Action.HOLD, Action.NO_ACTION):
            price_set = dict(current_quotes or {})
            instrument_set = dict(current_instruments or {})
            if account.positions:
                if not set(account.positions).issubset(price_set) or not set(
                    account.positions
                ).issubset(instrument_set):
                    raise FinanceError("fresh marks for every open position are required")
            price_set[symbol] = quote
            instrument_set[symbol] = instrument
            return EngineResult(
                account,
                (),
                (),
                (("NO_ACTION", {"symbol": symbol}),),
                equity(account, price_set, instrument_set),
            )
        if action not in (Action.OPEN_LONG, Action.OPEN_SHORT, Action.CLOSE_POSITION):
            raise FinanceError("unsupported action")
        if not idempotency_key.strip():
            raise FinanceError("idempotency key is required")

        old = account.positions.get(symbol)
        if action is Action.CLOSE_POSITION:
            if old is None:
                raise FinanceError("no open position to close")
            qty = old.quantity if quantity == ZERO else quantity
            if qty != old.quantity:
                raise FinanceError("partial closes are not enabled in baseline")
            fill_side = Side.SHORT if old.side is Side.LONG else Side.LONG
            raw_price = quote.bid if old.side is Side.LONG else quote.ask
            new_position = None
            margin_delta = -old.reserved_margin
            realized = ZERO
        else:
            if quantity <= ZERO:
                raise FinanceError("opening quantity must be positive")
            qty = quantity
            if qty % instrument.quantity_step != ZERO:
                raise FinanceError("quantity does not match instrument precision")
            if qty < instrument.min_quantity:
                raise FinanceError("quantity is below instrument minimum")
            if old is not None and not rules.allow_pyramiding:
                raise FinanceError("baseline does not allow pyramiding or re-entry")
            if old is not None:
                raise FinanceError("netting/pyramiding is not implemented")
            if len(account.positions) >= rules.max_positions:
                raise FinanceError("maximum open positions reached")
            new_side = Side.LONG if action is Action.OPEN_LONG else Side.SHORT
            if stop_loss is not None:
                _positive(stop_loss, "stop loss")
                if (new_side is Side.LONG and stop_loss >= quote.ask) or (
                    new_side is Side.SHORT and stop_loss <= quote.bid
                ):
                    raise FinanceError("stop loss is on the wrong side of entry")
            if take_profit is not None:
                _positive(take_profit, "take profit")
                if (new_side is Side.LONG and take_profit <= quote.ask) or (
                    new_side is Side.SHORT and take_profit >= quote.bid
                ):
                    raise FinanceError("take profit is on the wrong side of entry")
            raw_price = quote.ask if new_side is Side.LONG else quote.bid
            fill_side = new_side
            realized = ZERO
            new_position = None
            margin_delta = ZERO

        slip = rules.slippage_bps / Decimal("10000")
        fill_price = raw_price * (
            Decimal("1") + slip if fill_side is Side.LONG else Decimal("1") - slip
        )
        notional = money(qty * fill_price * instrument.contract_multiplier)
        if action is not Action.CLOSE_POSITION:
            if notional < instrument.min_notional:
                raise FinanceError("order is below minimum notional")
            if notional > rules.max_order_notional:
                raise FinanceError("order exceeds maximum notional")
            margin_delta = money(notional / leverage)
            position_quotes = dict(current_quotes or {})
            position_instruments = dict(current_instruments or {})
            if account.positions and (
                not set(account.positions).issubset(position_quotes)
                or not set(account.positions).issubset(position_instruments)
            ):
                raise FinanceError("fresh marks for every open position are required")
            position_quotes[symbol] = quote
            position_instruments[symbol] = instrument
            fee_estimate = money(notional * rules.commission_rate)
            adverse_mark_loss = money(
                qty * abs(fill_price - quote.mark) * instrument.contract_multiplier
            )
            required_collateral = money(margin_delta + fee_estimate + adverse_mark_loss)
            if required_collateral > available_collateral(
                account, position_quotes, position_instruments
            ):
                raise FinanceError("insufficient available collateral")
            current_marks = {s: position_quotes[s].mark for s in account.positions}
            current_marks[symbol] = quote.mark
            insts = {s: position_instruments[s] for s in account.positions}
            insts[symbol] = instrument
            if (
                money(gross_exposure(account, current_marks, insts) + notional)
                > rules.max_gross_exposure
            ):
                raise FinanceError("gross exposure exceeds competition maximum")
            new_position = Position(
                symbol, fill_side, qty, fill_price, margin_delta, stop_loss, take_profit
            )
        fee = money(notional * rules.commission_rate)
        if action is Action.CLOSE_POSITION:
            if old is None:
                raise FinanceError("no open position to close")
            realized = unrealized_pnl(old, fill_price, instrument.contract_multiplier)
        cash_delta = money(realized - fee)
        reserve_change = margin_delta if old is None else -old.reserved_margin
        postings = [
            Posting("cash", money(cash_delta)),
            Posting("reserved_margin", money(reserve_change)),
            Posting("available_collateral", money(-reserve_change)),
            Posting("realized_pnl", money(-realized)),
            Posting("fees_expense", fee),
        ]
        if sum((p.amount for p in postings), ZERO) != ZERO:
            raise FinanceError("internal ledger postings do not balance")
        final_quotes = dict(current_quotes or {})
        final_quotes[symbol] = quote
        multipliers = dict(current_instruments or {})
        multipliers[symbol] = instrument
        post_symbols = set(account.positions)
        if action is Action.CLOSE_POSITION:
            post_symbols.discard(symbol)
        if action is not Action.CLOSE_POSITION:
            post_symbols.add(symbol)
        if not post_symbols.issubset(final_quotes) or not post_symbols.issubset(multipliers):
            raise FinanceError("fresh marks for every open position are required")
        account.cash = money(account.cash + cash_delta)
        account.realized_pnl = money(account.realized_pnl + realized)
        account.fees = money(account.fees + fee)
        if action is Action.CLOSE_POSITION:
            del account.positions[symbol]
            event = "POSITION_CLOSED"
        else:
            assert new_position is not None
            account.positions[symbol] = new_position
            event = "ORDER_ACCEPTED"
        fill = Fill(symbol, fill_side, qty, money(fill_price), fee, action.value)
        new_equity = equity(account, final_quotes, multipliers)
        account.peak_equity = max(account.peak_equity or account.initial_balance, new_equity)
        detail = {
            "symbol": symbol,
            "quantity": str(qty),
            "price": str(fill.price),
            "fee": str(fee),
            "key": idempotency_key,
        }
        return EngineResult(account, (fill,), tuple(postings), ((event, detail),), new_equity)


def apply_funding(
    account: Account, quotes: dict[str, Quote], instruments: dict[str, Instrument], rate: Decimal
) -> EngineResult:
    """Apply a positive funding rate (longs pay shorts) to all open positions."""
    _decimal(rate, "funding rate")
    account = deepcopy(account)
    with localcontext() as ctx:
        ctx.prec = 60
        total = ZERO
        postings: list[Posting] = []
        for symbol in sorted(account.positions):
            position = account.positions[symbol]
            base = (
                position.quantity
                * quotes[symbol].mark
                * instruments[symbol].contract_multiplier
                * rate
            )
            payment = -base if position.side is Side.LONG else base
            payment = money(payment)
            total = money(total + payment)
            postings.extend((Posting("cash", payment), Posting("funding_income", money(-payment))))
        account.cash = money(account.cash + total)
        account.funding = money(account.funding + total)
        if sum((p.amount for p in postings), ZERO) != ZERO:
            raise FinanceError("funding postings do not balance")
        value = equity(account, quotes, instruments)
        return EngineResult(
            account,
            (),
            tuple(postings),
            (("FUNDING", {"amount": str(total), "rate": str(rate)}),),
            value,
        )


def protective_exit(
    account: Account, symbol: str, quote: Quote, instrument: Instrument, rules: Rules
) -> EngineResult | None:
    position = account.positions.get(symbol)
    if position is None:
        return None
    stop = position.stop_loss
    target = position.take_profit
    stop_hit = stop is not None and (
        quote.mark <= stop if position.side is Side.LONG else quote.mark >= stop
    )
    target_hit = target is not None and (
        quote.mark >= target if position.side is Side.LONG else quote.mark <= target
    )
    if not stop_hit and not target_hit:
        return None
    result = apply_action(
        account,
        action=Action.CLOSE_POSITION,
        symbol=symbol,
        quantity=position.quantity,
        leverage=Decimal("1"),
        quote=quote,
        instrument=instrument,
        rules=rules,
        idempotency_key=f"protective:{symbol}",
    )
    event = "STOP_TRIGGERED" if stop_hit else "TP_TRIGGERED"
    return EngineResult(
        result.account,
        result.fills,
        result.postings,
        ((event, {"symbol": symbol, "trigger": str(stop if stop_hit else target)}), *result.events),
        result.equity,
    )
