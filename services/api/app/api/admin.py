from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import LoginIn, LoginOut
from app.core.auth import COOKIE, admin_identity, local_login, require_origin
from app.core.config import get_settings
from app.db.models import Competition, PromptVersion, ProviderProfile
from app.db.session import get_db
from app.services.admin import (
    AdminInputError,
    create_competition,
    create_prompt_version,
    create_provider_profile,
    validate_competition_start,
)

router = APIRouter()
local_auth_router = APIRouter()


class AdminDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminCompetition(AdminDTO):
    id: str
    name: str
    state: str
    profile: str
    source_label: str


class AdminStatus(AdminDTO):
    authenticated: bool
    identity: str
    auth_mode: str
    competitions: list[AdminCompetition]


class ProviderProfileIn(AdminDTO):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(default=1, ge=1)
    adapter: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)
    api_key_env: str = Field(min_length=1, max_length=80)
    input_cost_per_million: str
    output_cost_per_million: str
    max_cost_per_request_usd: str
    max_input_body_bytes: int = Field(default=250000, ge=1, le=250000)
    max_output_tokens: int = Field(default=512, ge=1, le=2000)
    temperature: str = "0"


class ProviderProfileOut(AdminDTO):
    id: str
    name: str
    version: int
    adapter: str
    model: str
    api_key_env: str
    input_cost_per_million: str
    output_cost_per_million: str
    max_cost_per_request_usd: str
    max_input_body_bytes: int
    max_output_tokens: int
    temperature: str
    settings_sha256: str
    active: bool


class PromptVersionIn(AdminDTO):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    template: str = Field(min_length=1, max_length=100000)


class PromptVersionOut(AdminDTO):
    id: str
    name: str
    version: int
    sha256: str


class AgentSpecIn(AdminDTO):
    name: str = Field(min_length=1, max_length=80)
    provider_profile_id: str = Field(min_length=36, max_length=36)
    prompt_version_id: str = Field(min_length=36, max_length=36)


class CompetitionIn(AdminDTO):
    name: str = Field(min_length=1, max_length=120)
    profile: str = "alpha_2025_baseline"
    initial_balance: str = "10000"
    inference_budget_usd: str
    agents: list[AgentSpecIn] = Field(min_length=1, max_length=6)


class CompetitionCreated(AdminCompetition):
    rules_sha256: str
    initial_balance: str


@local_auth_router.post("/login", response_model=LoginOut)
def login(
    body: LoginIn, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]
) -> LoginOut:
    if get_settings().auth_mode != "local":
        raise HTTPException(status_code=404, detail="Not found")
    user = local_login(db, body.username, body.password, request, response)
    return LoginOut(username=user.username, role=user.role)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    identity: Annotated[str, Depends(admin_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    require_origin(request)
    if get_settings().auth_mode == "local":
        raw = request.cookies.get(COOKIE, "")
        if raw:
            import hashlib

            from app.db.models import Session as DbSession

            session = db.scalar(
                select(DbSession).where(
                    DbSession.token_sha256 == hashlib.sha256(raw.encode()).hexdigest()
                )
            )
            if session:
                session.revoked_at = datetime.now(UTC)
                db.commit()
    response.delete_cookie(
        COOKIE, path="/", secure=get_settings().cookie_secure, httponly=True, samesite="strict"
    )
    return {"status": "signed_out"}


@router.get("/status", response_model=AdminStatus)
def admin_status(
    identity: Annotated[str, Depends(admin_identity)], db: Annotated[Session, Depends(get_db)]
) -> AdminStatus:
    return AdminStatus(
        authenticated=True,
        identity=identity,
        competitions=[
            AdminCompetition(
                id=item.id,
                name=item.name,
                state=item.state,
                profile=item.profile,
                source_label=item.source_label,
            )
            for item in db.scalars(select(Competition).order_by(Competition.id).limit(100))
        ],
        auth_mode=get_settings().auth_mode,
    )


@router.get("/competitions", response_model=list[AdminCompetition])
def list_competitions(
    identity: Annotated[str, Depends(admin_identity)], db: Annotated[Session, Depends(get_db)]
) -> list[AdminCompetition]:
    return [
        AdminCompetition(
            id=c.id, name=c.name, state=c.state, profile=c.profile, source_label=c.source_label
        )
        for c in db.scalars(select(Competition).order_by(Competition.id))
    ]


@router.get("/providers", response_model=list[ProviderProfileOut])
def list_provider_profiles(
    identity: Annotated[str, Depends(admin_identity)], db: Annotated[Session, Depends(get_db)]
) -> list[ProviderProfileOut]:
    return [
        _provider_out(p)
        for p in db.scalars(
            select(ProviderProfile).order_by(ProviderProfile.name, ProviderProfile.version)
        )
    ]


@router.post("/providers", response_model=ProviderProfileOut, status_code=201)
def add_provider_profile(
    body: ProviderProfileIn,
    request: Request,
    identity: Annotated[str, Depends(admin_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> ProviderProfileOut:
    require_origin(request)
    try:
        row = create_provider_profile(db, body.model_dump())
    except AdminInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _provider_out(row)


@router.post("/providers/{provider_id}/test")
def validate_provider_profile(
    provider_id: str,
    request: Request,
    identity: Annotated[str, Depends(admin_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Validate stored metadata and key presence without making a paid provider call."""
    require_origin(request)
    row = db.get(ProviderProfile, provider_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider profile not found")
    import os

    configured = bool(os.environ.get(row.api_key_env))
    return {
        "status": "ready" if configured else "credential_missing",
        "network_call": "none",
        "credential_env": row.api_key_env,
    }


@router.get("/prompts", response_model=list[PromptVersionOut])
def list_prompts(
    identity: Annotated[str, Depends(admin_identity)], db: Annotated[Session, Depends(get_db)]
) -> list[PromptVersionOut]:
    return [
        PromptVersionOut(id=p.id, name=p.name, version=p.version, sha256=p.sha256)
        for p in db.scalars(
            select(PromptVersion).order_by(PromptVersion.name, PromptVersion.version)
        )
    ]


@router.post("/prompts", response_model=PromptVersionOut, status_code=201)
def add_prompt(
    body: PromptVersionIn,
    request: Request,
    identity: Annotated[str, Depends(admin_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> PromptVersionOut:
    require_origin(request)
    try:
        p = create_prompt_version(db, name=body.name, version=body.version, template=body.template)
    except AdminInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PromptVersionOut(id=p.id, name=p.name, version=p.version, sha256=p.sha256)


@router.post("/competitions", response_model=CompetitionCreated, status_code=201)
def add_competition(
    body: CompetitionIn,
    request: Request,
    identity: Annotated[str, Depends(admin_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> CompetitionCreated:
    require_origin(request)
    try:
        item = create_competition(
            db,
            {
                **body.model_dump(exclude={"agents"}),
                "agents": [agent.model_dump() for agent in body.agents],
            },
        )
    except AdminInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CompetitionCreated(
        id=item.id,
        name=item.name,
        state=item.state,
        profile=item.profile,
        source_label=item.source_label,
        rules_sha256=item.rules_sha256,
        initial_balance=str(item.initial_balance),
    )


@router.post("/competitions/{competition_id}/{action}")
def change_competition_state(
    competition_id: str,
    action: str,
    request: Request,
    identity: Annotated[str, Depends(admin_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    require_origin(request)
    transitions = {
        "start": {"DRAFT": "RUNNING"},
        "pause": {"RUNNING": "PAUSED"},
        "resume": {"PAUSED": "RUNNING"},
        "finish": {"RUNNING": "FINISHED", "PAUSED": "FINISHED"},
    }
    if action not in transitions:
        raise HTTPException(status_code=404, detail="Unknown competition action")
    competition = db.get(Competition, competition_id, with_for_update=True)
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    next_state = transitions[action].get(competition.state)
    if next_state is None:
        raise HTTPException(
            status_code=409, detail=f"Cannot {action} competition from {competition.state}"
        )
    if action == "start":
        try:
            validate_competition_start(db, competition)
        except AdminInputError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    competition.state = next_state
    now = datetime.now(UTC)
    if action == "start":
        competition.started_at = now
    if action == "finish":
        competition.ended_at = now
    db.commit()
    return {"id": competition.id, "state": competition.state}


def _provider_out(row: ProviderProfile) -> ProviderProfileOut:
    return ProviderProfileOut(
        id=row.id,
        name=row.name,
        version=row.version,
        adapter=row.adapter,
        model=row.model,
        api_key_env=row.api_key_env,
        input_cost_per_million=str(row.input_cost_per_million),
        output_cost_per_million=str(row.output_cost_per_million),
        max_cost_per_request_usd=str(row.max_cost_per_request_usd),
        max_input_body_bytes=row.max_input_body_bytes,
        max_output_tokens=row.max_output_tokens,
        temperature=str(row.temperature),
        settings_sha256=row.settings_sha256,
        active=row.active,
    )


@router.get("/openapi.json", include_in_schema=False)
def admin_openapi(identity: Annotated[str, Depends(admin_identity)]) -> JSONResponse:
    from app.main import admin_app

    return JSONResponse(admin_app.openapi())
