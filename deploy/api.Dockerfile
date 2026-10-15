FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/services/api \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.28 \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock ./
COPY services/api ./services/api
COPY prompts ./prompts
COPY configs ./configs
RUN uv sync --frozen --no-dev --no-install-project \
    && chown -R app:app /app

ENV PATH="/app/.venv/bin:$PATH"
USER app:app
EXPOSE 8000
