from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from app.api.admin import local_auth_router
from app.api.admin import router as admin_router
from app.api.public import router as public_router
from app.core.config import get_settings
from app.db.models import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Open Alpha Arena Lab", version="1.0.0", lifespan=lifespan)
public_app = FastAPI(
    title="Open Alpha Arena Lab Public API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)
admin_app = FastAPI(
    title="Open Alpha Arena Lab Admin API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _error_response(
    *, status_code: int, error: str, detail: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    response_headers = dict(headers or {})
    retryable = status_code in {429, 502, 503, 504}
    if retryable and status_code in {429, 503} and "retry-after" not in {
        key.lower() for key in response_headers
    }:
        response_headers["Retry-After"] = "5"
    response_headers.setdefault("Cache-Control", "no-store")
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "detail": detail, "retryable": retryable},
        headers=response_headers,
    )


@public_app.exception_handler(HTTPException)
async def public_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= 500:
        error = "internal_error" if exc.status_code == 500 else "service_unavailable"
        detail = (
            "Competition rules evidence unavailable"
            if exc.status_code == 503
            and exc.detail == "Competition rules evidence unavailable"
            else "The service could not complete this request."
        )
        return _error_response(
            status_code=exc.status_code,
            error=error,
            detail=detail,
            headers=exc.headers,
        )
    error = {
        400: "invalid_request",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "invalid_request",
        429: "rate_limit_exceeded",
        503: "service_unavailable",
    }.get(exc.status_code, "request_failed")
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return _error_response(
        status_code=exc.status_code,
        error=error,
        detail=detail,
        headers=exc.headers,
    )


@public_app.exception_handler(OperationalError)
async def public_database_unavailable(_: Request, __: OperationalError) -> JSONResponse:
    return _error_response(
        status_code=503,
        error="service_unavailable",
        detail="The service is temporarily unavailable. Please retry shortly.",
    )


@public_app.exception_handler(Exception)
async def public_unexpected_error(_: Request, __: Exception) -> JSONResponse:
    return _error_response(
        status_code=500,
        error="internal_error",
        detail="The service could not complete this request.",
    )


@app.exception_handler(OperationalError)
async def readiness_database_unavailable(_: Request, __: OperationalError) -> JSONResponse:
    return _error_response(
        status_code=503,
        error="service_unavailable",
        detail="The service is temporarily unavailable. Please retry shortly.",
    )


public_app.include_router(public_router)
admin_app.include_router(admin_router)
if get_settings().auth_mode == "local":
    admin_app.include_router(local_auth_router)
app.mount("/api/v1/public", public_app)
app.mount("/api/v1/admin", admin_app)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False, response_model=None)
def readyz() -> dict[str, str] | JSONResponse:
    settings = get_settings()
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
        tables = set(inspect(connection).get_table_names())
        required_tables = {"competitions", "accounts", "round_agent_jobs"}
        if not settings.database_url.startswith("sqlite"):
            required_tables.add("alembic_version")
        if not required_tables.issubset(tables):
            return _error_response(
                status_code=503,
                error="service_unavailable",
                detail="The database schema is not ready. Please retry shortly.",
            )
    return {"status": "ready"}
