from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from app.api import public_stream
from app.core.config import get_settings
from app.db.models import DomainEvent
from app.db.session import get_db
from app.main import public_app

PATH = "/competitions/competition-1/stream"


class _Db:
    def get(self, _model: object, competition_id: str) -> object | None:
        return object() if competition_id == "competition-1" else None

    def close(self) -> None:
        pass


def _db() -> Iterator[_Db]:
    yield _Db()


@pytest.fixture(autouse=True)
def _stream_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = get_settings().model_copy(update={"max_streams": 2, "stream_seconds": 0})
    monkeypatch.setattr(public_stream, "get_settings", lambda: settings)
    monkeypatch.setattr(public_stream, "_active_streams", 0)
    public_app.dependency_overrides[get_db] = _db
    yield
    public_app.dependency_overrides.pop(get_db, None)


def _settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    settings = public_stream.get_settings().model_copy(update=update)
    monkeypatch.setattr(public_stream, "get_settings", lambda: settings)


def _scope() -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": PATH,
        "raw_path": PATH.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }


async def _call(receive: Any, send: Any) -> None:
    await public_app(_scope(), receive, send)


async def _immediate_disconnect() -> dict[str, Any]:
    return {"type": "http.disconnect"}


async def _request(disconnect: asyncio.Event | None = None) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    first = True

    async def receive() -> dict[str, Any]:
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        if disconnect is None:
            await asyncio.Event().wait()
        else:
            await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await _call(receive, send)
    return sent


def _status(sent: list[dict[str, Any]]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_early_disconnects_release_slots_and_capacity_recovers() -> None:
    async def scenario() -> None:
        async def send(_message: dict[str, Any]) -> None:
            await asyncio.sleep(0)

        for _ in range(5):
            await _call(_immediate_disconnect, send)
        assert public_stream._active_streams == 0
        assert _status(await _request()) == 200
        assert public_stream._active_streams == 0

    asyncio.run(scenario())


def test_capacity_rejects_excess_streams_then_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, stream_seconds=60)

    async def no_events(_competition_id: str, _after: int) -> list[DomainEvent]:
        return []

    monkeypatch.setattr(public_stream, "_read_events", no_events)

    async def scenario() -> None:
        release = asyncio.Event()
        held = [asyncio.create_task(_request(release)) for _ in range(2)]
        while public_stream._active_streams < 2:
            await asyncio.sleep(0)
        assert _status(await _request()) == 429
        release.set()
        for task in held:
            sent = await task
            assert _status(sent) == 200
            assert any(m.get("body") == b": heartbeat\n\n" for m in sent)
        assert public_stream._active_streams == 0
        _settings(monkeypatch, stream_seconds=0)
        assert _status(await _request()) == 200

    asyncio.run(scenario())


def test_stream_errors_and_send_failures_release_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, stream_seconds=60)

    async def broken(_competition_id: str, _after: int) -> list[DomainEvent]:
        raise RuntimeError("query failed")

    monkeypatch.setattr(public_stream, "_read_events", broken)

    async def failing_send(_message: dict[str, Any]) -> None:
        raise OSError("socket closed")

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="query failed"):
            await _request()
        assert public_stream._active_streams == 0
        with pytest.raises(OSError):
            await _call(_immediate_disconnect, failing_send)
        assert public_stream._active_streams == 0

    asyncio.run(scenario())


def test_unknown_competition_is_not_admitted() -> None:
    async def scenario() -> None:
        sent: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        scope = _scope() | {"path": "/competitions/missing/stream"}
        await public_app(scope, _immediate_disconnect, send)
        assert _status(sent) == 404
        assert public_stream._active_streams == 0

    asyncio.run(scenario())
