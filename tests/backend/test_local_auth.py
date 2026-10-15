from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.core.auth import password_hash
from app.core.config import get_settings
from app.db.models import Base, User
from app.db.session import get_db
from app.main import admin_app, app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.mark.skipif(
    get_settings().auth_mode != "local" or get_settings().cookie_secure,
    reason="local HTTP cookie auth is disabled outside local development",
)
def test_local_auth_requires_origin_issues_opaque_cookie_and_revokes_session(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    username = f"admin-{uuid4()}"
    with Session(engine) as db:
        db.add(
            User(
                id=str(uuid4()),
                username=username,
                password_hash=password_hash("correct horse battery staple 42"),
                role="admin",
            )
        )
        db.commit()

    def test_session():
        with Session(engine) as db:
            yield db

    admin_app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(app) as client:
            login_url = "/api/v1/admin/login"
            credentials = {"username": username, "password": "correct horse battery staple 42"}
            assert client.post(login_url, json=credentials).status_code == 403
            response = client.post(
                login_url,
                json=credentials,
                headers={"Origin": "http://localhost:5173"},
            )
            assert response.status_code == 200
            cookie = response.headers["set-cookie"].lower()
            assert "arena_session=" in cookie
            assert "httponly" in cookie and "samesite=strict" in cookie

            assert client.get("/api/v1/admin/status").status_code == 200
            assert client.post("/api/v1/admin/logout").status_code == 403
            logout = client.post(
                "/api/v1/admin/logout", headers={"Origin": "http://localhost:5173"}
            )
            assert logout.status_code == 200
            assert client.get("/api/v1/admin/status").status_code == 401
    finally:
        admin_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
