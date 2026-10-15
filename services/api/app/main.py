from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect

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
public_app.include_router(public_router)
admin_app.include_router(admin_router)
if get_settings().auth_mode == "local":
    admin_app.include_router(local_auth_router)
app.mount("/api/v1/public", public_app)
app.mount("/api/v1/admin", admin_app)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz() -> dict[str, str]:
    settings = get_settings()
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
        tables = set(inspect(connection).get_table_names())
        required_tables = {"competitions", "accounts", "round_agent_jobs"}
        if not settings.database_url.startswith("sqlite"):
            required_tables.add("alembic_version")
        if not required_tables.issubset(tables):
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="database schema is not migrated")
    return {"status": "ready"}
