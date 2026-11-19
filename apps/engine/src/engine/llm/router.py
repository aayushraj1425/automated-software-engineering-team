import asyncio
import hashlib
import json
import math
import struct
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Literal

import structlog
from opentelemetry import trace

from engine.config import EMBEDDING_DIM, get_settings
from engine.llm.catalog import (
    MIN_STRENGTH,
    ModelEntry,
    ModelSelection,
    ModelSelectionError,
    SeatLevel,
)
from engine.llm.evidence import check_evidence, effective_strength
from engine.llm.keys import api_key_for_model
from engine.llm.providers import call_target, has_credentials
from engine.observability import record_llm_call

Tier = Literal["planner", "coder", "cheap"]

# Scoped by the runner and reset after each agent invocation, including errors.
selected_model_var: ContextVar[ModelSelection | None] = ContextVar("selected_model", default=None)
selection_observer_var: ContextVar[Callable[[ModelSelection], Awaitable[None]] | None] = ContextVar(
    "selection_observer", default=None
)

log = structlog.get_logger(__name__)

# No-op until the SDK is configured (OTEL_ENABLED — see engine/observability.py).
_tracer = trace.get_tracer("engine.llm")

FAKE_REPLY = (
    "This is a canned reply from the ASEP walking skeleton (LLM_FAKE=1). "
    "Set a provider key in .env to talk to a real model."
)


# Free-tier and burst-heavy providers throttle hard; wait and retry before
# failing a whole agent run over a temporary 429.
RATE_LIMIT_DELAYS_S = (15, 30, 60)
# Transient provider failures (a dropped connection, a request timeout, a 5xx)
# deserve a quick retry rather than failing the run — short backoff, and a
# separate budget so a burst of 429s can't spend the retries meant for a flaky
# connection (and vice versa).
TRANSIENT_DELAYS_S = (1, 2, 4)


async def _call_with_retries[T](call: Callable[[], Awaitable[T]]) -> T:
    """Run an LLM call, retrying through provider rate limits (long waits) and
    transient failures (short backoff) before giving up. Each failure class has
    its own attempt budget; anything else propagates immediately."""
    import litellm

    rate_limit_delays = iter(RATE_LIMIT_DELAYS_S)
    transient_delays = iter(TRANSIENT_DELAYS_S)
    while True:
        try:
            return await call()
        except litellm.exceptions.RateLimitError:
            delay = next(rate_limit_delays, None)
            if delay is None:
                raise
            log.warning("llm.rate_limited", retry_in_s=delay)
            await asyncio.sleep(delay)
        except (
            litellm.exceptions.Timeout,
            litellm.exceptions.APIConnectionError,
            litellm.exceptions.ServiceUnavailableError,
            litellm.exceptions.InternalServerError,
        ) as error:
            delay = next(transient_delays, None)
            if delay is None:
                raise
            log.warning("llm.transient_error", error=type(error).__name__, retry_in_s=delay)
            await asyncio.sleep(delay)


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
        if selected := selected_model_var.get():
            return selected.model
        s = get_settings()
        return {"planner": s.model_planner, "coder": s.model_coder, "cheap": s.model_cheap}[tier]

    def _available(self, entry: ModelEntry) -> bool:
        settings = get_settings()
        return settings.llm_fake or has_credentials(settings, entry)

    def resolve_seat(
        self,
        level: SeatLevel | str,
        overrides: dict[str, str] | None = None,
        budget: float | None = None,
        org_overrides: dict[str, str] | None = None,
        *,
        allow_open_source_auto: bool = False,
    ) -> ModelSelection:
        """Pick an available tool model; budget estimates are per model turn.

        Open source and self-hosted models join auto only when the caller passes
        allow_open_source_auto (the organization's opt-in) AND signed evaluation
        results for that exact model verify (llm/evidence.py). The catalog's
        `evaluated` flag never counts. Pins skip this gate: a human chose them.

        A budget can lower auto selection by one level. Pins are explicit and
        fail clearly when unavailable or unaffordable rather than being ignored.
        The existing run cap remains authoritative for accumulated actual spend.
        """
        level = SeatLevel(level)
        if budget is not None and (not math.isfinite(budget) or budget <= 0):
            raise ModelSelectionError("remaining model budget must be positive and finite")
        settings = get_settings()
        if not settings.model_catalog:
            if overrides or org_overrides:
                raise ModelSelectionError("model overrides require MODEL_CATALOG")
            tier = {
                SeatLevel.SUPPORT: "cheap",
                SeatLevel.ENGINEER: "coder",
                SeatLevel.SENIOR: "planner",
                SeatLevel.PRINCIPAL: "planner",
            }[level]
            model = getattr(settings, f"model_{tier}")
            return ModelSelection(model, level, level, f"legacy: MODEL_{tier.upper()}")

        pin = (overrides or {}).get(level)
        reason = "pinned for seat"
        if pin is None:
            pin = (org_overrides or {}).get(level) or settings.model_level_pins.get(level)
            reason = (
                "pinned by organization"
                if (org_overrides or {}).get(level)
                else "pinned in settings"
            )
        if pin is not None:
            entry = next((m for m in settings.model_catalog if m.id == pin), None)
            if entry is None or not entry.supports_tools or not self._available(entry):
                raise ModelSelectionError(f"pinned model {pin!r} is unknown or unavailable")
            if budget is not None and entry.estimate_cost() > budget:
                raise ModelSelectionError(f"pinned model {pin!r} exceeds the remaining budget")
            if entry.needs_evaluation and not check_evidence(entry, settings).eligible:
                reason += "; open source model without passing evaluation results"
            return ModelSelection(entry.id, level, level, reason, entry.estimate_cost())

        # (entry, strength auto may rely on): open source strength comes from evidence.
        candidates: list[tuple[ModelEntry, int]] = []
        for m in settings.model_catalog:
            if not m.supports_tools or not self._available(m):
                continue
            if not m.needs_evaluation:
                candidates.append((m, m.strength))
            elif allow_open_source_auto and (strength := effective_strength(m, settings)) > 0:
                candidates.append((m, strength))
        candidates.sort(key=lambda c: (c[0].estimate_cost(), c[0].id))
        levels = list(SeatLevel)
        for selected_level in (level, levels[max(0, levels.index(level) - 1)]):
            # Downgrade only for budget pressure, never because a key is missing.
            qualified = [c for c in candidates if c[1] >= MIN_STRENGTH[selected_level]]
            affordable = [c for c in qualified if budget is None or c[0].estimate_cost() <= budget]
            if affordable:
                entry = affordable[0][0]
                reason = f"auto: cheapest at strength {MIN_STRENGTH[selected_level]} or above"
                if entry.needs_evaluation:
                    reason += " (open source, passed evaluation, organization allows it)"
                if selected_level != level:
                    reason += f"; budget lowered {level} to {selected_level}"
                return ModelSelection(
                    entry.id, level, selected_level, reason, entry.estimate_cost()
                )
            if budget is None or not any(c[1] >= MIN_STRENGTH[level] for c in candidates):
                break
        raise ModelSelectionError(f"no available model for {level} within the remaining budget")

    def _catalog_entry(self, model: str) -> ModelEntry | None:
        return next((m for m in get_settings().model_catalog if m.id == model), None)

    def _catalog_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        entry = self._catalog_entry(model)
        return entry.estimate_cost(input_tokens, output_tokens) if entry else 0.0

    def _turn_cost(
        self, model: str, input_tokens: int, output_tokens: int, vendor_cost: Callable[[], float]
    ) -> float:
        """Self-hosted and open source models always use the operator's catalog price:
        LiteLLM's table can match a look-alike hosted model and charge the wrong
        amount. Everything else prefers LiteLLM and falls back to the catalog."""
        entry = self._catalog_entry(model)
        if entry is not None and entry.needs_evaluation:
            return entry.estimate_cost(input_tokens, output_tokens)
        try:
            return float(vendor_cost())
        except Exception:  # cost tables lag behind new models; usage still counts
            return self._catalog_cost(model, input_tokens, output_tokens)

    def _usage_tokens(
        self, model: str, usage: Any, prompt_chars: int, completion_chars: int
    ) -> tuple[int, int]:
        """Provider-reported tokens. A self-hosted server that omits usage would
        otherwise look free, so estimate roughly four characters per token."""
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        entry = self._catalog_entry(model)
        if entry is not None and entry.needs_evaluation and not (input_tokens or output_tokens):
            input_tokens = -(-prompt_chars // 4)
            output_tokens = -(-completion_chars // 4)
            if input_tokens or output_tokens:
                log.warning("llm.usage_estimated", model=model)
        return input_tokens, output_tokens

    async def _agent_completion(self, model: str, **kwargs: Any) -> tuple[Any, str]:
        """Retry first, then fail over to a model of the same strength.

        A fallback never weakens the seat: it must keep the original strength,
        stay within its cost ceiling, and offer at least its context size. Open
        source models are neither fallback targets (the router cannot see the
        organization opt-in) nor do they fall back, so a failure surfaces."""
        import litellm

        settings = get_settings()
        selection = selected_model_var.get()
        original = self._catalog_entry(model)
        alternatives: list[ModelEntry] = []
        if selection is not None and original is not None and not original.needs_evaluation:
            alternatives = sorted(
                (
                    m
                    for m in settings.model_catalog
                    if m.id != model
                    and m.strength == original.strength
                    and m.context_size >= original.context_size
                    and m.supports_tools
                    and not m.needs_evaluation
                    and self._available(m)
                    and m.estimate_cost() <= original.estimate_cost()
                ),
                key=lambda m: (m.estimate_cost(), m.id),
            )
        models = [model, *(m.id for m in alternatives)]
        for index, candidate in enumerate(models):
            target = call_target(candidate, settings)
            try:
                response = await _call_with_retries(
                    lambda target=target: litellm.acompletion(
                        model=target.model,
                        api_key=target.api_key,
                        api_base=target.api_base,
                        timeout=settings.llm_request_timeout_seconds or None,
                        **kwargs,
                    )
                )
            except (
                litellm.exceptions.RateLimitError,
                litellm.exceptions.Timeout,
                litellm.exceptions.APIConnectionError,
                litellm.exceptions.ServiceUnavailableError,
                litellm.exceptions.InternalServerError,
            ):
                if index == len(models) - 1:
                    raise
                continue
            if candidate != model and selection is not None:
                selection = replace(
                    selection,
                    model=candidate,
                    reason=f"fallback: {model} unavailable; same strength and cost ceiling",
                    estimated_cost_usd=self._catalog_cost(candidate, 8000, 2000),
                )
                if observer := selection_observer_var.get():
                    await observer(selection)
                selected_model_var.set(selection)
            return response, candidate
        raise RuntimeError("no completion candidates")  # models always contains the original

    def _record_stream_usage(
        self,
        span: trace.Span,
        tier: Tier,
        model: str,
        usage: Any,
        prompt_chars: int = 0,
        completion_chars: int = 0,
    ) -> None:
        """Record a streamed reply's tokens and cost the same way the non-stream
        paths do. A provider that ignores include_usage costs nothing but a missing
        metric, except self-hosted models, which fall back to a size estimate."""
        import litellm

        input_tokens, output_tokens = self._usage_tokens(
            model, usage, prompt_chars, completion_chars
        )
        if usage is None and not (input_tokens or output_tokens):
            return

        def vendor_cost() -> float:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
            )
            return prompt_cost + completion_cost

        cost = self._turn_cost(model, input_tokens, output_tokens, vendor_cost)
        span.set_attribute("llm.input_tokens", input_tokens)
        span.set_attribute("llm.output_tokens", output_tokens)
        span.set_attribute("llm.cost_usd", cost)
        record_llm_call(tier, model, cost, input_tokens, output_tokens)

    async def stream(self, tier: Tier, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        settings = get_settings()
        model = self.resolve(tier)
        started = time.monotonic()
        # A manual span (not a context manager): a generator's body runs across
        # many awaits, so the span is ended in `finally` when the stream closes.
        span = _tracer.start_span(
            "llm.stream",
            attributes={"llm.tier": tier, "llm.model": "fake" if settings.llm_fake else model},
        )
        try:
            if settings.llm_fake:
                for word in FAKE_REPLY.split(" "):
                    yield word + " "
                log.info("llm.stream", tier=tier, model="fake", duration_ms=0)
                return

            import litellm

            target = call_target(model, settings)
            response = await _call_with_retries(
                lambda: litellm.acompletion(
                    model=target.model,
                    messages=messages,
                    stream=True,
                    api_key=target.api_key,
                    api_base=target.api_base,
                    timeout=settings.llm_request_timeout_seconds or None,
                    # Ask for a final usage-bearing chunk so streamed replies
                    # count toward the spend metrics like non-streamed ones do.
                    stream_options={"include_usage": True},
                )
            )
            chunks = 0
            streamed_chars = 0
            usage: Any = None
            async for chunk in response:  # type: ignore[union-attr]
                # The usage-only final chunk (include_usage) carries no choices.
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:  # type: ignore[union-attr]
                    continue
                delta = chunk.choices[0].delta.content  # type: ignore[union-attr]
                if delta:
                    chunks += 1
                    streamed_chars += len(delta)
                    yield delta
            self._record_stream_usage(
                span,
                tier,
                model,
                usage,
                len(json.dumps(messages, default=str)),
                streamed_chars,
            )
            span.set_attribute("llm.chunks", chunks)
            log.info(
                "llm.stream",
                tier=tier,
                model=model,
                chunks=chunks,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            span.end()

    async def complete(self, tier: Tier, messages: list[dict[str, Any]]) -> str:
        settings = get_settings()
        model = self.resolve(tier)
        with _tracer.start_as_current_span(
            "llm.complete",
            attributes={"llm.tier": tier, "llm.model": "fake" if settings.llm_fake else model},
        ) as span:
            if settings.llm_fake:
                return FAKE_REPLY

            import litellm

            # The caller's own key wins over the server's .env key (PROVIDER_KEYS.md).
            target = call_target(model, settings)
            response = await _call_with_retries(
                lambda: litellm.acompletion(
                    model=target.model,
                    messages=messages,
                    api_key=target.api_key,
                    api_base=target.api_base,
                    timeout=settings.llm_request_timeout_seconds or None,
                )
            )
            content = response.choices[0].message.content  # type: ignore[union-attr]
            usage = getattr(response, "usage", None)
            input_tokens, output_tokens = self._usage_tokens(
                model,
                usage,
                len(json.dumps(messages, default=str)),
                len(content or ""),
            )
            cost = self._turn_cost(
                model,
                input_tokens,
                output_tokens,
                lambda: litellm.completion_cost(completion_response=response),
            )
            span.set_attribute("llm.input_tokens", input_tokens)
            span.set_attribute("llm.output_tokens", output_tokens)
            span.set_attribute("llm.cost_usd", cost)
            record_llm_call(tier, model, cost, input_tokens, output_tokens)
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
        with _tracer.start_as_current_span(
            "llm.tools",
            attributes={"llm.tier": tier, "llm.model": "fake" if settings.llm_fake else model},
        ) as span:
            if settings.llm_fake:
                return AssistantTurn(
                    content=FAKE_REPLY,
                    tool_calls=(),
                    message={"role": "assistant", "content": FAKE_REPLY},
                )

            import litellm

            started = time.monotonic()
            response, model = await self._agent_completion(
                model, messages=messages, tools=tools or None
            )
            span.set_attribute("llm.model", model)
            message = response.choices[0].message  # type: ignore[union-attr]
            calls: list[ToolCall] = []
            for call in message.tool_calls or []:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                calls.append(
                    ToolCall(id=call.id, name=call.function.name or "", arguments=arguments)
                )
            usage = getattr(response, "usage", None)
            input_tokens, output_tokens = self._usage_tokens(
                model,
                usage,
                len(json.dumps(messages, default=str)),
                len(message.content or "")
                + sum(len(json.dumps(c.arguments, default=str)) for c in calls),
            )
            cost = self._turn_cost(
                model,
                input_tokens,
                output_tokens,
                lambda: litellm.completion_cost(completion_response=response),
            )
            span.set_attribute("llm.input_tokens", input_tokens)
            span.set_attribute("llm.output_tokens", output_tokens)
            span.set_attribute("llm.cost_usd", cost)
            span.set_attribute("llm.tool_calls", len(calls))
            record_llm_call(tier, model, cost, input_tokens, output_tokens)
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
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One EMBEDDING_DIM vector per text (MODEL_EMBEDDING; fake mode is
        deterministic so index/search tests run offline)."""
        settings = get_settings()
        with _tracer.start_as_current_span(
            "llm.embed",
            attributes={
                "llm.model": "fake" if settings.llm_fake else settings.model_embedding,
                "llm.texts": len(texts),
            },
        ):
            if settings.llm_fake:
                return [_fake_embedding(text) for text in texts]

            return await self._embed_real(texts)

    async def _embed_real(self, texts: list[str]) -> list[list[float]]:
        settings = get_settings()
        started = time.monotonic()

        if settings.model_embedding.startswith("gemini/"):
            vectors = await self._embed_gemini_direct(texts)
        else:
            import litellm

            response = await _call_with_retries(
                lambda: litellm.aembedding(
                    model=settings.model_embedding,
                    input=texts,
                    api_key=api_key_for_model(settings.model_embedding),
                    timeout=settings.llm_request_timeout_seconds or None,
                )
            )
            vectors = [item["embedding"] for item in response.data]  # type: ignore[union-attr]

        log.info(
            "llm.embed",
            model=settings.model_embedding,
            texts=len(texts),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return vectors

    async def _embed_gemini_direct(self, texts: list[str]) -> list[list[float]]:
        """Call the Google AI Studio batchEmbedContents endpoint directly.
        LiteLLM routes gemini/ embedding models through its Vertex AI handler
        which targets v1beta — text-embedding-004 only exists on v1."""
        import httpx

        settings = get_settings()
        model = settings.model_embedding.removeprefix("gemini/")
        api_key = api_key_for_model(settings.model_embedding) or settings.gemini_api_key
        requests = [
            {"model": f"models/{model}", "content": {"parts": [{"text": t}]}} for t in texts
        ]
        timeout = settings.llm_request_timeout_seconds or None
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1/models/{model}:batchEmbedContents",
                json={"requests": requests},
                params={"key": api_key},
                timeout=timeout,
            )
            if not resp.is_success:
                raise RuntimeError(f"Gemini embed {resp.status_code}: {resp.text}")
        return [item["values"] for item in resp.json()["embeddings"]]


model_router = ModelRouter()
