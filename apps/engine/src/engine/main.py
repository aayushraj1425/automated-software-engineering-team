import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engine.agents.preview_cleanup import cleanup_expired_previews
from engine.agents.recovery import recover_interrupted_runs
from engine.api import (
    chat,
    conversations,
    documents,
    health,
    integrations,
    knowledge,
    model_policy,
    models,
    preview_credentials,
    provider_keys,
    repositories,
    runs,
    terminal,
    webhooks,
    work_items,
)
from engine.config import get_settings
from engine.db.session import dispose_engine
from engine.events.bus import dispose_bus
from engine.jobs import dispose_jobs
from engine.logging import setup_logging
from engine.observability import TracingMiddleware, configure_telemetry
from engine.ratelimit import RateLimitMiddleware, dispose_ratelimit
from engine.security.crypto import warn_if_derived_key


async def _maintain_previews() -> None:
    while True:
        # Failed teardown retains durable state for the next scheduled retry.
        with suppress(Exception):
            await cleanup_expired_previews()
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(get_settings().log_level)
    warn_if_derived_key()  # secrets-at-rest key fallback (security audit)
    # Spans/metrics are no-ops until this installs the SDK (ADR-0010,
    # docs/architecture/operations/PRODUCTION_HARDENING.md).
    if get_settings().otel_enabled:
        configure_telemetry()
    # Resume runs the last process left behind (docs/architecture/agents/RUN_RECOVERY.md).
    # Runs in the background so startup never blocks on an interrupted run; a
    # shutdown mid-recovery just leaves the runs for the next startup. Inline
    # mode only: in queue mode the worker owns runs, and the API must not
    # resume one a healthy worker may still be executing (BACKGROUND_WORKER.md).
    recovery: asyncio.Task | None = None
    preview_maintenance: asyncio.Task | None = None
    if get_settings().run_recovery_enabled and get_settings().run_queue == "inline":
        recovery = asyncio.create_task(recover_interrupted_runs())
    if not get_settings().llm_fake:
        preview_maintenance = asyncio.create_task(_maintain_previews())
    yield
    if preview_maintenance is not None:
        preview_maintenance.cancel()
        with suppress(asyncio.CancelledError):
            await preview_maintenance
    if recovery is not None and not recovery.done():
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery
    await dispose_jobs()
    await dispose_bus()
    await dispose_ratelimit()
    await dispose_engine()


app = FastAPI(
    title="ASEP Engine",
    version="0.1.0",
    description="AI engine for the ASEP platform: chat, agents, repository intelligence.",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == "/v1/preview-credentials":
        # FastAPI's default includes the invalid input; never echo a kubeconfig.
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid preview credential payload; expected a bounded kubeconfig string"
            },
        )
    return await request_validation_exception_handler(request, exc)


# Added first, so it sits innermost — inside the tracing span, making 429s
# visible in the request metrics. Off until RATE_LIMIT_PER_MINUTE is set
# (docs/architecture/operations/RATE_LIMITING.md).
app.add_middleware(RateLimitMiddleware)

# Added before CORS, so CORS wraps it: real API work gets a span, CORS
# preflights don't. Pure ASGI, SSE-safe.
app.add_middleware(TracingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().engine_cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(runs.router)
app.include_router(terminal.router)
app.include_router(repositories.router)
app.include_router(webhooks.router)
app.include_router(work_items.router)
app.include_router(knowledge.router)
app.include_router(documents.router)
app.include_router(provider_keys.router)
app.include_router(preview_credentials.router)
app.include_router(models.router)
app.include_router(model_policy.router)
app.include_router(integrations.router)
