"""OpenTelemetry wiring: request spans, LLM spans, run spans, and metrics.

The module configures the SDK once with in-memory exporters through the same
`configure_telemetry()` seam production uses, so these assertions read real
spans offline — the Phase 7 observability exit criterion. Design note:
docs/architecture/PRODUCTION_HARDENING.md (ADR-0010).
"""

import uuid

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from engine.llm.router import model_router
from engine.observability import configure_telemetry, record_llm_call
from tests.conftest import auth_headers

# The first configuration wins process-wide, so it happens at import — every
# span created by any test after this module loads flows to this exporter.
span_exporter = InMemorySpanExporter()
metric_reader = InMemoryMetricReader()
configure_telemetry(span_exporter=span_exporter, metric_reader=metric_reader)


@pytest.fixture(autouse=True)
def clean_spans():
    span_exporter.clear()
    yield


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


def _spans_named(name: str) -> list:
    return [s for s in span_exporter.get_finished_spans() if s.name == name]


async def test_a_chat_request_produces_request_and_llm_spans(client):
    resp = await client.post("/v1/chat", json={"message": "hello"}, headers=_headers())
    assert resp.status_code == 200

    (request_span,) = _spans_named("POST /v1/chat")
    assert request_span.attributes["http.route"] == "/v1/chat"
    assert request_span.attributes["http.response.status_code"] == 200

    (llm_span,) = _spans_named("llm.stream")
    assert llm_span.attributes["llm.model"] == "fake"
    assert llm_span.attributes["llm.tier"]


async def test_route_template_replaces_the_raw_path(client):
    missing = uuid.uuid4()
    resp = await client.get(f"/v1/runs/{missing}", headers=_headers())
    assert resp.status_code == 404

    (span,) = _spans_named("GET /v1/runs/{run_id}")
    assert span.attributes["http.route"] == "/v1/runs/{run_id}"
    assert span.attributes["http.response.status_code"] == 404


async def test_healthz_is_not_traced(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert not span_exporter.get_finished_spans()


async def test_llm_complete_span_carries_tier_and_model():
    await model_router.complete("cheap", [{"role": "user", "content": "hi"}])
    (span,) = _spans_named("llm.complete")
    assert span.attributes["llm.tier"] == "cheap"
    assert span.attributes["llm.model"] == "fake"


async def test_run_planning_is_traced(client, tmp_path, monkeypatch):
    from engine.config import get_settings

    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))
    resp = await client.post(
        "/v1/runs",
        json={
            "request": "Add a /status endpoint",
            "repository_url": "https://github.com/acme/demo",
        },
        headers=_headers(),
    )
    assert resp.status_code == 201, resp.text

    (span,) = _spans_named("run.plan")
    assert span.attributes["asep.run_id"] == resp.json()["id"]


async def test_request_metrics_count_by_route(client):
    resp = await client.get("/v1/repositories", headers=_headers())
    assert resp.status_code == 200

    metrics_data = metric_reader.get_metrics_data()
    assert metrics_data is not None
    points = [
        point
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == "http.server.requests"
        for point in metric.data.data_points
        if (point.attributes or {}).get("http.route") == "/v1/repositories"
    ]
    assert points, "no request-counter data point for the route"
    # A counter's points are NumberDataPoints; getattr keeps pyright happy
    # about the histogram members of the data-point union.
    assert getattr(points[0], "value", 0) >= 1


def _counter_points(name: str) -> list:
    data = metric_reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_llm_cost_and_token_metrics_record_spend():
    """record_llm_call feeds the token-spend alert's series (ALERTING.md)."""
    record_llm_call(
        "planner", "anthropic/claude-opus-4-8", cost_usd=0.5, input_tokens=100, output_tokens=40
    )

    cost = [p for p in _counter_points("llm.cost.usd") if p.attributes.get("llm.tier") == "planner"]
    assert cost and getattr(cost[0], "value", 0) >= 0.5

    tokens = _counter_points("llm.tokens")
    directions = {p.attributes.get("llm.token_type") for p in tokens}
    assert {"input", "output"} <= directions
