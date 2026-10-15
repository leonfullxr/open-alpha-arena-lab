from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from app.api import admin as admin_api
from app.core import auth as auth_core
from app.core.config import Settings
from app.db.models import Base
from app.db.session import get_db
from app.main import admin_app, app
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FakeJwks:
    def __init__(self, key: Any) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        assert token
        return SimpleNamespace(key=self.key)


def test_access_auth_verifies_signed_identity_and_denies_fallbacks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_url = "https://issuer.test/jwks"
    access_settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'access.db'}",
        auth_mode="access",
        access_issuer="https://issuer.test/",
        access_audience="arena-admin",
        access_jwks_url=jwks_url,
        admin_subjects=["admin-subject"],
        origin_transport_token="service-origin-token",
        allowed_origins=["https://arena.test"],
    )
    monkeypatch.setattr(auth_core, "get_settings", lambda: access_settings)
    monkeypatch.setattr(admin_api, "get_settings", lambda: access_settings)
    monkeypatch.setitem(auth_core._jwks_clients, jwks_url, FakeJwks(private.public_key()))

    engine = create_engine(access_settings.database_url)
    Base.metadata.create_all(engine)

    def test_session():
        with Session(engine) as db:
            yield db

    admin_app.dependency_overrides[get_db] = test_session
    token_headers = {
        "x-arena-origin-token": "service-origin-token",
    }

    def issue(**changes: Any) -> str:
        now = datetime.now(UTC)
        signer = changes.pop("_signer", private)
        claims: dict[str, Any] = {
            "iss": access_settings.access_issuer,
            "aud": access_settings.access_audience,
            "sub": "admin-subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        claims.update(changes)
        return jwt.encode(claims, signer, algorithm="RS256")

    try:
        with TestClient(app) as client:
            good = issue()
            response = client.get(
                "/api/v1/admin/status",
                headers={**token_headers, "x-arena-user-jwt": good},
            )
            assert response.status_code == 200
            assert response.json()["identity"] == "admin-subject"

            failures = [
                (issue(iss="https://wrong.test/"), 401),
                (issue(aud="wrong-audience"), 401),
                (issue(exp=None), 401),
                (issue(iat=None), 401),
                (issue(sub=None), 401),
                (issue(exp=datetime.now(UTC) - timedelta(seconds=10)), 401),
                (issue(iat=datetime.now(UTC) + timedelta(minutes=5)), 401),
                (issue(sub="not-allowlisted"), 403),
                (issue(_signer=wrong_private), 401),
            ]
            for token, expected in failures:
                result = client.get(
                    "/api/v1/admin/status",
                    headers={**token_headers, "x-arena-user-jwt": token},
                )
                assert result.status_code == expected

            for headers in (
                {"cf-access-jwt-assertion": good, **token_headers},
                {"x-user": "admin-subject", **token_headers},
                {"x-arena-user-jwt": good},
            ):
                assert client.get("/api/v1/admin/status", headers=headers).status_code == 401

            assert client.post(
                "/api/v1/admin/login",
                json={"username": "admin", "password": "password"},
                headers={"Origin": "https://arena.test"},
            ).status_code == 404
            origin_rejected = client.post(
                "/api/v1/admin/competitions",
                json={
                    "name": "x",
                    "inference_budget_usd": "1",
                    "agents": [
                        {
                            "name": "Agent",
                            "provider_profile_id": "0" * 36,
                            "prompt_version_id": "1" * 36,
                        }
                    ],
                },
                headers={
                    **token_headers,
                    "x-arena-user-jwt": good,
                    "Origin": "https://attacker.test",
                },
            )
            assert origin_rejected.status_code == 403
    finally:
        admin_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
