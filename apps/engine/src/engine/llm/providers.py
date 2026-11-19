"""Turn a catalog model id into the exact arguments for one LiteLLM call.

Only llm/router.py calls LiteLLM; this module just decides which model string,
endpoint, and key to hand it. Keys are matched strictly by provider name, so a
caller's real OpenAI key can never reach a self-hosted endpoint and an endpoint
key can never reach api.openai.com.
"""

from dataclasses import dataclass

from engine.config import Settings
from engine.llm.catalog import OPENAI_COMPATIBLE, ModelEntry, ModelSelectionError
from engine.llm.keys import api_key_for_model

# The OpenAI client refuses to start without a key, and local servers ignore it.
KEYLESS_PLACEHOLDER = "not-needed"


@dataclass(frozen=True)
class CallTarget:
    model: str
    api_key: str | None
    api_base: str | None = None


def server_key_for(settings: Settings, provider: str) -> str:
    if provider == OPENAI_COMPATIBLE:
        return settings.model_openai_compatible_api_key
    return getattr(settings, f"{provider}_api_key", "")


def has_credentials(settings: Settings, entry: ModelEntry) -> bool:
    """Whether a call for this entry could be authenticated right now."""
    if entry.provider == OPENAI_COMPATIBLE and not entry.requires_api_key:
        return True
    return bool(api_key_for_model(entry.id) or server_key_for(settings, entry.provider))


def call_target(model: str, settings: Settings) -> CallTarget:
    """Caller key first, then the server key, for the model's own provider."""
    provider = model.split("/", 1)[0]
    key = api_key_for_model(model) or server_key_for(settings, provider) or None
    if provider != OPENAI_COMPATIBLE:
        return CallTarget(model, key)
    entry = next((m for m in settings.model_catalog if m.id == model), None)
    if entry is None or entry.base_url is None:
        raise ModelSelectionError(f"openai_compatible model {model!r} is not in MODEL_CATALOG")
    if key is None:
        if entry.requires_api_key:
            raise ModelSelectionError(f"model {model!r} needs an openai_compatible API key")
        key = KEYLESS_PLACEHOLDER
    return CallTarget(f"openai/{model.split('/', 1)[1]}", key, entry.base_url)
