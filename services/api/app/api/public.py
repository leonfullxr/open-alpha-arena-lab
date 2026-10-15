from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.public_chart import chart_router
from app.api.public_funding import funding_history, funding_router
from app.api.public_history import bounded_page, decisions, history_router
from app.api.public_metrics import metrics_router
from app.api.public_schemas import (
    AgentSummary,
    CompetitionSummary,
    DecisionDTO,
    EquityPoint,
    EventDTO,
    EventPageDTO,
    ExportDTO,
    LeaderboardRow,
    PageDTO,
    StatusDTO,
    TickerItem,
    public_event_payload,
)
from app.api.public_stream import stream_router
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    DomainEvent,
    EquitySample,
    FundingPayment,
    InvocationAttempt,
    MarketSnapshot,
    Order,
    RoundAgentJob,
)
from app.db.session import get_db

router = APIRouter()
router.include_router(stream_router)
router.include_router(metrics_router)
router.include_router(history_router)
router.include_router(funding_router)
router.include_router(chart_router)


def _competition(db: Session, competition_id: str) -> Competition:
    item = db.get(Competition, competition_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return item


def _agents(db: Session, competition_id: str) -> list[AgentRun]:
    return list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.competition_id == competition_id)
            .order_by(AgentRun.manifest_order)
        )
    )


def _serialize_competition(db: Session, comp: Competition) -> CompetitionSummary:
    return CompetitionSummary(
        id=comp.id,
        name=comp.name,
        profile=comp.profile,
        state=comp.state,
        source_label=comp.source_label,
        initial_balance=str(comp.initial_balance),
        started_at=comp.started_at.isoformat() if comp.started_at else None,
        ended_at=comp.ended_at.isoformat() if comp.ended_at else None,
        agents=[
            AgentSummary(id=a.id, name=a.name, provider=a.provider, model=a.model)
            for a in _agents(db, comp.id)
        ],
    )


def _quote_age(event_at: str) -> tuple[str, bool]:
    try:
        timestamp = datetime.fromisoformat(event_at)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return "unknown", True
        age = (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds()
    except (TypeError, ValueError):
        return "unknown", True
    return str(age), age < 0 or age > 10


@router.get("/status", response_model=StatusDTO)
def status(db: Annotated[Session, Depends(get_db)]) -> StatusDTO:
    return StatusDTO(
        state="ready",
        demo_label="DEMO REPLAY",
        competition_count=db.scalar(select(func.count()).select_from(Competition)) or 0,
        schema_version=1,
    )


@router.get("/ticker", response_model=list[TickerItem])
def ticker(
    db: Annotated[Session, Depends(get_db)], competition_id: str | None = None
) -> list[TickerItem]:
    competition_row = _competition(db, competition_id) if competition_id else None
    if competition_row is not None and not competition_row.source_label.startswith("DEMO REPLAY"):
        snapshot_query = select(MarketSnapshot).where(MarketSnapshot.source_label == "hyperliquid")
    else:
        snapshot_query = (
            select(MarketSnapshot)
            .join(DecisionRound, DecisionRound.snapshot_id == MarketSnapshot.id)
            .join(Competition, Competition.id == DecisionRound.competition_id)
        )
        snapshot_query = snapshot_query.where(
            Competition.id == competition_id
            if competition_id
            else Competition.source_label.like("DEMO REPLAY%")
        )
    snapshot = db.scalar(snapshot_query.order_by(MarketSnapshot.captured_at.desc()).limit(1))
    if snapshot is None:
        return []
    competition = competition_row or db.scalar(
        select(Competition)
        .join(DecisionRound, DecisionRound.competition_id == Competition.id)
        .where(DecisionRound.snapshot_id == snapshot.id)
    )
    source = (
        f"{competition.source_label} · {snapshot.source_label}"
        if competition
        else snapshot.source_label
    )
    try:
        body = json.loads(snapshot.canonical_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    quotes = body.get("quotes") if isinstance(body, dict) else None
    if not isinstance(quotes, dict):
        return []
    items = []
    for symbol, quote in quotes.items():
        if not isinstance(quote, dict) or not all(
            field in quote for field in ("bid", "ask", "mark", "event_at", "received_at")
        ):
            continue
        age, stale = _quote_age(quote["event_at"])
        items.append(
            TickerItem(
                symbol=symbol,
                bid=quote["bid"],
                ask=quote["ask"],
                mark=quote["mark"],
                source=source,
                event_at=quote["event_at"],
                received_at=quote["received_at"],
                age_seconds=age,
                stale=stale,
            )
        )
    return items


@router.get("/competitions", response_model=list[CompetitionSummary])
def competitions(db: Annotated[Session, Depends(get_db)]) -> list[CompetitionSummary]:
    items = db.scalars(
        select(Competition).order_by(Competition.started_at.desc().nullslast(), Competition.id)
    ).all()
    return [_serialize_competition(db, item) for item in items]


@router.get("/competitions/{competition_id}", response_model=CompetitionSummary)
def competition(competition_id: str, db: Annotated[Session, Depends(get_db)]) -> CompetitionSummary:
    return _serialize_competition(db, _competition(db, competition_id))


@router.get("/competitions/{competition_id}/equity", response_model=PageDTO[EquityPoint])
def equity_curve(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
) -> PageDTO[EquityPoint]:
    bounded_page(limit, offset)
    _competition(db, competition_id)
    rows = db.execute(
        select(EquitySample, AgentRun)
        .join(Account, Account.id == EquitySample.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
        .order_by(EquitySample.round_index, AgentRun.manifest_order)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        EquityPoint(
            agent_id=agent.id,
            agent_name=agent.name,
            round=sample.round_index,
            timestamp=sample.logical_at.isoformat(),
            equity=str(sample.equity),
            realized_pnl=str(sample.realized_pnl),
            unrealized_pnl=str(sample.unrealized_pnl),
            fees=str(sample.fees),
            funding=str(sample.funding),
        )
        for sample, agent in rows
    ]
    total = (
        db.scalar(
            select(func.count())
            .select_from(EquitySample)
            .join(Account, Account.id == EquitySample.account_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .where(AgentRun.competition_id == competition_id)
        )
        or 0
    )
    return PageDTO[EquityPoint](items=items, limit=limit, offset=offset, total=total)


@router.get("/competitions/{competition_id}/leaderboard", response_model=list[LeaderboardRow])
def leaderboard(
    competition_id: str, db: Annotated[Session, Depends(get_db)]
) -> list[LeaderboardRow]:
    comp = _competition(db, competition_id)
    rows = []
    for agent in _agents(db, competition_id):
        account = db.scalar(select(Account).where(Account.agent_run_id == agent.id))
        if account is None:
            continue
        sample = db.scalar(
            select(EquitySample)
            .where(EquitySample.account_id == account.id)
            .order_by(EquitySample.round_index.desc())
        )
        current_equity = sample.equity if sample else account.cash
        unrealized = sample.unrealized_pnl if sample else 0
        trade_count = (
            db.scalar(select(func.count()).select_from(Order).where(Order.account_id == account.id))
            or 0
        )
        rows.append(
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "model": agent.model,
                "equity": str(current_equity),
                "roi_pct": str(
                    (current_equity - comp.initial_balance) / comp.initial_balance * 100
                ),
                "realized_pnl": str(account.realized_pnl),
                "unrealized_pnl": str(unrealized),
                "fees": str(account.fees),
                "funding": str(account.funding),
                "trade_count": trade_count,
            }
        )
    rows.sort(key=lambda row: (D(str(row["equity"])), str(row["agent_id"])), reverse=True)
    return [LeaderboardRow(rank=i + 1, **row) for i, row in enumerate(rows)]


@router.get("/competitions/{competition_id}/events", response_model=EventPageDTO)
def events(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> EventPageDTO:
    _competition(db, competition_id)
    rows = db.scalars(
        select(DomainEvent)
        .where(DomainEvent.competition_id == competition_id, DomainEvent.sequence > after)
        .order_by(DomainEvent.sequence)
        .limit(limit + 1)
    ).all()
    account_agent_ids = db.execute(
        select(Account.id, AgentRun.id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
    ).all()
    agent_by_account = {account_id: agent_id for account_id, agent_id in account_agent_ids}
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        EventDTO(
            sequence=e.sequence,
            event_type=e.event_type,
            event_at=e.event_at.isoformat(),
            agent_id=(agent_by_account.get(e.account_id) if e.account_id is not None else None),
            payload=public_event_payload(e.payload),
        )
        for e in rows
    ]
    return EventPageDTO(
        items=items,
        after=after,
        next_after=items[-1].sequence if items else after,
        has_more=has_more,
    )


@router.get("/competitions/{competition_id}/export", response_model=ExportDTO)
def export_competition(
    competition_id: str, db: Annotated[Session, Depends(get_db)], limit: int = Query(2000)
) -> ExportDTO:
    if not 1 <= limit <= 2000:
        raise HTTPException(status_code=422, detail="limit must be 1..2000")
    comp = _competition(db, competition_id)
    equity_rows: list[EquityPoint] = []
    decision_rows: list[DecisionDTO] = []
    funding_rows = []
    for offset in range(0, limit, 200):
        page_size = min(200, limit - offset)
        equity_rows.extend(equity_curve(competition_id, db, limit=page_size, offset=offset).items)
        decision_rows.extend(
            decisions(
                competition_id,
                db,
                limit=page_size,
                offset=offset,
                agent_id=None,
                symbol=None,
            ).items
        )
        funding_rows.extend(
            funding_history(
                competition_id,
                db,
                limit=page_size,
                offset=offset,
                agent_id=None,
                symbol=None,
            ).items
        )
    total_equity = (
        db.scalar(
            select(func.count())
            .select_from(EquitySample)
            .join(Account, Account.id == EquitySample.account_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .where(AgentRun.competition_id == competition_id)
        )
        or 0
    )
    total_decisions = (
        db.scalar(
            select(func.count())
            .select_from(RoundAgentJob)
            .outerjoin(InvocationAttempt, InvocationAttempt.job_id == RoundAgentJob.id)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .where(
                DecisionRound.competition_id == competition_id,
                or_(InvocationAttempt.id.is_not(None), RoundAgentJob.state == "TERMINAL"),
            )
        )
        or 0
    )
    total_funding = (
        db.scalar(
            select(func.count())
            .select_from(FundingPayment)
            .join(Account, Account.id == FundingPayment.account_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .where(AgentRun.competition_id == competition_id)
        )
        or 0
    )
    return ExportDTO(
        competition=_serialize_competition(db, comp),
        leaderboard=leaderboard(competition_id, db),
        equity=equity_rows,
        decisions=decision_rows,
        funding=funding_rows,
        truncated=(
            total_equity > len(equity_rows)
            or total_decisions > len(decision_rows)
            or total_funding > len(funding_rows)
        ),
        exported_decisions=len(decision_rows),
        exported_equity_points=len(equity_rows),
        exported_funding_payments=len(funding_rows),
    )
