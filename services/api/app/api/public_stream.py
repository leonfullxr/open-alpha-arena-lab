from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from app.api.public_schemas import public_event_payload
from app.core.config import get_settings
from app.db.models import Competition, DomainEvent
from app.db.session import SessionLocal, get_db

stream_router = APIRouter()
_active_streams = 0


class _AdmittedStreamResponse(StreamingResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _active_streams
        try:
            await super().__call__(scope, receive, send)
        finally:
            _active_streams -= 1


def _existing_competition_id(competition_id: str, db: Annotated[Session, Depends(get_db)]) -> str:
    if db.get(Competition, competition_id) is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    db.close()
    return competition_id


async def _read_events(competition_id: str, after: int) -> list[DomainEvent]:
    def query() -> list[DomainEvent]:
        with SessionLocal() as db:
            return list(
                db.scalars(
                    select(DomainEvent)
                    .where(
                        DomainEvent.competition_id == competition_id,
                        DomainEvent.sequence > after,
                    )
                    .order_by(DomainEvent.sequence)
                    .limit(100)
                )
            )

    return await asyncio.to_thread(query)


@stream_router.get("/competitions/{competition_id}/stream")
async def stream(
    competition_id: Annotated[str, Depends(_existing_competition_id)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    global _active_streams
    # Admission is atomic on the event loop: no await occurs between checking and
    # reserving a connection slot, so excess requests are rejected instead of queued.
    if _active_streams >= get_settings().max_streams:
        raise HTTPException(status_code=429, detail="Stream limit reached")
    try:
        after = max(0, int(last_event_id or "0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Last-Event-ID") from exc
    _active_streams += 1

    async def body() -> AsyncIterator[str]:
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
                        "payload": public_event_payload(event.payload).model_dump(
                            exclude_none=True
                        ),
                    },
                    separators=(",", ":"),
                )
                yield f"id: {event.sequence}\ndata: {data}\n\n"

    return _AdmittedStreamResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
