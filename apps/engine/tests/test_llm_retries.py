"""The router retries provider hiccups before failing a run. Rate limits and
transient errors have separate budgets, and the sleeps are patched out so the
test is instant."""

from unittest.mock import AsyncMock

import litellm
import pytest

from engine.llm import router
from engine.llm.router import RATE_LIMIT_DELAYS_S, TRANSIENT_DELAYS_S, _call_with_retries


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Never actually wait; record how long each retry would have slept."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(router.asyncio, "sleep", AsyncMock(side_effect=fake_sleep))
    return slept


def rate_limit() -> litellm.exceptions.RateLimitError:
    return litellm.exceptions.RateLimitError("429", llm_provider="openai", model="gpt")


def timeout() -> litellm.exceptions.Timeout:
    return litellm.exceptions.Timeout("timed out", model="gpt", llm_provider="openai")


def flaky(*, fail_times: int, error) -> "tuple":
    """A call that raises `error` the first `fail_times` times, then returns 'ok'."""
    calls = {"n": 0}

    async def call() -> str:
        if calls["n"] < fail_times:
            calls["n"] += 1
            raise error()
        return "ok"

    return call, calls


async def test_returns_immediately_when_the_call_succeeds(no_sleep):
    call, _ = flaky(fail_times=0, error=rate_limit)
    assert await _call_with_retries(call) == "ok"
    assert no_sleep == []


async def test_retries_through_rate_limits_then_succeeds(no_sleep):
    call, calls = flaky(fail_times=2, error=rate_limit)
    assert await _call_with_retries(call) == "ok"
    assert calls["n"] == 2
    assert no_sleep == list(RATE_LIMIT_DELAYS_S[:2])


async def test_retries_transient_errors_on_a_short_backoff(no_sleep):
    call, calls = flaky(fail_times=2, error=timeout)
    assert await _call_with_retries(call) == "ok"
    assert calls["n"] == 2
    assert no_sleep == list(TRANSIENT_DELAYS_S[:2])


async def test_gives_up_after_the_rate_limit_budget_is_exhausted(no_sleep):
    call, _ = flaky(fail_times=99, error=rate_limit)
    with pytest.raises(litellm.exceptions.RateLimitError):
        await _call_with_retries(call)
    # One sleep per delay in the budget, then it re-raises instead of looping forever.
    assert no_sleep == list(RATE_LIMIT_DELAYS_S)


async def test_separate_budgets_for_rate_limits_and_transient_errors(no_sleep):
    # A rate limit then a transient error then success: each spends one delay
    # from its own budget, proving a 429 doesn't eat the transient retries.
    calls = {"n": 0}
    errors = [rate_limit(), timeout()]

    async def call() -> str:
        if calls["n"] < len(errors):
            error = errors[calls["n"]]
            calls["n"] += 1
            raise error
        return "ok"

    assert await _call_with_retries(call) == "ok"
    assert no_sleep == [RATE_LIMIT_DELAYS_S[0], TRANSIENT_DELAYS_S[0]]


async def test_non_retryable_errors_propagate_immediately(no_sleep):
    async def call() -> str:
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        await _call_with_retries(call)
    assert no_sleep == []
