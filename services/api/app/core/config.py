from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./arena-demo.sqlite3"
    auth_mode: str = "local"
    cookie_secure: bool = False
    session_idle_minutes: int = 60
    session_absolute_hours: int = 12
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    origin_transport_token: str = ""
    access_issuer: str = ""
    access_audience: str = ""
    access_jwks_url: str = ""
    admin_subjects: list[str] = Field(default_factory=list)
    max_streams: int = 12
    stream_seconds: int = 900
    max_daily_llm_spend_usd: Decimal = Field(
        default=Decimal("5"), gt=Decimal("0"), max_digits=12, decimal_places=6
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.auth_mode not in {"local", "access"}:
        raise ValueError("AUTH_MODE must be local or access")
    if settings.auth_mode == "access" and not all(
        (
            settings.access_issuer,
            settings.access_audience,
            settings.access_jwks_url,
            settings.admin_subjects,
            settings.origin_transport_token,
        )
    ):
        raise ValueError(
            "Access mode requires issuer, audience, JWKS URL, admin subjects, and transport token"
        )
    if (
        settings.auth_mode == "local"
        and not settings.cookie_secure
        and not any("localhost" in o or "127.0.0.1" in o for o in settings.allowed_origins)
    ):
        raise ValueError("insecure cookies are only permitted for a local development origin")
    return settings
