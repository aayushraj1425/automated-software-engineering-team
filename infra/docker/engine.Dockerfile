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

# Preview releases run in the engine or worker process. Verify official binary
# checksums; set KUBECTL_VERSION to a minor compatible with the target cluster.
ARG HELM_VERSION=4.3.1
ARG KUBECTL_VERSION=1.36.1
RUN set -eux; \
    curl -fsSL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" -o /tmp/helm.tar.gz; \
    curl -fsSL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz.sha256sum" -o /tmp/helm.sha256; \
    cd /tmp; \
    sed 's@helm-v[^ ]*linux-amd64.tar.gz@helm.tar.gz@' helm.sha256 | sha256sum --check; \
    tar -xzf helm.tar.gz linux-amd64/helm; \
    install -m 0755 linux-amd64/helm /usr/local/bin/helm; \
    curl -fsSL "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o kubectl; \
    curl -fsSL "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" -o kubectl.sha256; \
    printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum --check; \
    install -m 0755 kubectl /usr/local/bin/kubectl; \
    rm -rf /tmp/helm.tar.gz /tmp/helm.sha256 /tmp/linux-amd64 /tmp/kubectl /tmp/kubectl.sha256; \
    helm version --short; \
    kubectl version --client

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
