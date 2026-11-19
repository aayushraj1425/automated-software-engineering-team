"""Open source model support: endpoints, credentials, evidence gate, fallback, cost.

Everything uses stub providers and synthetic models. Nothing here calls a model, so
none of it proves a real Ollama or vLLM model passes: only the evaluation script run
against that model can (docs/architecture/agents/OPEN_SOURCE_MODELS.md).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import litellm
import pytest
from pydantic import ValidationError

from engine.config import Settings
from engine.evaluation import GOLDEN_TASKS
from engine.llm import evidence as evidence_module
from engine.llm import router
from engine.llm.catalog import ModelEntry, ModelSelectionError, SeatLevel
from engine.llm.evaluate import evaluate_model, pinned_for_evaluation
from engine.llm.evidence import (
    EvaluationEvidence,
    ProbeEvidence,
    TaskEvidence,
    build_evidence,
    check_evidence,
    effective_strength,
    evidence_path,
    save_evidence,
)
from engine.llm.keys import provider_keys_var
from engine.llm.probes import PROBE_TOOLS, PROBES, run_probe, run_probes
from engine.llm.providers import call_target
from engine.llm.router import (
    AssistantTurn,
    ToolCall,
    model_router,
    selected_model_var,
    selection_observer_var,
)

LOCAL_URL = "http://localhost:11434/v1"
LOCAL = "openai_compatible/qwen-local"


def paid(name="engineer", strength=3, price: float = 1, **kwargs):
    fields = {
        "id": f"anthropic/{name}",
        "provider": "anthropic",
        "context_size": 100000,
        "strength": strength,
        "input_cost_per_million": price,
        "output_cost_per_million": price,
    }
    return ModelEntry(**{**fields, **kwargs})


def local(name="qwen-local", strength=3, price: float = 0, **kwargs):
    fields = {
        "id": f"openai_compatible/{name}",
        "provider": "openai_compatible",
        "base_url": LOCAL_URL,
        "context_size": 32000,
        "strength": strength,
        "input_cost_per_million": price,
        "output_cost_per_million": price,
        "open_source": True,
    }
    return ModelEntry(**{**fields, **kwargs})


@pytest.fixture
def world(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        llm_fake=False,
        engine_service_secret="unit-test-secret-0123456789abcdef",
        anthropic_api_key="server-anthropic",
        openai_api_key="server-openai",
        model_evaluation_dir=str(tmp_path / "evals"),
        model_catalog=[paid("support", 1, 0.1), paid(), paid("senior", 4, 5), local()],
    )
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    token = provider_keys_var.set({})
    yield settings
    provider_keys_var.reset(token)


def passing_tasks():
    return [
        TaskEvidence(
            name=t["name"], planned=True, completed=True, committed=True, diff_matched=True,
            cost_usd=0.0,
        )
        for t in GOLDEN_TASKS
    ]  # fmt: skip


def passing_probes():
    return [ProbeEvidence(name=p.name, passed=True) for p in PROBES]


def certify(settings, entry=None, *, tasks=None, probes=None, now=None, store=True):
    entry = entry or settings.model_catalog[-1]
    evidence = build_evidence(
        entry,
        tasks if tasks is not None else passing_tasks(),
        probes if probes is not None else passing_probes(),
        settings,
        now=now,
    )
    if store:
        save_evidence(evidence, settings)
    return evidence


# ----- catalog entries -------------------------------------------------------


def test_openai_compatible_entry_needs_a_clean_base_url():
    assert local(base_url=LOCAL_URL + "/").base_url == LOCAL_URL
    for bad in (
        None,
        "ftp://host/v1",
        "http://user:pw@host/v1",
        "http://host/v1?key=1",
        "http://169.254.169.254/v1",
        "localhost:11434",
    ):
        with pytest.raises(ValidationError):
            local(base_url=bad)
    with pytest.raises(ValidationError):
        paid(base_url=LOCAL_URL)
    with pytest.raises(ValidationError):
        ModelEntry(
            id="openai_compatible/", provider="openai_compatible", base_url=LOCAL_URL,
            context_size=1, strength=1, input_cost_per_million=0, output_cost_per_million=0,
        )  # fmt: skip


def test_endpoint_url_is_never_serialized():
    assert "base_url" not in local().model_dump()
    assert LOCAL_URL not in local().model_dump_json()


# ----- credential mapping ----------------------------------------------------


def test_keyless_local_endpoint_maps_to_openai_adapter(world):
    target = call_target(LOCAL, world)
    assert target.model == "openai/qwen-local"
    assert target.api_base == LOCAL_URL
    assert target.api_key == "not-needed"


def test_credentials_never_cross_providers(world):
    world.model_catalog.append(local("keyed", requires_api_key=True))
    world.model_openai_compatible_api_key = "server-endpoint-key"
    caller = provider_keys_var.set({"openai": "callers-real-openai", "anthropic": "callers-claude"})
    try:
        # The caller's OpenAI key must not reach the local endpoint.
        assert call_target("openai_compatible/keyed", world).api_key == "server-endpoint-key"
        assert call_target(LOCAL, world).api_key == "server-endpoint-key"
        # ... and the endpoint key must not reach OpenAI or Anthropic.
        assert call_target("openai/gpt-x", world) == call_target("openai/gpt-x", world)
        assert call_target("openai/gpt-x", world).api_key == "callers-real-openai"
        assert call_target("anthropic/engineer", world).api_key == "callers-claude"
    finally:
        provider_keys_var.reset(caller)
    own = provider_keys_var.set({"openai_compatible": "callers-endpoint-key"})
    try:
        assert call_target("openai_compatible/keyed", world).api_key == "callers-endpoint-key"
        assert call_target("openai/gpt-x", world).api_key == "server-openai"
    finally:
        provider_keys_var.reset(own)


def test_endpoint_needing_a_key_is_unavailable_without_one(world):
    world.model_catalog.append(local("keyed", requires_api_key=True))
    keyed = world.model_catalog[-1]
    assert not model_router._available(keyed)
    with pytest.raises(ModelSelectionError, match="unknown or unavailable"):
        model_router.resolve_seat("engineer", {"engineer": keyed.id})
    with pytest.raises(ModelSelectionError, match="needs an openai_compatible API key"):
        call_target(keyed.id, world)
    world.model_openai_compatible_api_key = "k"
    assert model_router._available(keyed)


def test_unknown_openai_compatible_model_is_rejected(world):
    with pytest.raises(ModelSelectionError, match="not in MODEL_CATALOG"):
        call_target("openai_compatible/not-configured", world)


# ----- auto selection needs opt-in AND evidence ------------------------------


def test_configured_evaluated_flag_alone_never_certifies(world):
    world.model_catalog[-1] = local(evaluated=True)
    pick = model_router.resolve_seat("engineer", allow_open_source_auto=True)
    assert pick.model == "anthropic/engineer"


def test_valid_evidence_without_org_opt_in_is_not_enough(world):
    certify(world)
    assert model_router.resolve_seat("engineer").model == "anthropic/engineer"
    assert (
        model_router.resolve_seat("engineer", allow_open_source_auto=False).model
        == "anthropic/engineer"
    )


def test_opt_in_plus_valid_evidence_selects_open_source(world):
    certify(world)
    pick = model_router.resolve_seat("engineer", allow_open_source_auto=True)
    assert pick.model == LOCAL
    assert pick.selected_level == SeatLevel.ENGINEER
    assert "open source" in pick.reason and pick.reason.startswith("auto: cheapest")


def test_evidence_caps_strength_below_senior(world):
    world.model_catalog[-1] = local(strength=5)
    certify(world)
    assert effective_strength(world.model_catalog[-1], world) == 3
    assert model_router.resolve_seat("senior", allow_open_source_auto=True).model == (
        "anthropic/senior"
    )
    # A claimed strength lower than the proven one still wins.
    world.model_catalog[-1] = local(strength=2)
    assert effective_strength(world.model_catalog[-1], world) == 2


def test_open_source_does_not_break_paid_only_selection(world):
    pick = model_router.resolve_seat("support", allow_open_source_auto=True)
    assert pick.model == "anthropic/support"  # no evidence yet: local is skipped


def test_pinning_still_works_and_flags_unevaluated_models(world):
    pick = model_router.resolve_seat("engineer", {"engineer": LOCAL})
    assert pick.model == LOCAL
    assert "without passing evaluation" in pick.reason
    certify(world)
    assert "without" not in model_router.resolve_seat("engineer", {"engineer": LOCAL}).reason


@pytest.mark.parametrize(
    "mutate, reason",
    [
        ("tamper_task", "signature"),
        ("other_endpoint", "endpoint changed"),
        ("expired", "expired"),
        ("failed_task", "golden tasks failed"),
        ("failed_probe", "tool call checks"),
        ("missing_task", "every golden task"),
        ("missing_probe", "every tool call check"),
        ("unreadable", "unreadable"),
        ("new_golden_tasks", "tests changed"),
    ],
)
def test_bad_evidence_is_rejected(world, mutate, reason, monkeypatch):
    entry = world.model_catalog[-1]
    now = datetime.now(UTC)
    if mutate == "expired":
        certify(world, now=now - timedelta(days=world.model_evaluation_max_age_days + 1))
    elif mutate == "failed_task":
        tasks = passing_tasks()
        tasks[0] = tasks[0].model_copy(update={"diff_matched": False})
        certify(world, tasks=tasks)
    elif mutate == "failed_probe":
        probes = passing_probes()
        probes[0] = probes[0].model_copy(update={"passed": False})
        certify(world, probes=probes)
    elif mutate == "missing_task":
        certify(world, tasks=passing_tasks()[:-1])
    elif mutate == "missing_probe":
        certify(world, probes=passing_probes()[:-1])
    else:
        certify(world)
    path = evidence_path(world, entry.id)
    if mutate == "tamper_task":
        document = EvaluationEvidence.model_validate_json(path.read_text())
        document.tasks[0].error = "edited by hand"
        path.write_text(document.model_dump_json())
    elif mutate == "unreadable":
        path.write_text("{not json")
    elif mutate == "other_endpoint":
        world.model_catalog[-1] = local(base_url="http://other-host:8000/v1")
        entry = world.model_catalog[-1]
    elif mutate == "new_golden_tasks":
        monkeypatch.setattr(evidence_module, "golden_tasks_digest", lambda: "changed")
    status = check_evidence(entry, world)
    assert not status.eligible and reason in status.reason, status
    assert model_router.resolve_seat("engineer", allow_open_source_auto=True).model == (
        "anthropic/engineer"
    )


def test_future_dated_evidence_is_rejected(world):
    certify(world, now=datetime.now(UTC) + timedelta(days=2))
    assert "future" in check_evidence(world.model_catalog[-1], world).reason


def test_evidence_signed_with_another_secret_is_rejected(world):
    certify(world)
    world.engine_service_secret = "a-different-secret-0123456789abcdef"
    assert "signature" in check_evidence(world.model_catalog[-1], world).reason


def test_evidence_cannot_be_built_from_an_offline_run(world):
    world.llm_fake = True
    with pytest.raises(ValueError, match="offline"):
        certify(world, store=False)


def test_missing_evidence_explains_how_to_get_it(world):
    status = check_evidence(world.model_catalog[-1], world)
    assert not status.eligible and "eval_open_model.py" in status.reason


# ----- fallback keeps strength ----------------------------------------------


async def _fallback_calls(world, monkeypatch, primary, failing):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] in failing:
            raise litellm.exceptions.ServiceUnavailableError(
                message="down", model=kwargs["model"], llm_provider="x"
            )
        return "response"

    monkeypatch.setattr(router, "TRANSIENT_DELAYS_S", ())
    monkeypatch.setattr(litellm, "acompletion", completion)
    pick = model_router.resolve_seat("senior", {"senior": primary})
    token = selected_model_var.set(pick)
    try:
        with pytest.raises(litellm.exceptions.ServiceUnavailableError):
            await model_router._agent_completion(primary, messages=[])
    finally:
        selected_model_var.reset(token)
    return [c["model"] for c in calls]


async def test_fallback_never_goes_weaker_smaller_or_open_source(world, monkeypatch):
    big = paid("senior", 4, 5, context_size=200000)
    world.model_catalog[2] = big
    world.model_catalog += [
        paid("weaker", 3, 1),  # weaker
        paid("small-window", 4, 1, context_size=1000),  # smaller context
        paid("pricier", 4, 9),  # above the cost ceiling
        local("strong-local", 4),  # open source
    ]
    certify(world, world.model_catalog[-1])
    tried = await _fallback_calls(world, monkeypatch, "anthropic/senior", {"anthropic/senior"})
    assert tried == ["anthropic/senior"]


async def test_open_source_model_has_no_fallback(world, monkeypatch):
    world.model_catalog.append(paid("senior-2", 3, 0.0001))
    tried = await _fallback_calls(world, monkeypatch, LOCAL, {"openai/qwen-local"})
    assert tried == ["openai/qwen-local"]


async def test_same_strength_paid_backup_is_still_used(world, monkeypatch):
    world.model_catalog.append(paid("backup", 4, 4))
    observed = []

    async def observe(pick):
        observed.append(pick)

    async def completion(**kwargs):
        if kwargs["model"] == "anthropic/senior":
            raise litellm.exceptions.ServiceUnavailableError(
                message="down", model="senior", llm_provider="anthropic"
            )
        return "ok"

    monkeypatch.setattr(router, "TRANSIENT_DELAYS_S", ())
    monkeypatch.setattr(litellm, "acompletion", completion)
    token = selected_model_var.set(
        model_router.resolve_seat("senior", {"senior": "anthropic/senior"})
    )
    watch = selection_observer_var.set(observe)
    try:
        _, used = await model_router._agent_completion("anthropic/senior", messages=[])
    finally:
        selection_observer_var.reset(watch)
        selected_model_var.reset(token)
    assert used == "anthropic/backup" and len(observed) == 1


# ----- routing and cost accounting ------------------------------------------


def _response(content="done", tool_calls=None, usage=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls or [],
                    model_dump=lambda **_: {"role": "assistant", "content": content},
                )
            )
        ],
        usage=usage,
    )


async def test_local_model_is_called_through_openai_adapter_with_catalog_price(world, monkeypatch):
    world.model_catalog[-1] = local(price=2)
    seen = []

    async def completion(**kwargs):
        seen.append(kwargs)
        return _response(usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500))

    def lookalike_price(**_):
        return 99.0  # LiteLLM's table matching a hosted look-alike must be ignored

    monkeypatch.setattr(litellm, "acompletion", completion)
    monkeypatch.setattr(litellm, "completion_cost", lookalike_price)
    token = selected_model_var.set(model_router.resolve_seat("engineer", {"engineer": LOCAL}))
    try:
        turn = await model_router.complete_with_tools("coder", [{"role": "user", "content": "hi"}])
    finally:
        selected_model_var.reset(token)
    assert seen[0]["model"] == "openai/qwen-local"
    assert seen[0]["api_base"] == LOCAL_URL
    assert seen[0]["api_key"] == "not-needed"
    assert turn.cost_usd == pytest.approx(1500 * 2 / 1_000_000)


async def test_missing_usage_from_local_server_is_estimated_not_free(world, monkeypatch):
    world.model_catalog[-1] = local(price=4)

    async def completion(**kwargs):
        return _response(content="x" * 400, usage=None)

    monkeypatch.setattr(litellm, "acompletion", completion)
    token = selected_model_var.set(model_router.resolve_seat("engineer", {"engineer": LOCAL}))
    try:
        turn = await model_router.complete_with_tools(
            "coder", [{"role": "user", "content": "y" * 800}]
        )
    finally:
        selected_model_var.reset(token)
    assert turn.output_tokens == 100 and turn.input_tokens > 200
    assert turn.cost_usd > 0


async def test_paid_models_still_prefer_litellm_pricing(world, monkeypatch):
    async def completion(**kwargs):
        return _response(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10))

    monkeypatch.setattr(litellm, "acompletion", completion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.5)
    token = selected_model_var.set(model_router.resolve_seat("engineer"))
    try:
        turn = await model_router.complete_with_tools("coder", [])
    finally:
        selected_model_var.reset(token)
    assert turn.cost_usd == 0.5


async def test_complete_and_stream_use_the_endpoint_too(world, monkeypatch):
    seen = []

    async def completion(**kwargs):
        seen.append(kwargs)
        if kwargs.get("stream"):

            async def chunks():
                yield SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="a" * 40))],
                )

            return chunks()
        return _response(
            content="hello", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        )

    monkeypatch.setattr(litellm, "acompletion", completion)
    token = selected_model_var.set(model_router.resolve_seat("engineer", {"engineer": LOCAL}))
    try:
        assert await model_router.complete("coder", [{"role": "user", "content": "hi"}]) == "hello"
        text = "".join([c async for c in model_router.stream("coder", [])])
    finally:
        selected_model_var.reset(token)
    assert text == "a" * 40
    assert [c["model"] for c in seen] == ["openai/qwen-local"] * 2
    assert all(c["api_base"] == LOCAL_URL for c in seen)


# ----- tool-call probes ------------------------------------------------------


def _turn(*calls: ToolCall, content="") -> AssistantTurn:
    return AssistantTurn(content, tuple(calls), {"role": "assistant", "content": content})


def _call(name, **arguments):
    return ToolCall(id=f"call-{name}", name=name, arguments=arguments)


class GoodModel:
    """A stub that behaves correctly on every probe."""

    async def __call__(self, messages, tools):
        assert tools == PROBE_TOOLS
        prompt = messages[1]["content"]
        done = any(m["role"] == "tool" for m in messages)
        if "src/app.py" in prompt:
            return _turn(_call("read_file", path="src/app.py"))
        if "pytest" in prompt:
            return _turn(_call("run_command", command="pytest -q", timeout_seconds=90))
        if "a.py" in prompt:
            if done:
                return _turn(content="done")
            return _turn(_call("read_file", path="a.py"), _call("read_file", path="b.py"))
        return _turn(content="2 + 2 is 4.")


async def test_a_capable_stub_passes_every_probe():
    results = await run_probes(GoodModel())
    assert [r.name for r in results] == [p.name for p in PROBES]
    assert all(r.passed for r in results), results


async def test_sequential_tool_calls_across_turns_pass_the_several_calls_probe():
    paths = iter(["a.py", "b.py"])

    async def one_per_turn(messages, tools):
        path = next(paths, None)
        return _turn(_call("read_file", path=path)) if path else _turn(content="done")

    probe = next(p for p in PROBES if p.name == "several_calls")
    assert (await run_probe(probe, one_per_turn)).passed


@pytest.mark.parametrize(
    "probe_name, bad_turn",
    [
        ("single_call", _turn(content="I would read it")),
        ("single_call", _turn(_call("read_file", path="other.py"))),
        ("typed_arguments", _turn(_call("run_command", command="pytest -q", timeout_seconds="90"))),
        ("typed_arguments", _turn(_call("run_command", command="pytest -q", timeout_seconds=True))),
        ("several_calls", _turn(_call("read_file", path="a.py"))),
        ("no_tool_when_unneeded", _turn(_call("run_command", command="echo", timeout_seconds=1))),
    ],
)
async def test_weak_tool_behaviour_fails_the_probe(probe_name, bad_turn):
    async def weak(messages, tools):
        return bad_turn if not any(m["role"] == "tool" for m in messages) else _turn(content="x")

    probe = next(p for p in PROBES if p.name == probe_name)
    assert not (await run_probe(probe, weak)).passed


async def test_provider_error_fails_the_probe_without_crashing():
    async def broken(messages, tools):
        raise ConnectionError("endpoint refused")

    result = (await run_probes(broken))[0]
    assert not result.passed and "ConnectionError" in result.detail


# ----- evaluation workflow ---------------------------------------------------


@dataclass
class Score:
    name: str
    planned: bool = True
    completed: bool = True
    committed: bool = True
    diff_matched: bool | None = True
    cost_usd: float = 0.0
    error: str | None = None


async def test_evaluation_pins_candidate_then_restores_settings(world):
    entry = world.model_catalog[-1]
    before = world.model_catalog, world.model_level_pins
    seen = {}

    async def fake_team(work_dir):
        seen["catalog"] = [m.id for m in world.model_catalog]
        seen["pins"] = dict(world.model_level_pins)
        return [Score(t["name"]) for t in GOLDEN_TASKS]

    evidence, passed = await evaluate_model(
        entry, world, complete=GoodModel(), evaluate_team=fake_team
    )
    assert passed
    assert seen["catalog"] == [entry.id]
    assert set(seen["pins"]) == set(SeatLevel) and set(seen["pins"].values()) == {entry.id}
    assert (world.model_catalog, world.model_level_pins) == before
    save_evidence(evidence, world)
    assert check_evidence(entry, world).eligible
    assert model_router.resolve_seat("engineer", allow_open_source_auto=True).model == entry.id


async def test_failed_golden_task_or_probe_does_not_pass(world):
    entry = world.model_catalog[-1]

    async def team_with_failure(work_dir):
        scores = [Score(t["name"]) for t in GOLDEN_TASKS]
        scores[1].diff_matched = False
        return scores

    evidence, passed = await evaluate_model(
        entry, world, complete=GoodModel(), evaluate_team=team_with_failure
    )
    assert not passed
    save_evidence(evidence, world)  # even if stored, it never verifies
    assert not check_evidence(entry, world).eligible

    async def passing_team(work_dir):
        return [Score(t["name"]) for t in GOLDEN_TASKS]

    async def refuses_tools(messages, tools):
        return _turn(content="I cannot use tools")

    _, passed = await evaluate_model(
        entry, world, complete=refuses_tools, evaluate_team=passing_team
    )
    assert not passed


async def test_offline_diff_unjudged_does_not_certify(world):
    entry = world.model_catalog[-1]

    async def unjudged(work_dir):
        return [Score(t["name"], diff_matched=None) for t in GOLDEN_TASKS]

    _, passed = await evaluate_model(entry, world, complete=GoodModel(), evaluate_team=unjudged)
    assert not passed


async def test_evaluation_refuses_fake_mode_and_missing_key(world):
    entry = world.model_catalog[-1]
    world.llm_fake = True
    with pytest.raises(ModelSelectionError, match="offline"):
        await evaluate_model(entry, world, complete=GoodModel(), evaluate_team=None)
    world.llm_fake = False
    keyed = local("keyed", requires_api_key=True)
    with pytest.raises(ModelSelectionError, match="no API key"):
        await evaluate_model(keyed, world, complete=GoodModel(), evaluate_team=None)


def test_pinned_for_evaluation_restores_on_error(world):
    entry = world.model_catalog[-1]
    before = list(world.model_catalog)
    with pytest.raises(RuntimeError), pinned_for_evaluation(world, entry):
        raise RuntimeError("boom")
    assert world.model_catalog == before and world.model_level_pins == {}
