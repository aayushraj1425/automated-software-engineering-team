import asyncio
import hashlib
import json
import math
import struct
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import structlog

from engine.config import EMBEDDING_DIM, get_settings

Tier = Literal["planner", "coder", "cheap"]

log = structlog.get_logger(__name__)

FAKE_REPLY = (
    "This is a canned reply from the ASEP walking skeleton (LLM_FAKE=1). "
    "Set a provider key in .env to talk to a real model."
)


# Free-tier and burst-heavy providers throttle hard; wait and retry before
# failing a whole agent run over a temporary 429.
RATE_LIMIT_DELAYS_S = (15, 30, 60)


async def _retry_rate_limits[T](call: Callable[[], Awaitable[T]]) -> T:
    """Run an LLM call, sleeping through provider rate limits before giving up."""
    import litellm

    for attempt, delay in enumerate(RATE_LIMIT_DELAYS_S, start=1):
        try:
            return await call()
        except litellm.exceptions.RateLimitError:
            log.warning("llm.rate_limited", attempt=attempt, retry_in_s=delay)
            await asyncio.sleep(delay)
    return await call()


def _fake_embedding(text: str) -> list[float]:
    """Deterministic stand-in vector: same text, same vector, unit length."""
    values: list[float] = []
    seed = text.encode("utf-8", errors="replace")
    counter = 0
    while len(values) < EMBEDDING_DIM:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for offset in range(0, len(digest) - 3, 4):
            (raw,) = struct.unpack_from(">i", digest, offset)
            values.append(raw / 2**31)
        counter += 1
    values = values[:EMBEDDING_DIM]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AssistantTurn:
    """One assistant reply: a final text answer and/or a batch of tool calls."""

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    message: dict[str, Any]  # appended verbatim to the conversation history
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


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

        response = await _retry_rate_limits(
            lambda: litellm.acompletion(model=model, messages=messages, stream=True)
        )
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

        response = await _retry_rate_limits(
            lambda: litellm.acompletion(model=model, messages=messages)
        )
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

    async def complete_with_tools(
        self, tier: Tier, messages: list[dict[str, Any]], tools: list[dict] | None = None
    ) -> AssistantTurn:
        """One agent turn: the model answers or asks to call tools."""
        settings = get_settings()
        model = self.resolve(tier)
        if settings.llm_fake:
            return AssistantTurn(
                content=FAKE_REPLY,
                tool_calls=(),
                message={"role": "assistant", "content": FAKE_REPLY},
            )

        import litellm

        started = time.monotonic()
        response = await _retry_rate_limits(
            lambda: litellm.acompletion(model=model, messages=messages, tools=tools or None)
        )
        message = response.choices[0].message  # type: ignore[union-attr]
        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(id=call.id, name=call.function.name or "", arguments=arguments))
        usage = getattr(response, "usage", None)
        try:
            cost = float(litellm.completion_cost(completion_response=response))
        except Exception:  # cost tables lag behind new models; usage still counts
            cost = 0.0
        log.info(
            "llm.tools",
            tier=tier,
            model=model,
            tool_calls=[c.name for c in calls],
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return AssistantTurn(
            content=message.content,
            tool_calls=tuple(calls),
            message=message.model_dump(exclude_none=True),
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cost_usd=cost,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One EMBEDDING_DIM vector per text (MODEL_EMBEDDING; fake mode is
        deterministic so index/search tests run offline)."""
        settings = get_settings()
        if settings.llm_fake:
            return [_fake_embedding(text) for text in texts]

        import litellm

        started = time.monotonic()
        response = await _retry_rate_limits(
            lambda: litellm.aembedding(model=settings.model_embedding, input=texts)
        )
        vectors = [item["embedding"] for item in response.data]  # type: ignore[union-attr]
        log.info(
            "llm.embed",
            model=settings.model_embedding,
            texts=len(texts),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return vectors


model_router = ModelRouter()
