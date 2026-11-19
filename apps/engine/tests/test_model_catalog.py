"""Seat routing tests use synthetic models and never call a provider."""

from types import SimpleNamespace

import litellm
import pytest
from pydantic import ValidationError

from engine.config import Settings
from engine.llm import router
from engine.llm.catalog import ModelEntry, ModelSelectionError, SeatLevel
from engine.llm.keys import provider_keys_var
from engine.llm.router import model_router, selected_model_var, selection_observer_var


def entry(name="engineer", strength=3, price: float = 1, **kwargs):
    return ModelEntry(
        id=f"anthropic/{name}",
        provider="anthropic",
        context_size=100000,
        strength=strength,
        input_cost_per_million=price,
        output_cost_per_million=price,
        **kwargs,
    )


@pytest.fixture
def catalog(monkeypatch):
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        llm_fake=False,
        anthropic_api_key="server-test-key",
        model_catalog=[
            entry("support", 1, 0.1),
            entry(),
            entry("senior", 4, 5),
            entry("principal", 5, 10),
        ],
    )
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    token = provider_keys_var.set({})
    yield settings
    provider_keys_var.reset(token)


def test_auto_selects_cheapest_qualified_tool_model(catalog):
    catalog.model_catalog += [
        entry("expensive", price=9),
        entry("no-tools", price=0, supports_tools=False),
    ]
    pick = model_router.resolve_seat("engineer")
    assert pick.model == "anthropic/engineer"
    assert pick.selected_level == SeatLevel.ENGINEER
    assert "cheapest" in pick.reason


def test_availability_checks_personal_and_server_keys(catalog):
    catalog.anthropic_api_key = ""
    with pytest.raises(ModelSelectionError):
        model_router.resolve_seat("engineer")
    token = provider_keys_var.set({"anthropic": "personal-test-key"})
    try:
        assert model_router.resolve_seat("engineer").model == "anthropic/engineer"
    finally:
        provider_keys_var.reset(token)


def test_pin_precedence_and_invalid_pins(catalog):
    catalog.model_level_pins = {SeatLevel.ENGINEER: "anthropic/senior"}
    org = {"engineer": "anthropic/principal"}
    assert model_router.resolve_seat("engineer").model == "anthropic/senior"
    assert model_router.resolve_seat("engineer", org_overrides=org).model == "anthropic/principal"
    assert (
        model_router.resolve_seat(
            "engineer", {"engineer": "anthropic/engineer"}, org_overrides=org
        ).model
        == "anthropic/engineer"
    )
    with pytest.raises(ModelSelectionError, match="unknown or unavailable"):
        model_router.resolve_seat("engineer", {"engineer": "anthropic/missing"})
    with pytest.raises(ModelSelectionError, match="exceeds"):
        model_router.resolve_seat("engineer", {"engineer": "anthropic/principal"}, budget=0.001)


def test_budget_lowers_only_one_level(catalog):
    pick = model_router.resolve_seat("senior", budget=0.02)
    assert pick.model == "anthropic/engineer"
    assert pick.selected_level == SeatLevel.ENGINEER
    assert "budget lowered senior to engineer" in pick.reason
    with pytest.raises(ModelSelectionError):
        model_router.resolve_seat("principal", budget=0.02)
    for budget in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ModelSelectionError):
            model_router.resolve_seat("engineer", budget=budget)


def test_missing_strength_does_not_silently_downgrade(catalog):
    catalog.model_catalog = [entry()]
    with pytest.raises(ModelSelectionError):
        model_router.resolve_seat("senior", budget=100)


def test_open_source_never_auto_selected_in_this_increment(catalog):
    catalog.model_catalog.insert(0, entry("local", price=0, open_source=True, evaluated=True))
    assert model_router.resolve_seat("engineer").model == "anthropic/engineer"
    assert model_router.resolve_seat("engineer", {"engineer": "anthropic/local"}).model.endswith(
        "/local"
    )


def test_legacy_defaults_and_context_restore(catalog):
    catalog.model_catalog = []
    pick = model_router.resolve_seat("senior")
    assert pick.model == catalog.model_planner
    assert pick.reason == "legacy: MODEL_PLANNER"
    token = selected_model_var.set(pick)
    try:
        assert model_router.resolve("coder") == catalog.model_planner
    finally:
        selected_model_var.reset(token)
    assert model_router.resolve("coder") == catalog.model_coder


def test_config_rejects_invalid_catalog(catalog):
    for models, pins in [([entry(), entry()], {}), ([entry()], {"engineer": "missing"})]:
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,  # pyright: ignore[reportCallIssue]
                model_catalog=models,
                model_level_pins=pins,
            )
    with pytest.raises(ValidationError):
        entry(price=-1)
    with pytest.raises(ValidationError):
        entry(price=float("nan"))


async def test_selected_model_is_called_and_unknown_price_uses_catalog(catalog, monkeypatch):
    seen = []

    async def completion(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="done", tool_calls=[], model_dump=lambda **_: {"content": "done"}
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )

    def missing_price(**kwargs):
        raise KeyError("unknown synthetic model")

    monkeypatch.setattr(litellm, "acompletion", completion)
    monkeypatch.setattr(litellm, "completion_cost", missing_price)
    token = selected_model_var.set(model_router.resolve_seat("senior"))
    try:
        turn = await model_router.complete_with_tools("coder", [])
    finally:
        selected_model_var.reset(token)
    assert seen[0]["model"] == "anthropic/senior"
    assert seen[0]["api_key"] == "server-test-key"
    assert turn.cost_usd == pytest.approx(0.00075)


async def test_transient_failure_falls_back_same_strength_and_records_pick(catalog, monkeypatch):
    catalog.model_catalog += [entry("backup", 4, 4), entry("costly", 4, 6)]
    calls, picks = [], []

    async def completion(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "anthropic/senior":
            raise litellm.exceptions.ServiceUnavailableError(
                message="down", model="senior", llm_provider="anthropic"
            )
        return "response"

    async def observe(pick):
        picks.append(pick)

    monkeypatch.setattr(router, "TRANSIENT_DELAYS_S", ())
    monkeypatch.setattr(litellm, "acompletion", completion)
    pick = model_router.resolve_seat("senior", {"senior": "anthropic/senior"})
    token = selected_model_var.set(pick)
    observer = selection_observer_var.set(observe)
    try:
        response, model = await model_router._agent_completion(pick.model, messages=[])
        selected = selected_model_var.get()
        assert selected is not None and selected.model == "anthropic/backup"
    finally:
        selection_observer_var.reset(observer)
        selected_model_var.reset(token)
    assert response == "response"
    assert model == "anthropic/backup"
    assert calls == ["anthropic/senior", "anthropic/backup"]
    assert len(picks) == 1 and "fallback" in picks[0].reason
