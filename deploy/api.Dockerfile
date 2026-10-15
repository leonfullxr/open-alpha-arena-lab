FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/services/api \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN pip install --no-cache-dir uv==0.6.14 \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock ./
COPY services/api ./services/api
RUN uv sync --frozen --no-dev --no-install-project \
    && chown -R app:app /app

ENV PATH="/app/.venv/bin:$PATH"
USER app:app
EXPOSE 8000
