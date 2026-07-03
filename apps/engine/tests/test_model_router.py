from engine.config import get_settings
from engine.llm.router import FAKE_REPLY, model_router


def test_resolve_maps_tiers_to_configured_models():
    settings = get_settings()
    assert model_router.resolve("planner") == settings.model_planner
    assert model_router.resolve("coder") == settings.model_coder
    assert model_router.resolve("cheap") == settings.model_cheap


async def test_fake_mode_streams_canned_reply():
    chunks = [c async for c in model_router.stream("cheap", [{"role": "user", "content": "hi"}])]
    assert len(chunks) > 1
    assert "".join(chunks).strip() == FAKE_REPLY


async def test_fake_mode_complete():
    result = await model_router.complete("planner", [{"role": "user", "content": "hi"}])
    assert result == FAKE_REPLY
