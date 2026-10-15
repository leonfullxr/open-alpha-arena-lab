"""Deterministic linear perpetual paper accounting; no provider or DB dependencies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import cast

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
    funding_mode: str = "hourly_historical_rate"
    funding_interval_hours: int = 1
    funding_history_max_offset_seconds: int = 5
    funding_rate_basis: str = "funding_history"
    funding_price_basis: str = "oracle_px_paper_approximation"
    risk_policy_version: str = "risk-v1"
    snapshot_schema_version: int = 1
    proposal_schema_version: int = 1
    public_evidence_schema_version: int = 1
    market_window_candles: int = 12


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
    daily_baseline_equity: Decimal | None = None
    risk_day: date | None = None

    @classmethod
    def create(cls, initial_balance: Decimal) -> Account:
        _positive(initial_balance, "initial balance")
        return cls(
            initial_balance=initial_balance,
            cash=initial_balance,
            peak_equity=initial_balance,
            daily_baseline_equity=initial_balance,
            risk_day=datetime.now(UTC).date(),
        )

    @property
    def reserved_margin(self) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 60
            return money(sum((p.reserved_margin for p in self.positions.values()), ZERO))


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
    equity: Decimal | None


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
        with localcontext() as ctx:
            ctx.prec = 60
            rounded = value.quantize(MONEY_QUANTUM)
    except InvalidOperation as exc:
        raise FinanceError("money exceeds numeric(38,18) range") from exc
    if len(rounded.as_tuple().digits) > 38 or rounded.copy_abs().adjusted() >= 20:
        raise FinanceError("money exceeds numeric(38,18) range")
    return rounded


def unrealized_pnl(
    position: Position, mark: Decimal, multiplier: Decimal = Decimal("1")
) -> Decimal:
    _positive(mark, "mark")
    with localcontext() as ctx:
        ctx.prec = 60
        delta = mark - position.average_entry
        if position.side is Side.SHORT:
            delta = -delta
        return money(position.quantity * delta * multiplier)


def funding_payment_amount(
    position: Position,
    rate: Decimal,
    oracle_px: Decimal,
    contract_multiplier: Decimal = Decimal("1"),
) -> Decimal:
    """Return signed account cash change: positive credits the account."""
    _decimal(rate, "funding rate")
    _positive(oracle_px, "funding oracle price")
    _positive(contract_multiplier, "contract multiplier")
    with localcontext() as ctx:
        ctx.prec = 60
        notional_rate = position.quantity * oracle_px * contract_multiplier * rate
        return money(-notional_rate if position.side is Side.LONG else notional_rate)


def evaluate_risk(
    account: Account,
    current_equity: Decimal,
    rules: Rules,
    *,
    as_of: date | None = None,
) -> tuple[Account, tuple[str, ...]]:
    """Update the persisted risk baseline and latch a breach without blocking exits."""
    _decimal(current_equity, "equity")
    account = deepcopy(account)
    with localcontext() as ctx:
        ctx.prec = 60
        risk_day = as_of or datetime.now(UTC).date()
        if account.risk_day != risk_day or account.daily_baseline_equity is None:
            account.risk_day = risk_day
            account.daily_baseline_equity = current_equity
        peak = account.peak_equity or account.initial_balance
        reasons: list[str] = []
        if account.daily_baseline_equity - current_equity >= rules.max_daily_loss:
            reasons.append("MAX_DAILY_LOSS")
        if peak > ZERO and (peak - current_equity) / peak >= rules.max_drawdown_fraction:
            reasons.append("MAX_DRAWDOWN")
        account.peak_equity = max(peak, current_equity)
    if reasons:
        account.halted = True
    return account, tuple(reasons)


def validate_rules(rules: Rules) -> None:
    for value, label in (
        (rules.commission_rate, "commission rate"),
        (rules.slippage_bps, "slippage"),
        (rules.max_leverage, "maximum leverage"),
        (rules.max_order_notional, "maximum order notional"),
        (rules.max_gross_exposure, "maximum gross exposure"),
        (rules.maintenance_margin_rate, "maintenance margin rate"),
        (rules.max_quote_age_seconds, "maximum quote age"),
        (rules.max_quote_skew_seconds, "maximum quote skew"),
        (rules.max_daily_loss, "maximum daily loss"),
        (rules.max_drawdown_fraction, "maximum drawdown fraction"),
        (rules.liquidation_fee_rate, "liquidation fee rate"),
    ):
        _decimal(value, label)
    if not ZERO <= rules.commission_rate < Decimal("1"):
        raise FinanceError("commission rate must be in [0, 1)")
    if not ZERO <= rules.slippage_bps < Decimal("10000"):
        raise FinanceError("slippage must be in [0, 10000)")
    for value, label in (
        (rules.max_leverage, "maximum leverage"),
        (rules.max_order_notional, "maximum order notional"),
        (rules.max_gross_exposure, "maximum gross exposure"),
        (rules.max_quote_age_seconds, "maximum quote age"),
        (rules.max_daily_loss, "maximum daily loss"),
    ):
        if value <= ZERO:
            raise FinanceError(f"{label} must be positive")
    if not ZERO < rules.maintenance_margin_rate < Decimal("1"):
        raise FinanceError("maintenance margin rate must be in (0, 1)")
    if not ZERO <= rules.max_quote_skew_seconds:
        raise FinanceError("maximum quote skew must be nonnegative")
    if not ZERO < rules.max_drawdown_fraction <= Decimal("1"):
        raise FinanceError("maximum drawdown fraction must be in (0, 1]")
    if not ZERO <= rules.liquidation_fee_rate < Decimal("1"):
        raise FinanceError("liquidation fee rate must be in [0, 1)")
    if rules.funding_mode != "hourly_historical_rate":
        raise FinanceError("unsupported funding mode")
    if rules.funding_interval_hours != 1:
        raise FinanceError("only the documented hourly funding interval is supported")
    if rules.funding_history_max_offset_seconds != 5:
        raise FinanceError("unsupported funding history event-time offset")
    if rules.funding_rate_basis != "funding_history":
        raise FinanceError("funding rate must come from historical funding evidence")
    if rules.funding_price_basis not in {"oracle_px", "oracle_px_paper_approximation"}:
        raise FinanceError("funding notional must use the captured paper oracle price")
    if rules.risk_policy_version != "risk-v1":
        raise FinanceError("unsupported risk policy version")
    if (
        rules.snapshot_schema_version != 1
        or rules.proposal_schema_version != 1
        or rules.public_evidence_schema_version != 1
        or rules.market_window_candles != 12
    ):
        raise FinanceError("unsupported frozen evidence schema or market window")
    if (
        not isinstance(rules.max_positions, int)
        or isinstance(rules.max_positions, bool)
        or rules.max_positions < 1
    ):
        raise FinanceError("maximum positions must be a positive integer")


def rules_from_config(data: Mapping[str, object]) -> Rules:
    """Parse the canonical frozen rule names into the engine's typed policy."""

    def decimal(name: str) -> Decimal:
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise FinanceError(f"frozen rule {name} must be a decimal string or integer")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise FinanceError(f"frozen rule {name} is invalid") from exc
        _decimal(result, name)
        return result

    max_positions = data.get("max_positions")
    allow_pyramiding = data.get("allow_pyramiding")
    interval = data.get("funding_interval_hours")
    funding_history_max_offset = data.get("funding_history_max_offset_seconds")
    funding_mode = data.get("funding_mode")
    funding_rate_basis = data.get("funding_rate_basis")
    funding_price_basis = data.get("funding_price_basis")
    policy_version = data.get("risk_policy_version")
    snapshot_schema_version = data.get("snapshot_schema_version")
    proposal_schema_version = data.get("proposal_schema_version")
    public_evidence_schema_version = data.get("public_evidence_schema_version")
    market_window_candles = data.get("market_window_candles")
    if not isinstance(max_positions, int) or isinstance(max_positions, bool):
        raise FinanceError("frozen rule max_positions must be an integer")
    if not isinstance(allow_pyramiding, bool):
        raise FinanceError("frozen rule allow_pyramiding must be boolean")
    if not isinstance(interval, int) or isinstance(interval, bool):
        raise FinanceError("frozen rule funding_interval_hours must be an integer")
    if not isinstance(funding_history_max_offset, int) or isinstance(
        funding_history_max_offset, bool
    ):
        raise FinanceError("frozen rule funding_history_max_offset_seconds must be an integer")
    if not isinstance(funding_mode, str):
        raise FinanceError("frozen funding and risk policy identifiers are required")
    if not isinstance(funding_rate_basis, str):
        raise FinanceError("frozen funding and risk policy identifiers are required")
    if not isinstance(funding_price_basis, str):
        raise FinanceError("frozen funding and risk policy identifiers are required")
    if not isinstance(policy_version, str):
        raise FinanceError("frozen funding and risk policy identifiers are required")
    for name, value in (
        ("snapshot_schema_version", snapshot_schema_version),
        ("proposal_schema_version", proposal_schema_version),
        ("public_evidence_schema_version", public_evidence_schema_version),
        ("market_window_candles", market_window_candles),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise FinanceError(f"frozen rule {name} must be an integer")
    rules = Rules(
        commission_rate=decimal("commission_rate"),
        slippage_bps=decimal("slippage_bps"),
        max_leverage=decimal("leverage_max"),
        max_order_notional=decimal("max_notional"),
        max_gross_exposure=decimal("max_gross_exposure"),
        maintenance_margin_rate=decimal("maintenance_margin_rate"),
        max_positions=max_positions,
        max_quote_age_seconds=decimal("quote_max_age_seconds"),
        max_quote_skew_seconds=decimal("quote_set_max_skew_seconds"),
        max_daily_loss=decimal("max_daily_loss"),
        max_drawdown_fraction=decimal("max_drawdown_fraction"),
        allow_pyramiding=allow_pyramiding,
        liquidation_fee_rate=decimal("liquidation_fee_rate"),
        funding_mode=funding_mode,
        funding_interval_hours=interval,
        funding_history_max_offset_seconds=funding_history_max_offset,
        funding_rate_basis=funding_rate_basis,
        funding_price_basis=funding_price_basis,
        risk_policy_version=policy_version,
        snapshot_schema_version=cast(int, snapshot_schema_version),
        proposal_schema_version=cast(int, proposal_schema_version),
        public_evidence_schema_version=cast(int, public_evidence_schema_version),
        market_window_candles=cast(int, market_window_candles),
    )
    decimal("fixture_funding_rate_per_hour")
    validate_rules(rules)
    return rules


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
    with localcontext() as ctx:
        ctx.prec = 60
        return money(equity(account, quotes, instruments) - account.reserved_margin)


def quote_set_is_trusted(quotes: Iterable[Quote], required_symbols: set[str], rules: Rules) -> bool:
    materialized = tuple(quotes)
    by_symbol = {q.symbol: q for q in materialized}
    try:
        validate_rules(rules)
    except FinanceError:
        return False
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
    liquidation: bool = False,
    as_of: date | None = None,
) -> EngineResult:
    """Apply one baseline order to a detached account value and return balanced journal postings."""
    account = deepcopy(account)
    with localcontext() as ctx:
        ctx.prec = 60
        validate_rules(rules)
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
        if action in (Action.HOLD, Action.NO_ACTION):
            price_set = dict(current_quotes or {})
            instrument_set = dict(current_instruments or {})
            if account.positions:
                if not set(account.positions).issubset(price_set) or not set(
                    account.positions
                ).issubset(instrument_set):
                    raise FinanceError("fresh marks for every open position are required")
                held_quotes = {key: price_set[key] for key in account.positions}
                if not quote_set_is_trusted(held_quotes.values(), set(account.positions), rules):
                    raise FinanceError("fresh marks for every open position are required")
            price_set[symbol] = quote
            instrument_set[symbol] = instrument
            value = equity(account, price_set, instrument_set)
            account, _ = evaluate_risk(account, value, rules, as_of=as_of)
            return EngineResult(
                account,
                (),
                (),
                (("NO_ACTION", {"symbol": symbol}),),
                value,
            )
        if action not in (Action.OPEN_LONG, Action.OPEN_SHORT, Action.CLOSE_POSITION):
            raise FinanceError("unsupported action")
        if not idempotency_key.strip():
            raise FinanceError("idempotency key is required")
        if action in (Action.OPEN_LONG, Action.OPEN_SHORT) and account.halted:
            raise FinanceError("account is halted for new entries")
        old = account.positions.get(symbol)
        if old is not None and action in (Action.OPEN_LONG, Action.OPEN_SHORT):
            if not rules.allow_pyramiding:
                raise FinanceError("baseline does not allow pyramiding or re-entry")
            raise FinanceError("netting/pyramiding is not implemented")
        if action in (Action.OPEN_LONG, Action.OPEN_SHORT) and account.positions:
            marked_quotes = dict(current_quotes or {})
            marked_instruments = dict(current_instruments or {})
            if not set(account.positions).issubset(marked_quotes) or not set(
                account.positions
            ).issubset(marked_instruments):
                raise FinanceError("fresh marks for every open position are required")
            held_quotes = {key: marked_quotes[key] for key in account.positions}
            if not quote_set_is_trusted(held_quotes.values(), set(account.positions), rules):
                raise FinanceError("fresh marks for every open position are required")
            marked_equity = equity(account, marked_quotes, marked_instruments)
            account, risk_reasons = evaluate_risk(account, marked_equity, rules, as_of=as_of)
            if risk_reasons:
                raise FinanceError("account risk limits block new entries")

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
        fee_rate = rules.commission_rate + (rules.liquidation_fee_rate if liquidation else ZERO)
        fee = money(notional * fee_rate)
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
        complete_marks = post_symbols.issubset(final_quotes) and post_symbols.issubset(multipliers)
        if complete_marks and post_symbols:
            complete_marks = quote_set_is_trusted(
                (final_quotes[key] for key in post_symbols), post_symbols, rules
            )
        if not complete_marks and action is not Action.CLOSE_POSITION:
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
        new_equity = equity(account, final_quotes, multipliers) if complete_marks else None
        if new_equity is not None:
            account, _ = evaluate_risk(account, new_equity, rules, as_of=as_of)
        detail = {
            "symbol": symbol,
            "quantity": str(qty),
            "price": str(fill.price),
            "fee": str(fee),
            "key": idempotency_key,
        }
        return EngineResult(account, (fill,), tuple(postings), ((event, detail),), new_equity)


def apply_funding(
    account: Account,
    quotes: dict[str, Quote],
    instruments: dict[str, Instrument],
    rates: dict[str, Decimal],
    rules: Rules | None = None,
    *,
    as_of: date | None = None,
    funding_prices: dict[str, Decimal] | None = None,
) -> EngineResult:
    """Apply historical per-symbol funding rates using captured oracle prices.

    Funding notional is a paper approximation because the oracle is sampled shortly
    before the settlement boundary. A positive rate charges longs and credits shorts.
    """
    rules = rules or Rules()
    validate_rules(rules)
    account = deepcopy(account)
    rates = dict(rates)
    prices = dict(funding_prices or {})
    if set(rates) != set(prices):
        raise FinanceError("funding rates and oracle prices must have matching symbols")
    if not set(rates).issubset(account.positions):
        raise FinanceError("funding evidence includes a symbol not held by the account")
    with localcontext() as ctx:
        ctx.prec = 60
        total = ZERO
        postings: list[Posting] = []
        for symbol in sorted(rates):
            rate = rates[symbol]
            _decimal(rate, f"{symbol} funding rate")
            position = account.positions[symbol]
            funding_price = prices[symbol]
            _positive(funding_price, "funding oracle price")
            instrument = instruments.get(symbol)
            if instrument is None:
                raise FinanceError(f"funding instrument {symbol} is missing")
            payment = funding_payment_amount(
                position, rate, funding_price, instrument.contract_multiplier
            )
            total = money(total + payment)
            postings.extend((Posting("cash", payment), Posting("funding_income", money(-payment))))
        account.cash = money(account.cash + total)
        account.funding = money(account.funding + total)
        if sum((p.amount for p in postings), ZERO) != ZERO:
            raise FinanceError("funding postings do not balance")
        held_quotes = (quotes[symbol] for symbol in account.positions if symbol in quotes)
        complete_marks = set(account.positions).issubset(quotes) and quote_set_is_trusted(
            held_quotes, set(account.positions), rules
        )
        value = equity(account, quotes, instruments) if complete_marks else None
        if value is not None:
            account, _ = evaluate_risk(account, value, rules, as_of=as_of)
        return EngineResult(
            account,
            (),
            tuple(postings),
            (("FUNDING", {"amount": str(total), "symbols": str(len(rates))}),),
            value,
        )


def protective_exit(
    account: Account,
    symbol: str,
    quote: Quote,
    instrument: Instrument,
    rules: Rules,
    *,
    current_quotes: dict[str, Quote] | None = None,
    current_instruments: dict[str, Instrument] | None = None,
    idempotency_key: str | None = None,
    as_of: date | None = None,
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
        idempotency_key=idempotency_key or f"protective:{symbol}",
        current_quotes=current_quotes,
        current_instruments=current_instruments,
        as_of=as_of,
    )
    event = "STOP_TRIGGERED" if stop_hit else "TP_TRIGGERED"
    return EngineResult(
        result.account,
        result.fills,
        result.postings,
        ((event, {"symbol": symbol, "trigger": str(stop if stop_hit else target)}), *result.events),
        result.equity,
    )


def estimated_liquidation_required(
    account: Account,
    quotes: dict[str, Quote],
    instruments: dict[str, Instrument],
    rules: Rules,
) -> bool:
    """Return a conservative cross-margin trigger estimate, not venue liquidation math."""
    validate_rules(rules)
    if not account.positions:
        return False
    if not set(account.positions).issubset(quotes) or not set(account.positions).issubset(
        instruments
    ):
        raise FinanceError("fresh marks for every open position are required for liquidation")
    held_quotes = {symbol: quotes[symbol] for symbol in account.positions}
    if not quote_set_is_trusted(held_quotes.values(), set(account.positions), rules):
        raise FinanceError("fresh trusted held-symbol quotes are required for liquidation")
    with localcontext() as ctx:
        ctx.prec = 60
        marked_equity = equity(account, quotes, instruments)
        maintenance = money(
            sum(
                (
                    position.quantity
                    * quotes[symbol].mark
                    * instruments[symbol].contract_multiplier
                    * rules.maintenance_margin_rate
                    for symbol, position in account.positions.items()
                ),
                ZERO,
            )
        )
        estimated_exit_fees = money(
            sum(
                (
                    position.quantity
                    * quotes[symbol].mark
                    * instruments[symbol].contract_multiplier
                    * (rules.commission_rate + rules.liquidation_fee_rate)
                    for symbol, position in account.positions.items()
                ),
                ZERO,
            )
        )
        return marked_equity <= maintenance + estimated_exit_fees


def liquidate_cross_margin_estimate(
    account: Account,
    quotes: dict[str, Quote],
    instruments: dict[str, Instrument],
    rules: Rules,
    *,
    idempotency_prefix: str,
    as_of: date | None = None,
) -> EngineResult | None:
    """Close held positions in symbol order using bid/ask fills when estimated margin fails."""
    if not estimated_liquidation_required(account, quotes, instruments, rules):
        return None
    state = deepcopy(account)
    fills: list[Fill] = []
    postings: list[Posting] = []
    events: list[tuple[str, dict[str, str]]] = []
    for symbol in sorted(state.positions):
        position = state.positions[symbol]
        result = apply_action(
            state,
            action=Action.CLOSE_POSITION,
            symbol=symbol,
            quantity=position.quantity,
            leverage=Decimal("1"),
            quote=quotes[symbol],
            instrument=instruments[symbol],
            rules=rules,
            idempotency_key=f"{idempotency_prefix}:{symbol}",
            current_quotes=quotes,
            current_instruments=instruments,
            liquidation=True,
            as_of=as_of,
        )
        state = result.account
        fills.extend(result.fills)
        postings.extend(result.postings)
        events.append(
            (
                "ESTIMATED_CROSS_MARGIN_LIQUIDATION",
                {"symbol": symbol, "basis": "conservative_cross_margin_approximation"},
            )
        )
        events.extend(result.events)
    value = equity(state, quotes, instruments)
    state, _ = evaluate_risk(state, value, rules, as_of=as_of)
    return EngineResult(state, tuple(fills), tuple(postings), tuple(events), value)
