"""Fixed boundary between the runner, preview adapter, API, and approval UI."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PreviewOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_path: str = "deploy/helm"
    values_file: str | None = None
    image: str | None = None
    ttl_hours: int = Field(default=24, ge=1, le=168)
    smoke_paths: list[str] = Field(default_factory=lambda: ["/healthz"], max_length=10)


class SmokeResult(BaseModel):
    passed: bool
    checks: list[dict] = Field(default_factory=list)
    error: str | None = None


class PreviewDeployment(BaseModel):
    run_id: uuid.UUID
    namespace: str
    url: str | None = None
    status: Literal["deployed", "failed", "deleted", "simulated"]
    expires_at: datetime
    source_sha: str | None = None
    smoke: SmokeResult | None = None
    error: str | None = None


# Implementations live in deploy/preview.py and agents/release.py (Agent 5).
# Contract: async deploy_preview(ws, credentials: dict[str, str], *,
#   options: PreviewOptions | None = None) -> PreviewDeployment
# Contract: async run_cloud_smoke_tests(url: str, *, paths: list[str] | None = None,
#   timeout_seconds: int = 30) -> SmokeResult
# Contract: async teardown_preview(deployment: PreviewDeployment,
#   credentials: dict[str, str]) -> None
