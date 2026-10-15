from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.public_schemas import (
    AgentMetricsDTO,
    BenchmarkDTO,
    CompetitionMetricsDTO,
)
from app.db.models import AgentRun, Competition
from app.db.session import get_db
from app.services.metrics import agent_metrics, btc_buy_and_hold

metrics_router = APIRouter()


@metrics_router.get("/competitions/{competition_id}/metrics", response_model=CompetitionMetricsDTO)
def competition_metrics(
    competition_id: str, db: Annotated[Session, Depends(get_db)]
) -> CompetitionMetricsDTO:
    competition = db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    agents = list(
        db.query(AgentRun)
        .filter(AgentRun.competition_id == competition.id)
        .order_by(AgentRun.manifest_order)
    )
    benchmark_data = btc_buy_and_hold(db, competition)
    benchmark = (
        BenchmarkDTO(
            symbol="BTC",
            label="BTC buy-and-hold · same initial capital",
            method=(
                "Buy at first ask plus configured slippage; sell at final bid minus "
                "slippage; entry and exit fees charged."
            ),
            **benchmark_data,
        )
        if benchmark_data
        else None
    )
    return CompetitionMetricsDTO(
        competition_id=competition.id,
        agents=[AgentMetricsDTO(**agent_metrics(db, competition, agent)) for agent in agents],
        benchmark=benchmark,
    )
