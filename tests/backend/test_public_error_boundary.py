from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.db.session import get_db
from app.main import app, public_app
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


class HealthyDatabase:
    def scalar(self, *_: object, **__: object) -> int:
        return 0

    def get(self, *_: object, **__: object) -> None:
        return None


def test_public_database_operational_error_is_safe_503_and_recovers() -> None:
    state = {"unavailable": True}

    def database_session() -> Iterator[HealthyDatabase]:
        if state["unavailable"]:
            raise OperationalError("SELECT 1", {}, RuntimeError("PRIVATE_DB_CANARY"))
        yield HealthyDatabase()

    public_app.dependency_overrides[get_db] = database_session
    try:
        client = TestClient(public_app, raise_server_exceptions=False)
        unavailable = client.get("/status")
        state["unavailable"] = False
        recovered = client.get("/status")

        assert unavailable.status_code == 503
        assert unavailable.json() == {
            "error": "service_unavailable",
            "detail": "The service is temporarily unavailable. Please retry shortly.",
            "retryable": True,
        }
        assert unavailable.headers["retry-after"] == "5"
        assert "PRIVATE_DB_CANARY" not in unavailable.text
        assert recovered.status_code == 200
    finally:
        public_app.dependency_overrides.pop(get_db, None)


def test_public_unexpected_exception_is_safe_500_and_expected_http_errors_keep_status() -> None:
    def broken_session() -> Iterator[HealthyDatabase]:
        raise RuntimeError("PRIVATE_EXCEPTION_CANARY")
        yield HealthyDatabase()

    public_app.dependency_overrides[get_db] = broken_session
    try:
        client = TestClient(public_app, raise_server_exceptions=False)
        unexpected = client.get("/status")

        assert unexpected.status_code == 500
        assert unexpected.json() == {
            "error": "internal_error",
            "detail": "The service could not complete this request.",
            "retryable": False,
        }
        assert "PRIVATE_EXCEPTION_CANARY" not in unexpected.text
    finally:
        public_app.dependency_overrides.pop(get_db, None)

    def healthy_session() -> Iterator[HealthyDatabase]:
        yield HealthyDatabase()

    public_app.dependency_overrides[get_db] = healthy_session
    try:
        missing = TestClient(public_app).get("/competitions/missing")
        assert missing.status_code == 404
        assert missing.json() == {
            "error": "not_found",
            "detail": "Competition not found",
            "retryable": False,
        }
    finally:
        public_app.dependency_overrides.pop(get_db, None)


def test_readyz_database_operational_error_is_retryable_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import engine

    def unavailable_connect() -> None:
        raise OperationalError("SELECT 1", {}, RuntimeError("PRIVATE_READYZ_CANARY"))

    monkeypatch.setattr(engine, "connect", unavailable_connect)
    response = TestClient(app, raise_server_exceptions=False).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "error": "service_unavailable",
        "detail": "The service is temporarily unavailable. Please retry shortly.",
        "retryable": True,
    }
    assert response.headers["retry-after"] == "5"
    assert "PRIVATE_READYZ_CANARY" not in response.text
