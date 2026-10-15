from __future__ import annotations

import base64
import json
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.public_schemas import (
    ArtifactDTO,
    DecisionDTO,
    ExecutionQuoteDTO,
    ModelDTO,
    PageDTO,
    PositionDTO,
    ProposalEvidenceDTO,
    TradeDTO,
)
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    Fill,
    InvocationAttempt,
    InvocationResult,
    MarketQuote,
    Order,
    Position,
    PromptVersion,
    RiskEvaluation,
    RoundAgentJob,
    TradeProposal,
)
from app.db.session import get_db
from app.llm.schema import ProposalOutputError, parse_proposal_output

history_router = APIRouter()


def _competition(db: Session, competition_id: str) -> Competition:
    item = db.get(Competition, competition_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return item


def bounded_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
        raise HTTPException(status_code=422, detail="limit must be 1..200 and offset 0..100000")


@history_router.get("/competitions/{competition_id}/decisions", response_model=PageDTO[DecisionDTO])
def decisions(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
    agent_id: str | None = None,
    symbol: str | None = Query(None, min_length=1, max_length=32),
) -> PageDTO[DecisionDTO]:
    bounded_page(limit, offset)
    _competition(db, competition_id)
    query = (
        select(InvocationAttempt, InvocationResult, RoundAgentJob, DecisionRound, AgentRun)
        .select_from(RoundAgentJob)
        .outerjoin(InvocationAttempt, InvocationAttempt.job_id == RoundAgentJob.id)
        .outerjoin(InvocationResult, InvocationResult.attempt_id == InvocationAttempt.id)
        .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
        .join(AgentRun, AgentRun.id == RoundAgentJob.agent_run_id)
        .where(DecisionRound.competition_id == competition_id)
        .where(
            or_(
                InvocationAttempt.id.is_not(None),
                RoundAgentJob.state == "TERMINAL",
            )
        )
        .order_by(DecisionRound.round_index, AgentRun.manifest_order)
    )
    if agent_id:
        query = query.where(AgentRun.id == agent_id)
    if symbol:
        query = query.where(
            exists(
                select(TradeProposal.id).where(
                    TradeProposal.job_id == RoundAgentJob.id,
                    TradeProposal.symbol == symbol,
                )
            )
        )
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0
    rows = db.execute(query.offset(offset).limit(limit)).all()
    items: list[DecisionDTO] = []
    for artifact, result, job, round_row, agent in rows:
        proposals: list[ProposalEvidenceDTO] = []
        validation_status = "NOT_AVAILABLE"
        validation_errors: list[str] = []
        if result is not None and result.error_code:
            validation_status = "PROVIDER_ERROR"
            validation_errors = [result.error_code]
        elif result is not None and result.output_bytes:
            try:
                batch = parse_proposal_output(result.output_bytes)
                validation_status = "VALID"
                stored_proposals = list(
                    db.scalars(
                        select(TradeProposal)
                        .where(TradeProposal.job_id == job.id)
                        .order_by(TradeProposal.sequence)
                    )
                )
                stored_by_sequence = {row.sequence: row for row in stored_proposals}
                risks: dict[str, RiskEvaluation] = {}
                if stored_proposals:
                    for risk in db.scalars(
                        select(RiskEvaluation).where(
                            RiskEvaluation.proposal_id.in_(
                                [proposal.id for proposal in stored_proposals]
                            )
                        )
                    ):
                        risks[risk.proposal_id] = risk
                for index, proposal in enumerate(batch.proposals):
                    stored = stored_by_sequence.get(index)
                    risk_row = risks.get(stored.id) if stored else None
                    proposals.append(
                        ProposalEvidenceDTO(
                            action=proposal.action.value,
                            symbol=proposal.symbol,
                            quantity=format(proposal.quantity, "f"),
                            leverage=format(proposal.leverage, "f"),
                            stop_loss=(
                                format(proposal.stop_loss, "f") if proposal.stop_loss else None
                            ),
                            take_profit=(
                                format(proposal.take_profit, "f") if proposal.take_profit else None
                            ),
                            confidence=format(proposal.confidence, "f"),
                            invalidation=proposal.invalidation,
                            justification=proposal.justification,
                            risk_decision=risk_row.decision if risk_row else None,
                            risk_reasons=risk_row.reasons if risk_row else [],
                        )
                    )
            except ProposalOutputError:
                validation_status = "INVALID"
                validation_errors = ["INVALID_PROPOSAL_OUTPUT"]
        elif job.error_code:
            validation_status = "PROVIDER_ERROR"
            validation_errors = [job.error_code]
        elif job.terminal_result:
            validation_status = "TERMINAL"

        provider_status_code = result.public_metadata.get("status_code") if result else None
        if (
            isinstance(provider_status_code, bool)
            or not isinstance(provider_status_code, int)
            or not 100 <= provider_status_code <= 599
        ):
            provider_status_code = None

        items.append(
            DecisionDTO(
                id=artifact.id if artifact else job.id,
                agent_id=agent.id,
                agent_name=agent.name,
                round=round_row.round_index,
                action=proposals[0].action if proposals else None,
                symbol=proposals[0].symbol if proposals else None,
                quantity=proposals[0].quantity if proposals else None,
                justification=proposals[0].justification if proposals else None,
                proposals=proposals,
                validation_status=validation_status,
                validation_errors=validation_errors,
                prompt_sha256=artifact.prompt_sha256 if artifact else None,
                output_sha256=result.output_sha256 if result else None,
                artifact_url=(
                    f"/api/v1/public/decisions/{artifact.id}/artifact" if artifact else None
                ),
                provider=agent.provider,
                model=agent.model,
                error_code=(result.error_code if result else job.error_code),
                provider_status_code=provider_status_code,
                latency_ms=result.latency_ms if result else None,
                estimated_cost_usd=(
                    str(result.estimated_cost_usd)
                    if result and result.estimated_cost_usd is not None
                    else None
                ),
                usage=result.usage if result else {},
                execution_result=job.terminal_result,
            )
        )
    return PageDTO[DecisionDTO](items=items, limit=limit, offset=offset, total=total)


@history_router.get("/decisions/{decision_id}/artifact", response_model=ArtifactDTO)
def artifact(decision_id: str, db: Annotated[Session, Depends(get_db)]) -> ArtifactDTO:
    item = db.get(InvocationAttempt, decision_id)
    result = db.scalar(select(InvocationResult).where(InvocationResult.attempt_id == decision_id))
    if item is None or result is None:
        raise HTTPException(status_code=404, detail="Decision artifact not found")
    output_safe = False
    if result.error_code is None and result.output_bytes:
        try:
            parse_proposal_output(result.output_bytes)
            output_safe = True
        except ProposalOutputError:
            pass
    public_output = result.output_bytes if output_safe else b""
    return ArtifactDTO(
        id=item.id,
        prompt_sha256=item.prompt_sha256,
        output_sha256=result.output_sha256,
        prompt_bytes_base64=base64.b64encode(item.prompt_bytes).decode(),
        output_bytes_base64=base64.b64encode(public_output).decode(),
        output_publicly_releasable=output_safe,
    )


@history_router.get("/competitions/{competition_id}/positions", response_model=PageDTO[PositionDTO])
def positions(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
    include_closed: bool = False,
    agent_id: str | None = None,
    symbol: str | None = Query(None, min_length=1, max_length=32),
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
    if agent_id:
        query = query.where(AgentRun.id == agent_id)
    if symbol:
        query = query.where(Position.symbol == symbol)
    rows = db.execute(
        query.order_by(AgentRun.manifest_order, Position.symbol, Position.opened_at, Position.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        PositionDTO(
            id=p.id,
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
            opened_at=p.opened_at.isoformat(),
            closed_at=p.closed_at.isoformat() if p.closed_at else None,
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
    if agent_id:
        count_query = count_query.where(AgentRun.id == agent_id)
    if symbol:
        count_query = count_query.where(Position.symbol == symbol)
    total = db.scalar(count_query) or 0
    return PageDTO[PositionDTO](items=items, limit=limit, offset=offset, total=total)


@history_router.get("/competitions/{competition_id}/trades", response_model=PageDTO[TradeDTO])
def trades(
    competition_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50),
    offset: int = Query(0),
    agent_id: str | None = None,
    symbol: str | None = Query(None, min_length=1, max_length=32),
) -> PageDTO[TradeDTO]:
    bounded_page(limit, offset)
    _competition(db, competition_id)
    market_quote_set = case(
        (Order.kind == "MARKET", DecisionRound.execution_quote_set_id),
        else_=Order.quote_set_id,
    )
    query = (
        select(
            Fill,
            Order,
            AgentRun,
            TradeProposal.sequence,
            func.coalesce(InvocationAttempt.id, RoundAgentJob.id),
            DecisionRound.round_index,
            MarketQuote,
            market_quote_set.label("effective_quote_set_id"),
        )
        .join(Order, Order.id == Fill.order_id)
        .join(Account, Account.id == Order.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .outerjoin(TradeProposal, TradeProposal.id == Order.proposal_id)
        .outerjoin(RoundAgentJob, RoundAgentJob.id == TradeProposal.job_id)
        .outerjoin(InvocationAttempt, InvocationAttempt.job_id == RoundAgentJob.id)
        .outerjoin(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
        .outerjoin(
            MarketQuote,
            and_(
                MarketQuote.quote_set_id == market_quote_set,
                MarketQuote.symbol == Fill.symbol,
            ),
        )
        .where(AgentRun.competition_id == competition_id)
    )
    if agent_id:
        query = query.where(AgentRun.id == agent_id)
    if symbol:
        query = query.where(Fill.symbol == symbol)
    rows = cast(
        list[
            tuple[
                Fill,
                Order,
                AgentRun,
                int | None,
                str | None,
                int | None,
                MarketQuote | None,
                str | None,
            ]
        ],
        db.execute(
            query.order_by(
                Order.event_sequence.asc().nulls_first(),
                Fill.ordinal.asc().nulls_first(),
                Fill.id,
            )
            .offset(offset)
            .limit(limit)
        ).all(),
    )
    items: list[TradeDTO] = []
    for (
        fill,
        order,
        agent,
        proposal_sequence,
        decision_id,
        round_index,
        quote,
        effective_quote_set_id,
    ) in rows:
        items.append(
            TradeDTO(
                fill_id=fill.id,
                agent_id=agent.id,
                agent_name=agent.name,
                symbol=fill.symbol,
                side=fill.side,
                quantity=str(fill.quantity),
                price=str(fill.price),
                fee=str(fill.fee),
                order_id=order.id,
                status=order.status,
                order_kind=order.kind,
                decision_id=decision_id,
                proposal_sequence=proposal_sequence,
                round=round_index,
                executed_at=fill.executed_at.isoformat() if fill.executed_at else None,
                event_sequence=order.event_sequence,
                fill_ordinal=fill.ordinal,
                quote_set_id=effective_quote_set_id,
                execution_quote=(
                    ExecutionQuoteDTO(
                        bid=str(quote.bid),
                        ask=str(quote.ask),
                        mark=str(quote.mark),
                        source_at=quote.source_at.isoformat(),
                        source_at_basis=quote.source_at_basis,
                    )
                    if quote is not None
                    else None
                ),
            )
        )
    count_query = (
        select(func.count())
        .select_from(Fill)
        .join(Order, Order.id == Fill.order_id)
        .join(Account, Account.id == Order.account_id)
        .join(AgentRun, AgentRun.id == Account.agent_run_id)
        .where(AgentRun.competition_id == competition_id)
    )
    if agent_id:
        count_query = count_query.where(AgentRun.id == agent_id)
    if symbol:
        count_query = count_query.where(Fill.symbol == symbol)
    total = db.scalar(count_query) or 0
    return PageDTO[TradeDTO](items=items, limit=limit, offset=offset, total=total)


@history_router.get("/models/{agent_id}", response_model=ModelDTO)
def model_details(agent_id: str, db: Annotated[Session, Depends(get_db)]) -> ModelDTO:
    agent = db.get(AgentRun, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    competition = _competition(db, agent.competition_id)
    prompt = db.get(PromptVersion, agent.prompt_version_id)
    try:
        source_settings = json.loads(agent.model_settings_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        source_settings = {}
    public_settings: dict[str, str | int] = {}
    for key in (
        "adapter",
        "input_cost_per_million_usd",
        "output_cost_per_million_usd",
        "max_cost_per_request_usd",
        "temperature",
    ):
        value = source_settings.get(key)
        if isinstance(value, str) and len(value) <= 80:
            public_settings[key] = value
    for key in ("max_input_body_bytes", "max_output_tokens"):
        value = source_settings.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 250000:
            public_settings[key] = value
    return ModelDTO(
        id=agent.id,
        name=agent.name,
        provider=agent.provider,
        model=agent.model,
        status=agent.status,
        source_label=(
            "DEMO REPLAY"
            if competition.source_label.startswith("DEMO REPLAY")
            else competition.source_label
        ),
        credential_reference_configured=bool(agent.api_key_env),
        competition_id=competition.id,
        profile=competition.profile,
        settings_sha256=agent.settings_sha256,
        prompt_sha256=prompt.sha256 if prompt else "",
        public_settings=public_settings,
    )
