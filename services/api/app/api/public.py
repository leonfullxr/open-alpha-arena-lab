from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal as D
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    DomainEvent,
    EquitySample,
    Fill,
    InvocationAttempt,
    InvocationResult,
    MarketSnapshot,
    Order,
    Position,
    RoundAgentJob,
)
from app.db.session import SessionLocal, get_db

router = APIRouter()


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ItemT = TypeVar("ItemT")


class PageDTO[ItemT](PublicModel):
    items: list[ItemT]
    limit: int
    offset: int
    total: int


class StatusDTO(PublicModel):
    state: str
    demo_label: str
    competition_count: int
    schema_version: int


class TickerItem(PublicModel):
    symbol: str
    bid: str
    ask: str
    mark: str
    source: str
    event_at: str
    received_at: str


class AgentSummary(PublicModel):
    id: str
    name: str
    provider: str
    model: str


class CompetitionSummary(PublicModel):
    id: str
    name: str
    profile: str
    state: str
    source_label: str
    initial_balance: str
    started_at: str | None
    ended_at: str | None
    agents: list[AgentSummary]


class EquityPoint(PublicModel):
    agent_id: str
    agent_name: str
    round: int
    timestamp: str
    equity: str
    realized_pnl: str
    unrealized_pnl: str
    fees: str
    funding: str


class LeaderboardRow(PublicModel):
    rank: int
    agent_id: str
    agent_name: str
    model: str
    equity: str
    roi_pct: str
    realized_pnl: str
    unrealized_pnl: str
    fees: str
    funding: str
    trade_count: int


class EventDTO(PublicModel):
    sequence: int
    event_type: str
    event_at: str
    agent_id: str | None
    payload: PublicEventPayload


class EventPageDTO(PublicModel):
    items: list[EventDTO]
    after: int
    next_after: int
    has_more: bool


class PublicEventPayload(PublicModel):
    agent_id: str | None = None
    round: int | None = None
    action: str | None = None
    source: str | None = None
    symbol: str | None = None
    quantity: str | None = None
    price: str | None = None
    fee: str | None = None
    reason: str | None = None


def _public_event_payload(value: dict[str, Any]) -> PublicEventPayload:
    allowed = {
        "agent_id",
        "round",
        "action",
        "source",
        "symbol",
        "quantity",
        "price",
        "fee",
        "reason",
    }
    return PublicEventPayload.model_validate(
        {key: item for key, item in value.items() if key in allowed}
    )


class DecisionDTO(PublicModel):
    id: str
    agent_id: str
    agent_name: str
    round: int
    action: str
    symbol: str
    quantity: str
    justification: str
    market_summary: str
    prompt_sha256: str
    output_sha256: str
    artifact_url: str
    provider: str
    model: str


class PositionDTO(PublicModel):
    agent_id: str
    agent_name: str
    symbol: str
    side: str
    quantity: str
    average_entry: str
    reserved_margin: str
    stop_loss: str | None
    take_profit: str | None
    state: str


class TradeDTO(PublicModel):
    agent_id: str
    agent_name: str
    symbol: str
    side: str
    quantity: str
    price: str
    fee: str
    order_id: str
    status: str


class ModelDTO(PublicModel):
    id: str
    name: str
    provider: str
    model: str
    status: str
    source_label: str
    api_key_configured: bool


class ExportDTO(PublicModel):
    competition: CompetitionSummary
    leaderboard: list[LeaderboardRow]
    equity: list[EquityPoint]
    decisions: list[DecisionDTO]
    truncated: bool
    exported_decisions: int
    exported_equity_points: int


class ArtifactDTO(PublicModel):
    id: str
    prompt_sha256: str
    output_sha256: str
    prompt_bytes_base64: str
    output_bytes_base64: str


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


def bounded_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
        raise HTTPException(status_code=422, detail="limit must be 1..200 and offset 0..100000")


@router.get("/status", response_model=StatusDTO)
def status(db: Annotated[Session, Depends(get_db)]) -> StatusDTO:
    return StatusDTO(
        state="ready",
        demo_label="DEMO REPLAY",
        competition_count=db.scalar(select(func.count()).select_from(Competition)) or 0,
        schema_version=1,
    )


@router.get("/ticker", response_model=list[TickerItem])
def ticker(db: Annotated[Session, Depends(get_db)]) -> list[TickerItem]:
    snapshot = db.scalar(select(MarketSnapshot).order_by(MarketSnapshot.captured_at.desc()))
    if snapshot is None:
        return []
    body = json.loads(snapshot.canonical_bytes)
    return [
        TickerItem(
            symbol=s,
            bid=q["bid"],
            ask=q["ask"],
            mark=q["mark"],
            source="DEMO REPLAY · fixture-replay-v1",
            event_at=q["event_at"],
            received_at=q["received_at"],
        )
        for s, q in body["quotes"].items()
    ]


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
    agents = {a.id: a for a in _agents(db, competition_id)}
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        EventDTO(
            sequence=e.sequence,
            event_type=e.event_type,
            event_at=e.event_at.isoformat(),
            agent_id=next(
                (
                    a.id
                    for a in agents.values()
                    if db.scalar(select(Account.id).where(Account.agent_run_id == a.id))
                    == e.account_id
                ),
                None,
            ),
            payload=_public_event_payload(e.payload),
        )
        for e in rows
    ]
    return EventPageDTO(
        items=items,
        after=after,
        next_after=items[-1].sequence if items else after,
        has_more=has_more,
    )


@router.get("/competitions/{competition_id}/decisions", response_model=PageDTO[DecisionDTO])
def decisions(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
) -> PageDTO[DecisionDTO]:
    bounded_page(limit, offset)
    _competition(db, competition_id)
    rows = db.execute(
        select(InvocationAttempt, InvocationResult, RoundAgentJob, DecisionRound, AgentRun)
        .join(InvocationResult, InvocationResult.attempt_id == InvocationAttempt.id)
        .join(RoundAgentJob, RoundAgentJob.id == InvocationAttempt.job_id)
        .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
        .join(AgentRun, AgentRun.id == RoundAgentJob.agent_run_id)
        .where(DecisionRound.competition_id == competition_id)
        .order_by(DecisionRound.round_index, AgentRun.manifest_order)
        .offset(offset)
        .limit(limit)
    ).all()
    items = []
    for artifact, result, _job, round_row, agent in rows:
        output = json.loads(result.output_bytes)
        items.append(
            DecisionDTO(
                id=artifact.id,
                agent_id=agent.id,
                agent_name=agent.name,
                round=round_row.round_index,
                action=output["action"],
                symbol=output["symbol"],
                quantity=output["quantity"],
                justification=output["justification"],
                market_summary=output["market_summary"],
                prompt_sha256=artifact.prompt_sha256,
                output_sha256=result.output_sha256,
                artifact_url=f"/api/v1/public/decisions/{artifact.id}/artifact",
                provider=agent.provider,
                model=agent.model,
            )
        )
    total = (
        db.scalar(
            select(func.count())
            .select_from(InvocationAttempt)
            .join(InvocationResult, InvocationResult.attempt_id == InvocationAttempt.id)
            .join(RoundAgentJob, RoundAgentJob.id == InvocationAttempt.job_id)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .where(DecisionRound.competition_id == competition_id)
        )
        or 0
    )
    return PageDTO[DecisionDTO](items=items, limit=limit, offset=offset, total=total)


@router.get("/decisions/{decision_id}/artifact", response_model=ArtifactDTO)
def artifact(decision_id: str, db: Annotated[Session, Depends(get_db)]) -> ArtifactDTO:
    import base64

    item = db.get(InvocationAttempt, decision_id)
    result = db.scalar(select(InvocationResult).where(InvocationResult.attempt_id == decision_id))
    if item is None or result is None:
        raise HTTPException(status_code=404, detail="Decision artifact not found")
    return ArtifactDTO(
        id=item.id,
        prompt_sha256=item.prompt_sha256,
        output_sha256=result.output_sha256,
        prompt_bytes_base64=base64.b64encode(item.prompt_bytes).decode(),
        output_bytes_base64=base64.b64encode(result.output_bytes).decode(),
    )


@router.get("/competitions/{competition_id}/positions", response_model=PageDTO[PositionDTO])
def positions(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
    include_closed: bool = False,
) -> PageDTO[PositionDTO]:
    bounded_page(limit, offset)
    _competition(db, competition_id)
    query = (
        select(Position, AgentRun)
        .join(Account, Account.id == Position.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
    )
    query = query.where(AgentRun.competition_id == competition_id)
    if not include_closed:
        query = query.where(Position.state == "OPEN")
    rows = db.execute(
        query.order_by(AgentRun.manifest_order, Position.symbol).offset(offset).limit(limit)
    ).all()
    items = [
        PositionDTO(
            agent_id=a.id,
            agent_name=a.name,
            symbol=p.symbol,
            side=p.side,
            quantity=str(p.quantity),
            average_entry=str(p.average_entry),
            reserved_margin=str(p.reserved_margin),
            stop_loss=str(p.stop_loss) if p.stop_loss is not None else None,
            take_profit=str(p.take_profit) if p.take_profit is not None else None,
            state=p.state,
        )
        for p, a in rows
    ]
    count_query = (
        select(func.count())
        .select_from(Position)
        .join(Account, Account.id == Position.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
    )
    if not include_closed:
        count_query = count_query.where(Position.state == "OPEN")
    total = db.scalar(count_query) or 0
    return PageDTO[PositionDTO](items=items, limit=limit, offset=offset, total=total)


@router.get("/competitions/{competition_id}/trades", response_model=PageDTO[TradeDTO])
def trades(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
) -> PageDTO[TradeDTO]:
    bounded_page(limit, offset)
    _competition(db, competition_id)
    rows = db.execute(
        select(Fill, Order, Account, AgentRun)
        .join(Order, Order.id == Fill.order_id)
        .join(Account, Account.id == Order.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
        .order_by(Fill.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        TradeDTO(
            agent_id=a.id,
            agent_name=a.name,
            symbol=f.symbol,
            side=f.side,
            quantity=str(f.quantity),
            price=str(f.price),
            fee=str(f.fee),
            order_id=o.id,
            status=o.status,
        )
        for f, o, _, a in rows
    ]
    total = (
        db.scalar(
            select(func.count())
            .select_from(Fill)
            .join(Order, Order.id == Fill.order_id)
            .join(Account, Account.id == Order.account_id)
            .join(AgentRun, AgentRun.id == Account.agent_run_id)
            .where(AgentRun.competition_id == competition_id)
        )
        or 0
    )
    return PageDTO[TradeDTO](items=items, limit=limit, offset=offset, total=total)


@router.get("/models/{agent_id}", response_model=ModelDTO)
def model_details(agent_id: str, db: Annotated[Session, Depends(get_db)]) -> ModelDTO:
    agent = db.get(AgentRun, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ModelDTO(
        id=agent.id,
        name=agent.name,
        provider=agent.provider,
        model=agent.model,
        status=agent.status,
        source_label="DEMO REPLAY",
        api_key_configured=bool(agent.api_key_env),
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
    for offset in range(0, limit, 200):
        page_size = min(200, limit - offset)
        equity_rows.extend(equity_curve(competition_id, db, limit=page_size, offset=offset).items)
        decision_rows.extend(decisions(competition_id, db, limit=page_size, offset=offset).items)
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
            .select_from(InvocationAttempt)
            .join(RoundAgentJob, RoundAgentJob.id == InvocationAttempt.job_id)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .where(DecisionRound.competition_id == competition_id)
        )
        or 0
    )
    return ExportDTO(
        competition=_serialize_competition(db, comp),
        leaderboard=leaderboard(competition_id, db),
        equity=equity_rows,
        decisions=decision_rows,
        truncated=total_equity > len(equity_rows) or total_decisions > len(decision_rows),
        exported_decisions=len(decision_rows),
        exported_equity_points=len(equity_rows),
    )


_stream_slots = asyncio.Semaphore(12)


async def _read_events(competition_id: str, after: int) -> list[DomainEvent]:
    def query() -> list[DomainEvent]:
        with SessionLocal() as db:
            return list(
                db.scalars(
                    select(DomainEvent)
                    .where(
                        DomainEvent.competition_id == competition_id, DomainEvent.sequence > after
                    )
                    .order_by(DomainEvent.sequence)
                    .limit(100)
                )
            )

    return await asyncio.to_thread(query)


@router.get("/competitions/{competition_id}/stream")
async def stream(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    _competition(db, competition_id)
    if _stream_slots.locked() and _stream_slots._value <= 0:
        raise HTTPException(status_code=429, detail="Stream limit reached")
    try:
        after = max(0, int(last_event_id or "0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Last-Event-ID") from exc

    async def body() -> AsyncIterator[str]:
        async with _stream_slots:
            started = asyncio.get_running_loop().time()
            cursor = after
            while asyncio.get_running_loop().time() - started < get_settings().stream_seconds:
                events = await _read_events(competition_id, cursor)
                if not events:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(1)
                    continue
                for event in events:
                    cursor = event.sequence
                    data = json.dumps(
                        {
                            "type": event.event_type,
                            "timestamp": event.event_at.isoformat(),
                            "payload": _public_event_payload(event.payload).model_dump(
                                exclude_none=True
                            ),
                        },
                        separators=(",", ":"),
                    )
                    yield f"id: {event.sequence}\ndata: {data}\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
