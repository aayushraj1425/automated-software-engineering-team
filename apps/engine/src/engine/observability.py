"""OpenTelemetry wiring: request spans, metrics, and the SDK switch (Phase 7).

The code instruments unconditionally through the OTel *API* — spans and metric
instruments here and in the ModelRouter/runner are no-ops until something
configures the SDK, so instrumented code carries no `if telemetry:` branches.
`configure_telemetry()` is that switch: called at startup when OTEL_ENABLED=1
(exporting via OTLP to OTEL_EXPORTER_OTLP_ENDPOINT), or by tests with in-memory
exporters so assertions read real spans offline. ADR-0010; design note:
docs/architecture/PRODUCTION_HARDENING.md.
"""

import time
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

from engine.config import get_settings

log = structlog.get_logger(__name__)

# The API's global providers are proxies that upgrade when the SDK is set, so
# instruments created at import start recording after configure_telemetry().
tracer = trace.get_tracer("engine")
_meter = metrics.get_meter("engine")
request_counter = _meter.create_counter(
    "http.server.requests", description="Requests handled, by route and status code"
)
request_duration = _meter.create_histogram(
    "http.server.duration", unit="ms", description="Request duration, by route and status code"
)

_configured = False


def configure_telemetry(
    span_exporter: SpanExporter | None = None, metric_reader: MetricReader | None = None
) -> None:
    """Install the OTel SDK. Idempotent — the first configuration wins.

    With no arguments, exporters come from settings (OTLP over HTTP when
    OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise spans stay in-process only).
    Tests pass in-memory exporters/readers to read telemetry back.
    """
    global _configured
    if _configured:
        return
    _configured = True

    settings = get_settings()
    resource = Resource.create({"service.name": settings.otel_service_name})

    tracer_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        # Simple (synchronous) processing so tests see spans immediately.
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
    trace.set_tracer_provider(tracer_provider)

    readers: list[MetricReader] = []
    if metric_reader is not None:
        readers.append(metric_reader)
    elif settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=settings.otel_exporter_otlp_endpoint)
            )
        )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    log.info(
        "telemetry.configured",
        service=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint or None,
    )


class TracingMiddleware:
    """One server span + one counter/histogram sample per request.

    Pure ASGI (not BaseHTTPMiddleware) so SSE streaming responses pass through
    untouched. /healthz is excluded — liveness probes would drown the traces.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        started = time.monotonic()
        status_holder = {"status": 500}  # a crash before response.start is a 500

        async def send_with_status(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        with tracer.start_as_current_span(
            f"{method} {scope['path']}", kind=SpanKind.SERVER
        ) as span:
            try:
                await self.app(scope, receive, send_with_status)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                # The router resolved the route during handling; prefer its
                # template ("/v1/runs/{run_id}") over the raw path.
                route = getattr(scope.get("route"), "path", scope["path"])
                status = status_holder["status"]
                span.update_name(f"{method} {route}")
                span.set_attribute("http.request.method", method)
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                labels = {"http.route": route, "http.response.status_code": status}
                request_counter.add(1, labels)
                request_duration.record((time.monotonic() - started) * 1000, labels)
