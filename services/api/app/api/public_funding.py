from __future__ import annotations

import base64
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.public_schemas import (
    FundingEvidenceArtifactDTO,
    FundingPaymentDTO,
    PageDTO,
)
from app.db.models import Account, AgentRun, Competition, FundingPayment, FundingRateEvidence
from app.db.session import get_db

funding_router = APIRouter()


def _bounded_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
        raise HTTPException(status_code=422, detail="limit must be 1..200 and offset 0..100000")


@funding_router.get(
    "/competitions/{competition_id}/funding",
    response_model=PageDTO[FundingPaymentDTO],
)
def funding_history(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
    agent_id: str | None = None,
    symbol: str | None = Query(None, min_length=1, max_length=32),
) -> PageDTO[FundingPaymentDTO]:
    _bounded_page(limit, offset)
    if db.get(Competition, competition_id) is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    query = (
        select(FundingPayment, AgentRun, FundingRateEvidence)
        .join(Account, Account.id == FundingPayment.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .outerjoin(FundingRateEvidence, FundingRateEvidence.id == FundingPayment.evidence_id)
        .where(AgentRun.competition_id == competition_id)
    )
    if agent_id:
        query = query.where(AgentRun.id == agent_id)
    if symbol:
        query = query.where(FundingPayment.symbol == symbol)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(
            FundingPayment.event_at.desc(), AgentRun.manifest_order, FundingPayment.symbol
        )
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        FundingPaymentDTO(
            id=payment.id,
            agent_id=agent.id,
            agent_name=agent.name,
            symbol=payment.symbol,
            boundary_at=payment.event_at.isoformat(),
            status=payment.status,
            reason=payment.reason,
            amount=str(payment.amount) if payment.amount is not None else None,
            rate=str(payment.rate) if payment.rate is not None else None,
            oracle_px=str(payment.oracle_px) if payment.oracle_px is not None else None,
            source=payment.source,
            evidence_id=payment.evidence_id,
            evidence_sha256=evidence.sha256 if evidence is not None else None,
        )
        for payment, agent, evidence in rows
    ]
    return PageDTO[FundingPaymentDTO](items=items, limit=limit, offset=offset, total=total)


@funding_router.get(
    "/funding/evidence/{evidence_id}", response_model=FundingEvidenceArtifactDTO
)
def funding_evidence(
    evidence_id: str, db: Annotated[Session, Depends(get_db)]
) -> FundingEvidenceArtifactDTO:
    evidence = db.get(FundingRateEvidence, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Funding evidence not found")
    return FundingEvidenceArtifactDTO(
        id=evidence.id,
        symbol=evidence.symbol,
        boundary_at=evidence.boundary_at.isoformat(),
        status=evidence.status,
        rate=str(evidence.rate) if evidence.rate is not None else None,
        history_event_at=(
            evidence.history_event_at.isoformat() if evidence.history_event_at else None
        ),
        sha256=evidence.sha256,
        exact_record_base64=(
            base64.b64encode(evidence.raw_record_bytes).decode("ascii")
            if evidence.raw_record_bytes is not None
            else None
        ),
    )
