"""Catalog metadata and deterministic seat selection; no provider calls here."""

import ipaddress
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeatLevel(StrEnum):
    SUPPORT = "support"
    ENGINEER = "engineer"
    SENIOR = "senior"
    PRINCIPAL = "principal"


MIN_STRENGTH = {
    SeatLevel.SUPPORT: 1,
    SeatLevel.ENGINEER: 3,
    SeatLevel.SENIOR: 4,
    SeatLevel.PRINCIPAL: 5,
}


OPENAI_COMPATIBLE = "openai_compatible"


def normalize_base_url(value: str) -> str:
    """A plain http(s) endpoint with no credentials, query or link-local host."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("base_url must be an http or https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("base_url must not contain credentials, a query, or a fragment")
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        address = None  # a hostname, not a literal IP
    if address is not None and address.is_link_local:
        raise ValueError("base_url must not point at a link-local address")
    return value.strip().rstrip("/")


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=256)
    provider: str = Field(pattern="^(anthropic|openai|gemini|openai_compatible)$")
    context_size: int = Field(gt=0)
    supports_tools: bool = True
    strength: int = Field(ge=1, le=5)
    input_cost_per_million: float = Field(ge=0)
    output_cost_per_million: float = Field(ge=0)
    open_source: bool = False
    # Informational only: auto selection never trusts this flag. Open source
    # models earn auto eligibility from signed evaluation results (llm/evidence.py).
    evaluated: bool = False
    # Operator-only endpoint for openai_compatible models (Ollama, vLLM, ...).
    # Excluded from serialization so API responses never reveal internal hosts.
    base_url: str | None = Field(default=None, max_length=512, exclude=True)
    requires_api_key: bool = False

    @model_validator(mode="after")
    def provider_matches_id(self):
        if not self.id.startswith(f"{self.provider}/"):
            raise ValueError("model id must start with its provider and a slash")
        if self.id == f"{self.provider}/":
            raise ValueError("model id needs a model name after the provider")
        if self.provider == OPENAI_COMPATIBLE:
            if not self.base_url:
                raise ValueError("openai_compatible models need a base_url")
            object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        elif self.base_url is not None:
            raise ValueError("base_url is only allowed for openai_compatible models")
        return self

    @property
    def needs_evaluation(self) -> bool:
        """Open weights and self-hosted endpoints join auto only after evidence."""
        return self.open_source or self.provider == OPENAI_COMPATIBLE

    def estimate_cost(self, input_tokens: int = 8000, output_tokens: int = 2000) -> float:
        return (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000


@dataclass(frozen=True)
class ModelSelection:
    model: str
    level: SeatLevel
    selected_level: SeatLevel
    reason: str
    estimated_cost_usd: float | None = None


class ModelSelectionError(ValueError):
    pass
