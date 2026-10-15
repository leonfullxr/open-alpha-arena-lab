from decimal import Decimal as D

import pytest
from app.engine.finance import (
    Account,
    Action,
    FinanceError,
    Instrument,
    Quote,
    Rules,
    Side,
    apply_action,
    apply_funding,
    equity,
    estimated_liquidation_required,
    evaluate_risk,
    funding_payment_amount,
    liquidate_cross_margin_estimate,
    money,
    protective_exit,
    quote_set_is_trusted,
    rules_from_config,
    unrealized_pnl,
)
from app.engine.finance import (
    Position as EnginePosition,
)


def test_long_and_short_fill_at_executable_side_and_close_profitably() -> None:
    rules = Rules(commission_rate=D("0"), slippage_bps=D("0"))
    inst = Instrument("BTC")
    long = Account.create(D("10000"))
    opened = apply_action(
        long,
        action=Action.OPEN_LONG,
        symbol="BTC",
        quantity=D("1"),
        leverage=D("2"),
        quote=Quote("BTC", D("99"), D("101"), D("100")),
        instrument=inst,
        rules=rules,
        idempotency_key="open-long",
    )
    assert opened.fills[0].price == D("101")
    assert opened.account.reserved_margin == D("50.500000000000000000")
    closed = apply_action(
        opened.account,
        action=Action.CLOSE_POSITION,
        symbol="BTC",
        quantity=D("0"),
        leverage=D("1"),
        quote=Quote("BTC", D("110"), D("111"), D("110")),
        instrument=inst,
        rules=rules,
        idempotency_key="close-long",
    )
    assert closed.account.cash == D("10009.000000000000000000")
    assert closed.account.realized_pnl == D("9.000000000000000000")
    assert not closed.account.positions

    short = Account.create(D("10000"))
    short_open = apply_action(
        short,
        action=Action.OPEN_SHORT,
        symbol="BTC",
        quantity=D("1"),
        leverage=D("2"),
        quote=Quote("BTC", D("99"), D("101"), D("100")),
        instrument=inst,
        rules=rules,
        idempotency_key="open-short",
    )
    short_close = apply_action(
        short_open.account,
        action=Action.CLOSE_POSITION,
        symbol="BTC",
        quantity=D("0"),
        leverage=D("1"),
        quote=Quote("BTC", D("90"), D("91"), D("90")),
        instrument=inst,
        rules=rules,
        idempotency_key="close-short",
    )
    assert short_close.account.cash == D("10008.000000000000000000")


def test_fees_funding_and_reserved_margin_do_not_reduce_equity() -> None:
    account = Account.create(D("10000"))
    quote = Quote("ETH", D("1999"), D("2001"), D("2000"))
    instrument = Instrument("ETH")
    rules = Rules(commission_rate=D("0.001"), slippage_bps=D("0"))
    result = apply_action(
        account,
        action=Action.OPEN_LONG,
        symbol="ETH",
        quantity=D("1"),
        leverage=D("2"),
        quote=quote,
        instrument=instrument,
        rules=rules,
        idempotency_key="eth-open",
    )
    assert result.account.cash == D("9997.999000000000000000")
    assert result.account.reserved_margin == D("1000.500000000000000000")
    assert result.equity == D("9996.999000000000000000")  # spread mark plus the opening fee
    funded = apply_funding(
        result.account,
        {"ETH": quote},
        {"ETH": instrument},
        {"ETH": D("0.001")},
        funding_prices={"ETH": D("2000")},
    )
    assert funded.account.funding == D("-2.000000000000000000")
    assert funded.account.cash == D("9995.999000000000000000")
    reversed_funding = apply_funding(
        result.account,
        {"ETH": quote},
        {"ETH": instrument},
        {"ETH": D("-0.001")},
        funding_prices={"ETH": D("2000")},
    )
    assert reversed_funding.account.funding == D("2.000000000000000000")
    assert sum(p.amount for p in result.postings) == 0
    assert sum(p.amount for p in funded.postings) == 0


def test_historical_funding_accepts_subset_rates_and_signed_per_symbol_payments() -> None:
    account = Account.create(D("10000"))
    account.positions = {
        "BTC": EnginePosition("BTC", Side.LONG, D("2"), D("100"), D("40")),
        "ETH": EnginePosition("ETH", Side.SHORT, D("1.5"), D("50"), D("20")),
        "SOL": EnginePosition("SOL", Side.LONG, D("3"), D("10"), D("6")),
    }
    result = apply_funding(
        account,
        {},
        {"BTC": Instrument("BTC"), "ETH": Instrument("ETH", contract_multiplier=D("0.1"))},
        {"BTC": D("0.01"), "ETH": D("-0.02")},
        funding_prices={"BTC": D("100"), "ETH": D("200")},
    )
    assert result.account.funding == D("-2.600000000000000000")
    assert result.account.cash == D("9997.400000000000000000")
    assert result.account.positions["SOL"].quantity == D("3")
    assert result.equity is None
    assert sum(posting.amount for posting in result.postings) == D("0")
    assert account.funding == D("0")
    assert funding_payment_amount(
        account.positions["ETH"], D("-0.02"), D("200"), D("0.1")
    ) == D("-0.600000000000000000")
    with pytest.raises(FinanceError, match="matching symbols"):
        apply_funding(
            account,
            {},
            {"BTC": Instrument("BTC")},
            {"BTC": D("0.01")},
            funding_prices={"ETH": D("100")},
        )


def test_decimal_money_accepts_numeric_boundary_and_rejects_overflow() -> None:
    maximum = D("99999999999999999999.999999999999999999")
    assert money(maximum) == maximum
    with pytest.raises(FinanceError, match=r"numeric\(38,18\)"):
        money(D("100000000000000000000"))


def test_rejects_unsafe_size_precision_stop_and_duplicate_baseline_entry() -> None:
    account = Account.create(D("100"))
    inst = Instrument("X", min_notional=D("10"))
    quote = Quote("X", D("9.99"), D("10"), D("10"))
    rules = Rules(max_leverage=D("2"), max_order_notional=D("50"))
    with pytest.raises(FinanceError, match="maximum notional"):
        apply_action(
            account,
            action=Action.OPEN_LONG,
            symbol="X",
            quantity=D("6"),
            leverage=D("2"),
            quote=quote,
            instrument=inst,
            rules=rules,
            idempotency_key="too-big",
        )
    with pytest.raises(FinanceError, match="wrong side"):
        apply_action(
            account,
            action=Action.OPEN_LONG,
            symbol="X",
            quantity=D("1"),
            leverage=D("2"),
            quote=quote,
            instrument=inst,
            rules=rules,
            stop_loss=D("11"),
            idempotency_key="bad-stop",
        )
    opened = apply_action(
        account,
        action=Action.OPEN_LONG,
        symbol="X",
        quantity=D("1"),
        leverage=D("2"),
        quote=quote,
        instrument=inst,
        rules=rules,
        idempotency_key="ok",
    )
    with pytest.raises(FinanceError, match="pyramiding"):
        apply_action(
            opened.account,
            action=Action.OPEN_LONG,
            symbol="X",
            quantity=D("1"),
            leverage=D("2"),
            quote=quote,
            instrument=inst,
            rules=rules,
            idempotency_key="duplicate",
        )
    with pytest.raises(FinanceError, match="finite Decimal"):
        apply_action(
            account,
            action=Action.OPEN_LONG,
            symbol="X",
            quantity=D("NaN"),
            leverage=D("2"),
            quote=quote,
            instrument=inst,
            rules=rules,
            idempotency_key="nan",
        )


def test_gap_stop_uses_executable_quote_and_fresh_complete_set_is_enforced() -> None:
    account = Account.create(D("10000"))
    inst = Instrument("BTC")
    rules = Rules(commission_rate=D("0"), slippage_bps=D("0"))
    opened = apply_action(
        account,
        action=Action.OPEN_LONG,
        symbol="BTC",
        quantity=D("1"),
        leverage=D("2"),
        quote=Quote("BTC", D("99"), D("100"), D("99.5")),
        instrument=inst,
        rules=rules,
        stop_loss=D("95"),
        idempotency_key="stop-open",
    )
    exit_result = protective_exit(
        opened.account, "BTC", Quote("BTC", D("90"), D("92"), D("91")), inst, rules
    )
    assert exit_result is not None
    assert exit_result.fills[0].price == D("90")
    assert exit_result.account.realized_pnl == D("-10.000000000000000000")
    assert not quote_set_is_trusted(
        [Quote("BTC", D("1"), D("2"), D("1.5"), D("11"), D("1"))], {"BTC"}, rules
    )
    assert not quote_set_is_trusted(
        [
            Quote("BTC", D("1"), D("2"), D("1.5")),
            Quote("ETH", D("1"), D("2"), D("1.5"), event_seconds=D("6")),
        ],
        {"BTC", "ETH"},
        rules,
    )


def test_unrealized_pnl_signs_and_profit_includes_mark() -> None:
    long = Account.create(D("1000"))
    p = apply_action(
        long,
        action=Action.OPEN_SHORT,
        symbol="X",
        quantity=D("2"),
        leverage=D("2"),
        quote=Quote("X", D("99"), D("100"), D("100")),
        instrument=Instrument("X"),
        rules=Rules(commission_rate=D("0"), slippage_bps=D("0")),
        idempotency_key="s",
    )
    position = p.account.positions["X"]
    assert unrealized_pnl(position, D("90")) == D("18.000000000000000000")
    assert equity(
        p.account, {"X": Quote("X", D("89"), D("91"), D("90"))}, {"X": Instrument("X")}
    ) == D("1018.000000000000000000")


def test_close_pnl_uses_slipped_fill_and_hold_marks_every_position() -> None:
    account = Account.create(D("10000"))
    rules = Rules(commission_rate=D("0"), slippage_bps=D("10"))
    btc = Instrument("BTC")
    eth = Instrument("ETH")
    opened = apply_action(
        account,
        action=Action.OPEN_LONG,
        symbol="BTC",
        quantity=D("1"),
        leverage=D("2"),
        quote=Quote("BTC", D("99"), D("100"), D("100")),
        instrument=btc,
        rules=rules,
        idempotency_key="btc-open",
    )
    closed = apply_action(
        opened.account,
        action=Action.CLOSE_POSITION,
        symbol="BTC",
        quantity=D("0"),
        leverage=D("1"),
        quote=Quote("BTC", D("110"), D("111"), D("110")),
        instrument=btc,
        rules=rules,
        idempotency_key="btc-close",
    )
    assert closed.fills[0].price == D("109.890")
    assert closed.account.realized_pnl == D("9.790000000000000000")
    assert "BTC" in opened.account.positions

    multi = Account.create(D("10000"))
    multi.positions["BTC"] = EnginePosition("BTC", Side.LONG, D("1"), D("100.1"), D("50.05"))
    multi.positions["ETH"] = EnginePosition("ETH", Side.SHORT, D("1"), D("50"), D("25"))
    full_quotes = {
        "BTC": Quote("BTC", D("101"), D("102"), D("101")),
        "ETH": Quote("ETH", D("49"), D("50"), D("49")),
        "SOL": Quote("SOL", D("10"), D("11"), D("10.5")),
    }
    instruments = {"BTC": btc, "ETH": eth, "SOL": Instrument("SOL")}
    hold = apply_action(
        multi,
        action=Action.HOLD,
        symbol="SOL",
        quantity=D("0"),
        leverage=D("1"),
        quote=full_quotes["SOL"],
        instrument=instruments["SOL"],
        rules=rules,
        idempotency_key="hold",
        current_quotes=full_quotes,
        current_instruments=instruments,
    )
    assert hold.equity == D("10001.900000000000000000")
    with pytest.raises(FinanceError, match="fresh marks"):
        apply_action(
            multi,
            action=Action.HOLD,
            symbol="SOL",
            quantity=D("0"),
            leverage=D("1"),
            quote=full_quotes["SOL"],
            instrument=instruments["SOL"],
            rules=rules,
            idempotency_key="hold-missing",
        )


def test_quote_set_rejects_duplicate_future_and_nonfinite_values() -> None:
    rules = Rules()
    valid = Quote("BTC", D("99"), D("100"), D("99.5"))
    assert not quote_set_is_trusted([valid, valid], {"BTC"}, rules)
    assert not quote_set_is_trusted(
        [Quote("BTC", D("99"), D("100"), D("99.5"), age_seconds=D("-0.1"))],
        {"BTC"},
        rules,
    )
    assert not quote_set_is_trusted([Quote("BTC", D("NaN"), D("100"), D("99.5"))], {"BTC"}, rules)
    with pytest.raises(FinanceError, match="instrument precision"):
        apply_action(
            Account.create(D("1000")),
            action=Action.OPEN_LONG,
            symbol="BTC",
            quantity=D("0.0000001"),
            leverage=D("2"),
            quote=Quote("BTC", D("99"), D("100"), D("100")),
            instrument=Instrument("BTC"),
            rules=rules,
            idempotency_key="off-step",
        )


def test_frozen_rules_apply_entry_limits_and_risk_halt_keeps_closes_available() -> None:
    cfg = {
        "commission_rate": "0",
        "slippage_bps": "0",
        "leverage_max": "2",
        "max_notional": "500",
        "max_gross_exposure": "150",
        "maintenance_margin_rate": "0.01",
        "max_positions": 6,
        "quote_max_age_seconds": "10",
        "quote_set_max_skew_seconds": "5",
        "max_daily_loss": "100",
        "max_drawdown_fraction": "0.1",
        "allow_pyramiding": False,
        "liquidation_fee_rate": "0.005",
        "funding_mode": "hourly_historical_rate",
        "funding_interval_hours": 1,
        "funding_history_max_offset_seconds": 5,
        "funding_rate_basis": "funding_history",
        "funding_price_basis": "oracle_px",
        "fixture_funding_rate_per_hour": "0",
        "risk_policy_version": "risk-v1",
        "snapshot_schema_version": 1,
        "proposal_schema_version": 1,
        "public_evidence_schema_version": 1,
        "market_window_candles": 12,
        "indicator_policy": "trailing_500_v1",
        "indicator_warmup_bars": 500,
    }
    rules = rules_from_config(cfg)
    future_schema = dict(cfg, proposal_schema_version=2)
    with pytest.raises(FinanceError, match="schema"):
        rules_from_config(future_schema)
    future_indicator = dict(cfg, indicator_policy="trailing_100_v1")
    with pytest.raises(FinanceError, match="schema"):
        rules_from_config(future_indicator)
    quote = Quote("BTC", D("99"), D("100"), D("100"))
    with pytest.raises(FinanceError, match="leverage"):
        apply_action(
            Account.create(D("1000")),
            action=Action.OPEN_LONG,
            symbol="BTC",
            quantity=D("1"),
            leverage=D("3"),
            quote=quote,
            instrument=Instrument("BTC"),
            rules=rules,
            idempotency_key="too-much-leverage",
        )
    with pytest.raises(FinanceError, match="collateral"):
        apply_action(
            Account.create(D("40")),
            action=Action.OPEN_LONG,
            symbol="BTC",
            quantity=D("1"),
            leverage=D("1"),
            quote=quote,
            instrument=Instrument("BTC"),
            rules=rules,
            idempotency_key="insufficient-collateral",
        )
    account = Account.create(D("1000"))
    first = apply_action(
        account,
        action=Action.OPEN_LONG,
        symbol="BTC",
        quantity=D("1"),
        leverage=D("2"),
        quote=quote,
        instrument=Instrument("BTC"),
        rules=rules,
        idempotency_key="first-entry",
    )
    eth_quote = Quote("ETH", D("99"), D("100"), D("100"))
    with pytest.raises(FinanceError, match="gross exposure"):
        apply_action(
            first.account,
            action=Action.OPEN_LONG,
            symbol="ETH",
            quantity=D("1"),
            leverage=D("2"),
            quote=eth_quote,
            instrument=Instrument("ETH"),
            rules=rules,
            idempotency_key="gross-limit",
            current_quotes={"BTC": quote},
            current_instruments={"BTC": Instrument("BTC")},
        )

    assert first.account.risk_day is not None
    halted, reasons = evaluate_risk(first.account, D("800"), rules, as_of=first.account.risk_day)
    assert reasons == ("MAX_DAILY_LOSS", "MAX_DRAWDOWN")
    assert halted.halted
    with pytest.raises(FinanceError, match="halted"):
        apply_action(
            halted,
            action=Action.OPEN_LONG,
            symbol="ETH",
            quantity=D("1"),
            leverage=D("2"),
            quote=eth_quote,
            instrument=Instrument("ETH"),
            rules=rules,
            idempotency_key="halted-entry",
        )
    closed = apply_action(
        halted,
        action=Action.CLOSE_POSITION,
        symbol="BTC",
        quantity=D("0"),
        leverage=D("1"),
        quote=Quote("BTC", D("99"), D("100"), D("99")),
        instrument=Instrument("BTC"),
        rules=rules,
        idempotency_key="risk-exit",
    )
    assert not closed.account.positions


def test_protective_close_allows_missing_other_mark_and_estimated_liquidation_is_explicit():
    rules = Rules(commission_rate=D("0"), slippage_bps=D("0"))
    account = Account.create(D("1000"))
    account.positions["BTC"] = EnginePosition(
        "BTC", Side.LONG, D("1"), D("100"), D("50"), stop_loss=D("95")
    )
    account.positions["ETH"] = EnginePosition("ETH", Side.SHORT, D("1"), D("50"), D("25"))
    exit_result = protective_exit(
        account,
        "BTC",
        Quote("BTC", D("90"), D("92"), D("91")),
        Instrument("BTC"),
        rules,
        idempotency_key="protective:position-1:quote-set-1",
    )
    assert exit_result is not None
    assert exit_result.equity is None
    assert set(exit_result.account.positions) == {"ETH"}
    assert exit_result.fills[0].price == D("90")

    distressed = Account.create(D("20"))
    distressed.positions["BTC"] = EnginePosition("BTC", Side.LONG, D("1"), D("100"), D("50"))
    distress_quotes = {"BTC": Quote("BTC", D("0.9"), D("1"), D("1"))}
    instruments = {"BTC": Instrument("BTC")}
    liquidation_rules = Rules(commission_rate=D("0"), slippage_bps=D("0"))
    assert estimated_liquidation_required(
        distressed, distress_quotes, instruments, liquidation_rules
    )
    result = liquidate_cross_margin_estimate(
        distressed,
        distress_quotes,
        instruments,
        liquidation_rules,
        idempotency_prefix="risk:quote-set-1",
    )
    assert result is not None
    assert not result.account.positions
    assert result.events[0][0] == "ESTIMATED_CROSS_MARGIN_LIQUIDATION"


def test_reserved_margin_aggregation_rejects_numeric_38_18_overflow() -> None:
    largest = D("99999999999999999999.999999999999999999")
    account = Account(
        initial_balance=D("1000"),
        cash=D("1000"),
        positions={
            "BTC": EnginePosition("BTC", Side.LONG, D("1"), D("1"), largest),
            "ETH": EnginePosition("ETH", Side.SHORT, D("1"), D("1"), largest),
        },
    )
    with pytest.raises(FinanceError, match=r"numeric\(38,18\)"):
        _ = account.reserved_margin
