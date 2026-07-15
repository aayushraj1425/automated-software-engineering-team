# ASEP engine — production image. One image, three workloads (the command
# decides): API (uvicorn), worker (arq), migrations (alembic upgrade head).
# Build from the repo root:
#   docker build -f infra/docker/engine.Dockerfile -t asep-engine apps/engine
# Design note: docs/architecture/KUBERNETES_DEPLOY.md

FROM python:3.12-slim AS base

# git: agent runs operate on per-run worktrees. postgresql-client: pg_dump /
# pg_restore for the backup CLI and the nightly worker cron.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so code edits don't bust the layer cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Non-root; agent worktrees and backups land under /home/engine.
RUN useradd --create-home engine && chown -R engine:engine /app
USER engine
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
