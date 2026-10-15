from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import LoginIn, LoginOut
from app.core.auth import COOKIE, admin_identity, local_login, require_origin
from app.core.config import get_settings
from app.db.models import Competition
from app.db.session import get_db

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
    competition.state = next_state
    now = datetime.now(UTC)
    if action == "start":
        competition.started_at = now
    if action == "finish":
        competition.ended_at = now
    db.commit()
    return {"id": competition.id, "state": competition.state}


@router.get("/openapi.json", include_in_schema=False)
def admin_openapi(identity: Annotated[str, Depends(admin_identity)]) -> JSONResponse:
    from app.main import admin_app

    return JSONResponse(admin_app.openapi())
