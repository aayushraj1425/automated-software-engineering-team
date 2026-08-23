"""Streamed replies must feed the spend metrics the same way non-streamed ones
do. The conftest forces LLM_FAKE=1, so these flip it off and stand in a fake
litellm streaming response (content chunks plus a final usage-only chunk)."""

import litellm
import pytest

from engine.llm import router
from engine.llm.router import model_router


class FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeDelta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.delta = FakeDelta(content)


class FakeChunk:
    """A content chunk (one choice) or, when content is None, the usage-only
    final chunk that include_usage adds (no choices)."""

    def __init__(self, content: str | None = None, usage: FakeUsage | None = None) -> None:
        self.choices = [] if content is None else [FakeChoice(content)]
        self.usage = usage


@pytest.fixture
def real_llm(monkeypatch):
    """Turn off fake mode and neutralise the provider key lookup, so stream()
    takes the real litellm path (which the test then stubs)."""
    monkeypatch.setattr(router.get_settings(), "llm_fake", False)
    monkeypatch.setattr(router, "api_key_for_model", lambda model: None)


def stub_stream(monkeypatch, *chunks: FakeChunk) -> None:
    async def fake_acompletion(**kwargs):
        assert kwargs["stream_options"] == {"include_usage": True}

        async def gen():
            for chunk in chunks:
                yield chunk

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


def spy_on_record(monkeypatch) -> dict:
    seen: dict = {}
    monkeypatch.setattr(
        router,
        "record_llm_call",
        lambda tier, model, cost, input_tokens, output_tokens: seen.update(
            tier=tier, model=model, cost=cost, input=input_tokens, output=output_tokens
        ),
    )
    return seen


async def test_stream_yields_text_and_records_usage(real_llm, monkeypatch):
    stub_stream(
        monkeypatch,
        FakeChunk(content="hello "),
        FakeChunk(content="world"),
        FakeChunk(usage=FakeUsage(prompt_tokens=12, completion_tokens=8)),
    )
    monkeypatch.setattr(litellm, "cost_per_token", lambda **kwargs: (0.001, 0.002))
    seen = spy_on_record(monkeypatch)

    text = [t async for t in model_router.stream("cheap", [{"role": "user", "content": "hi"}])]

    assert text == ["hello ", "world"]
    assert seen["input"] == 12
    assert seen["output"] == 8
    assert seen["cost"] == pytest.approx(0.003)


async def test_stream_records_nothing_when_no_usage_chunk(real_llm, monkeypatch):
    # A provider that ignores include_usage sends no usage chunk.
    stub_stream(monkeypatch, FakeChunk(content="hello "), FakeChunk(content="world"))
    seen = spy_on_record(monkeypatch)

    text = [t async for t in model_router.stream("cheap", [{"role": "user", "content": "hi"}])]

    assert text == ["hello ", "world"]
    assert seen == {}


async def test_stream_survives_a_broken_cost_table(real_llm, monkeypatch):
    # Tokens must still be recorded even if cost lookup raises for a new model.
    stub_stream(
        monkeypatch,
        FakeChunk(content="hi"),
        FakeChunk(usage=FakeUsage(prompt_tokens=5, completion_tokens=3)),
    )

    def boom(**kwargs):
        raise KeyError("model not in cost map")

    monkeypatch.setattr(litellm, "cost_per_token", boom)
    seen = spy_on_record(monkeypatch)

    [t async for t in model_router.stream("cheap", [{"role": "user", "content": "hi"}])]

    assert seen["input"] == 5
    assert seen["output"] == 3
    assert seen["cost"] == 0.0
