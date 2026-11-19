"""Preview adapter knobs. Same env-file rules as the engine's config.py.

Kept separate because the adapter is built in parallel with config.py; the lead
can fold these fields into Settings later (PREVIEW_DEPLOY_ADAPTER.md).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class PreviewSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # In-VPC clusters hand out private load balancer addresses.
    preview_allow_private_smoke: bool = False
    # Local minikube / kind clusters serve their API on loopback.
    preview_allow_local_cluster: bool = False
    # fnmatch patterns, comma separated; empty means no restriction.
    preview_allowed_api_server_hosts: str = ""
    # Registry hosts a rendered image may come from; empty means any.
    preview_allowed_image_registries: str = ""
    preview_helm_timeout_seconds: int = 300

    @staticmethod
    def _split(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]

    @property
    def allowed_api_server_hosts(self) -> list[str]:
        return self._split(self.preview_allowed_api_server_hosts)

    @property
    def allowed_image_registries(self) -> list[str]:
        return self._split(self.preview_allowed_image_registries)


@lru_cache
def get_preview_settings() -> PreviewSettings:
    return PreviewSettings()
