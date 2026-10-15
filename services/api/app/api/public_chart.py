from __future__ import annotations

from datetime import UTC, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.api.public_schemas import EquityChartDTO, EquityPoint
from app.db.models import Account, AgentRun, Competition, EquitySample
from app.db.session import get_db

chart_router = APIRouter()


@chart_router.get("/competitions/{competition_id}/chart", response_model=EquityChartDTO)
def equity_chart(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    range_name: Annotated[Literal["ALL", "72H", "24H"], Query(alias="range")] = "ALL",
    points: int = Query(default=400, ge=2, le=400),
) -> EquityChartDTO:
    if db.get(Competition, competition_id) is None:
        raise HTTPException(status_code=404, detail="Competition not found")

    latest = db.scalar(
        select(func.max(EquitySample.logical_at))
        .join(Account, Account.id == EquitySample.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
    )
    if latest is None:
        return EquityChartDTO(range=range_name, points=points, total_raw=0, sampled=False, items=[])
    if latest.tzinfo is None or latest.utcoffset() is None:
        latest = latest.replace(tzinfo=UTC)
    duration = {"ALL": None, "72H": timedelta(hours=72), "24H": timedelta(hours=24)}[
        range_name
    ]
    cutoff = latest - duration if duration is not None else None

    scoped = (
        select(
            EquitySample.account_id.label("account_id"),
            EquitySample.round_index.label("round_index"),
            EquitySample.logical_at.label("logical_at"),
            EquitySample.equity.label("equity"),
            EquitySample.realized_pnl.label("realized_pnl"),
            EquitySample.unrealized_pnl.label("unrealized_pnl"),
            EquitySample.fees.label("fees"),
            EquitySample.funding.label("funding"),
            AgentRun.id.label("agent_id"),
            AgentRun.name.label("agent_name"),
            AgentRun.manifest_order.label("manifest_order"),
        )
        .join(Account, Account.id == EquitySample.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
    )
    if cutoff is not None:
        scoped = scoped.where(EquitySample.logical_at >= cutoff)
    raw = scoped.subquery("chart_raw")
    row_number = func.row_number().over(
        partition_by=raw.c.account_id,
        order_by=(raw.c.logical_at, raw.c.round_index),
    )
    row_count = func.count().over(partition_by=raw.c.account_id)
    ranked = select(raw, row_number.label("row_number"), row_count.label("row_count")).subquery(
        "chart_ranked"
    )
    bucket_index = cast(
        func.floor(
            cast(ranked.c.row_number - 1, Numeric)
            * (points - 1)
            / func.nullif(cast(ranked.c.row_count - 1, Numeric), 0)
        ),
        Integer,
    )
    buckets = select(ranked, bucket_index.label("bucket_index")).subquery("chart_buckets")
    bucket_order = func.row_number().over(
        partition_by=(buckets.c.account_id, buckets.c.bucket_index),
        order_by=(buckets.c.logical_at, buckets.c.round_index),
    )
    selected = select(buckets, bucket_order.label("bucket_order")).subquery("chart_selected")
    rows = db.execute(
        select(selected)
        .where(selected.c.bucket_order == 1)
        .order_by(selected.c.logical_at, selected.c.manifest_order)
    ).mappings()
    items = [
        EquityPoint(
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            round=row["round_index"],
            timestamp=row["logical_at"].isoformat(),
            equity=str(row["equity"]),
            realized_pnl=str(row["realized_pnl"]),
            unrealized_pnl=str(row["unrealized_pnl"]),
            fees=str(row["fees"]),
            funding=str(row["funding"]),
        )
        for row in rows
    ]
    total = db.scalar(select(func.count()).select_from(raw)) or 0
    return EquityChartDTO(
        range=range_name,
        points=points,
        total_raw=total,
        sampled=total > len(items),
        items=items,
    )
