from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, Request, Response
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Session as DbSession
from app.db.models import User
from app.db.session import get_db

COOKIE = "__Host-arena_session" if get_settings().cookie_secure else "arena_session"
_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_dummy_hash = _password_hasher.hash("codex-dummy-auth-check")
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()
_MAX_LOGIN_RATE_KEYS = 4096
_jwks_clients: dict[str, PyJWKClient] = {}


def password_hash(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return _password_hasher.verify(encoded, password)
    except Exception:
        return False


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def require_origin(request: Request) -> None:
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin is None or origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Origin is not allowed")


def local_login(
    db: Session, username: str, password: str, request: Request, response: Response
) -> User:
    if get_settings().auth_mode != "local":
        raise HTTPException(status_code=404, detail="Not found")
    require_origin(request)
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _attempts_lock:
        for host, timestamps in tuple(_attempts.items()):
            live = [at for at in timestamps if now - at < 60]
            if live:
                _attempts[host] = live
            else:
                del _attempts[host]
        recent = _attempts.get(key, [])
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="Too many login attempts")
        if key not in _attempts and len(_attempts) >= _MAX_LOGIN_RATE_KEYS:
            oldest_host = min(_attempts, key=lambda host: _attempts[host][-1])
            del _attempts[oldest_host]
        _attempts[key] = [*recent, now]
    user = db.scalar(select(User).where(User.username == username))
    encoded = user.password_hash if user else _dummy_hash
    valid = verify_password(encoded, password)
    if user is None or not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    created = datetime.now(UTC)
    row = DbSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        last_seen_at=created,
        idle_expires_at=created + timedelta(minutes=settings.session_idle_minutes),
        abs_expires_at=created + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(row)
    db.commit()
    response.set_cookie(
        COOKIE,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )
    return user


def _access_subject(request: Request) -> str:
    settings = get_settings()
    supplied_token = request.headers.get("x-arena-origin-token", "")
    if not hmac.compare_digest(supplied_token, settings.origin_transport_token):
        raise HTTPException(status_code=401, detail="Invalid origin transport")
    token = request.headers.get("x-arena-user-jwt", "")
    if not token:
        raise HTTPException(status_code=401, detail="Admin identity required")
    client = _jwks_clients.setdefault(
        settings.access_jwks_url, PyJWKClient(settings.access_jwks_url)
    )
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.access_audience,
            issuer=settings.access_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Access identity") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or subject not in settings.admin_subjects:
        raise HTTPException(status_code=403, detail="Admin subject is not allowed")
    return subject


def admin_identity(request: Request, db: Annotated[Session, Depends(get_db)]) -> str:
    settings = get_settings()
    if settings.auth_mode == "access":
        return _access_subject(request)
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Session required")
    digest = hashlib.sha256(raw.encode()).hexdigest()
    session = db.scalar(
        select(DbSession).where(DbSession.token_sha256 == digest, DbSession.revoked_at.is_(None))
    )
    now = datetime.now(UTC)
    if (
        session is None
        or _as_utc(session.idle_expires_at) <= now
        or _as_utc(session.abs_expires_at) <= now
    ):
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, session.user_id)
    if user is None or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    session.last_seen_at = now
    session.idle_expires_at = min(
        now + timedelta(minutes=get_settings().session_idle_minutes),
        _as_utc(session.abs_expires_at),
    )
    db.commit()
    return user.username
