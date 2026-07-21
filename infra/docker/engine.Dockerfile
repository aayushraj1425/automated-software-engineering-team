# ASEP engine — production image. One image, three workloads (the command
# decides): API (uvicorn), worker (arq), migrations (alembic upgrade head).
# Build from the repo root:
#   docker build -f infra/docker/engine.Dockerfile -t asep-engine apps/engine
# Design note: docs/architecture/KUBERNETES_DEPLOY.md

FROM python:3.12-slim AS base

# git: agent runs operate on per-run worktrees. postgresql-client: pg_dump /
# pg_restore for the backup CLI and the nightly worker cron. ca-certificates +
# curl: fetch the docker CLI below (curl stays — it is tiny and handy).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git postgresql-client ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# The docker CLI *client only* (no daemon). The worker's QA sandbox drives a
# Docker daemon over DOCKER_HOST — a DinD sidecar in-cluster — reusing the
# static client binary Docker publishes. API/migration workloads never call it;
# it rides along because the image is shared (docs/architecture/SANDBOX_EXECUTION.md).
ARG DOCKER_CLI_VERSION=27.3.1
RUN set -eux; \
    curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz; \
    tar -xzf /tmp/docker.tgz -C /tmp docker/docker; \
    mv /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker /tmp/docker.tgz; \
    docker --version

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
