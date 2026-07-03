from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    redis_url: str = "redis://localhost:6379/0"

    engine_service_secret: str = "dev-only-service-secret-change-me-00"
    engine_cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    llm_fake: bool = False
    model_planner: str = "anthropic/claude-opus-4-8"
    model_coder: str = "anthropic/claude-sonnet-4-6"
    model_cheap: str = "anthropic/claude-haiku-4-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
