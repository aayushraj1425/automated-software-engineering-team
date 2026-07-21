from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Every embedding — real or fake — has exactly this many numbers; the
# code_chunks column is vector(EMBEDDING_DIM). Changing it means re-indexing.
EMBEDDING_DIM = 768


class Settings(BaseSettings):
    """Engine configuration. One root .env drives everything (see .env.example).

    env_file order: the local file wins over the repo root for duplicate keys.
    """

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://asep:asep@localhost:5433/asep"
    # Privilege separation (ROW_LEVEL_SECURITY.md): user-pinned sessions
    # connect as a non-owner role that cannot touch policies or claim the
    # service context. Empty = single-role mode (everything on database_url).
    database_url_api: str = ""
    redis_url: str = "redis://localhost:6379/0"

    engine_service_secret: str = "dev-only-service-secret-change-me-00"
    # AES-GCM key (base64, 32 bytes) for secrets at rest (PROVIDER_KEYS.md);
    # empty derives one from engine_service_secret — development only.
    engine_encryption_key: str = ""
    engine_cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    llm_fake: bool = False
    workspaces_dir: str = ".workspaces"
    run_recovery_enabled: bool = True  # resume interrupted runs at startup (RUN_RECOVERY.md)
    # Where runs execute: "inline" (background task in the API process) or
    # "arq" (Redis queue + worker process — BACKGROUND_WORKER.md).
    run_queue: str = "inline"
    sandbox_enabled: bool = True  # run the workspace's tests in Docker before the PR
    sandbox_required: bool = False  # fail the run (instead of skipping) when Docker is down
    sandbox_timeout_seconds: int = 300  # per phase: dependency install, then tests
    qa_max_attempts: int = 2  # QA fix-and-retry cycles before a red sandbox fails the run
    github_token: str = ""  # pushes the run branch and opens the pull request
    github_webhook_secret: str = ""  # verifies GitHub webhooks; empty rejects all webhook calls
    # Integration adapters skip the network and report success (tests, offline
    # dev) — the run→notify path still runs (EXTERNAL_INTEGRATIONS.md).
    integrations_dry_run: bool = False
    # OpenTelemetry (ADR-0010, PRODUCTION_HARDENING.md): spans/metrics are
    # no-ops until otel_enabled installs the SDK; the endpoint is an OTLP/HTTP
    # collector (empty keeps telemetry in-process only).
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "asep-engine"
    # Per-caller token bucket (RATE_LIMITING.md): 0 disables; the bucket holds
    # `burst` tokens and refills at per_minute/60 per second.
    rate_limit_per_minute: int = 0
    rate_limit_burst: int = 30
    # Share one bucket across replicas via Redis (RATE_LIMITING.md). Off keeps
    # the bucket in-process (effective limit is per replica); on, a Redis
    # outage degrades back to per-replica, never to a hard dependency.
    rate_limit_shared: bool = False
    # Postgres backups (BACKUPS_AND_RECOVERY.md): enabling adds a nightly
    # pg_dump cron to the arq worker; the CLI (`python -m engine.backup`)
    # works regardless. pg_bin_dir points at pg_dump/pg_restore when they
    # are not on PATH (empty tries PATH, then the Windows install dir).
    backup_enabled: bool = False
    backup_dir: str = ".backups"
    backup_retention: int = 14
    pg_bin_dir: str = ""
    model_planner: str = "anthropic/claude-opus-4-8"
    model_coder: str = "anthropic/claude-sonnet-4-6"
    model_cheap: str = "anthropic/claude-haiku-4-5"
    model_embedding: str = "gemini/text-embedding-004"  # must produce EMBEDDING_DIM numbers


@lru_cache
def get_settings() -> Settings:
    return Settings()
