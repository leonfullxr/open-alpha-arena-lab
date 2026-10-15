from __future__ import annotations

import json
import math
from decimal import Decimal

from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    EquitySample,
    LedgerJournal,
    LedgerPosting,
    MarketSnapshot,
    Position,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def agent_metrics(db: Session, competition: Competition, agent: AgentRun) -> dict[str, object]:
    account = db.scalar(select(Account).where(Account.agent_run_id == agent.id))
    if account is None:
        raise LookupError("agent account missing")
    samples = list(
        db.scalars(
            select(EquitySample)
            .where(EquitySample.account_id == account.id)
            .order_by(EquitySample.round_index)
        )
    )
    peak = competition.initial_balance
    max_drawdown = Decimal("0")
    for sample in samples:
        peak = max(peak, sample.equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - sample.equity) / peak * 100)

    posting_rows = db.execute(
        select(LedgerJournal.id, LedgerPosting.amount)
        .join(LedgerPosting, LedgerPosting.journal_id == LedgerJournal.id)
        .where(LedgerJournal.account_id == account.id, LedgerPosting.bucket == "realized_pnl")
    ).all()
    by_trade: dict[str, Decimal] = {}
    for journal_id, amount in posting_rows:
        by_trade[journal_id] = by_trade.get(journal_id, Decimal("0")) - amount
    realized = [value for value in by_trade.values() if value != 0]
    winners = [value for value in realized if value > 0]
    losers = [value for value in realized if value < 0]
    win_rate = Decimal(len(winners)) / Decimal(len(realized)) * 100 if realized else None
    gross_profit = sum(winners, Decimal("0"))
    gross_loss = -sum(losers, Decimal("0"))
    profit_factor = gross_profit / gross_loss if gross_loss else None

    equity_values = [float(sample.equity) for sample in samples]
    returns = [b / a - 1 for a, b in zip(equity_values, equity_values[1:], strict=False) if a > 0]
    sharpe: Decimal | None = None
    if len(returns) >= 3:
        mean = sum(returns) / len(returns)
        deviation = math.sqrt(sum((item - mean) ** 2 for item in returns) / (len(returns) - 1))
        if deviation > 0:
            # Per-round Sharpe: no annualization assumption about missing intervals.
            sharpe = Decimal(str(mean / deviation))

    positions = list(
        db.scalars(
            select(Position).where(Position.account_id == account.id, Position.state == "OPEN")
        )
    )
    current_margin = sum((p.reserved_margin for p in positions), Decimal("0"))
    gross: Decimal | None = Decimal("0")
    if positions:
        latest = db.scalar(
            select(MarketSnapshot)
            .join(DecisionRound, DecisionRound.snapshot_id == MarketSnapshot.id)
            .where(DecisionRound.competition_id == competition.id)
            .order_by(MarketSnapshot.captured_at.desc())
            .limit(1)
        )
        marks = json.loads(latest.canonical_bytes).get("quotes", {}) if latest else {}
        if any(p.symbol not in marks for p in positions):
            gross = None
        else:
            gross = sum(
                (p.quantity * Decimal(str(marks[p.symbol]["mark"])) for p in positions),
                Decimal("0"),
            )
    return {
        "agent_id": agent.id,
        "win_rate_pct": _str(win_rate),
        "profit_factor": _str(profit_factor),
        "max_drawdown_pct": format(max_drawdown, "f"),
        "sharpe_ratio": _str(sharpe),
        "average_leverage": None,
        "current_margin_used": format(current_margin, "f"),
        "current_gross_exposure": _str(gross),
        "closed_trades": len(realized),
        "winning_trades": len(winners),
        "losing_trades": len(losers),
    }


def btc_buy_and_hold(db: Session, competition: Competition) -> dict[str, str] | None:
    snapshots = list(
        db.scalars(
            select(MarketSnapshot)
            .join(DecisionRound, DecisionRound.snapshot_id == MarketSnapshot.id)
            .where(DecisionRound.competition_id == competition.id)
            .order_by(DecisionRound.round_index)
        )
    )
    points: list[tuple[MarketSnapshot, dict[str, str]]] = []
    for snapshot in snapshots:
        quotes = json.loads(snapshot.canonical_bytes).get("quotes", {})
        quote = quotes.get("BTC")
        if isinstance(quote, dict) and quote.get("bid") and quote.get("ask"):
            points.append((snapshot, quote))
    if len(points) < 2:
        return None
    start, start_quote = points[0]
    end, end_quote = points[-1]
    rules = json.loads(competition.rules_bytes)
    fee = Decimal(str(rules.get("commission_rate", rules.get("fee_rate", "0"))))
    slip = Decimal(str(rules.get("slippage_bps", "0"))) / Decimal(10_000)
    entry_price = Decimal(start_quote["ask"]) * (Decimal("1") + slip)
    exit_price = Decimal(end_quote["bid"]) * (Decimal("1") - slip)
    quantity = competition.initial_balance / (entry_price * (Decimal("1") + fee))
    ending_equity = quantity * exit_price * (Decimal("1") - fee)
    roi = (ending_equity / competition.initial_balance - 1) * 100
    return {
        "start_at": start.captured_at.isoformat(),
        "end_at": end.captured_at.isoformat(),
        "start_price": format(entry_price, "f"),
        "end_price": format(exit_price, "f"),
        "equity": format(ending_equity, "f"),
        "roi_pct": format(roi, "f"),
        "fee_rate": format(fee, "f"),
        "slippage_bps": format(Decimal(str(rules.get("slippage_bps", "0"))), "f"),
    }


def _str(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
