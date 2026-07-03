import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import structlog

from engine.config import get_settings

Tier = Literal["planner", "coder", "cheap"]

log = structlog.get_logger(__name__)

FAKE_REPLY = (
    "This is a canned reply from the ASEP walking skeleton (LLM_FAKE=1). "
    "Set a provider key in .env to talk to a real model."
)


class ModelRouter:
    """The single gateway for all LLM traffic (ADR-0006).

    Callers ask for a tier, never a concrete model; env maps tiers to models.
    Nothing outside this module may import litellm.
    """

    def resolve(self, tier: Tier) -> str:
        s = get_settings()
        return {"planner": s.model_planner, "coder": s.model_coder, "cheap": s.model_cheap}[tier]

    async def stream(self, tier: Tier, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        settings = get_settings()
        model = self.resolve(tier)
        started = time.monotonic()

        if settings.llm_fake:
            for word in FAKE_REPLY.split(" "):
                yield word + " "
            log.info("llm.stream", tier=tier, model="fake", duration_ms=0)
            return

        import litellm

        response = await litellm.acompletion(model=model, messages=messages, stream=True)
        chunks = 0
        async for chunk in response:  # type: ignore[union-attr]
            delta = chunk.choices[0].delta.content  # type: ignore[union-attr]
            if delta:
                chunks += 1
                yield delta
        log.info(
            "llm.stream",
            tier=tier,
            model=model,
            chunks=chunks,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def complete(self, tier: Tier, messages: list[dict[str, Any]]) -> str:
        settings = get_settings()
        model = self.resolve(tier)
        if settings.llm_fake:
            return FAKE_REPLY

        import litellm

        response = await litellm.acompletion(model=model, messages=messages)
        content = response.choices[0].message.content  # type: ignore[union-attr]
        usage = getattr(response, "usage", None)
        log.info(
            "llm.complete",
            tier=tier,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )
        return content or ""


model_router = ModelRouter()
