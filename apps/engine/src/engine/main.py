import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine.agents.recovery import recover_interrupted_runs
from engine.api import (
    chat,
    conversations,
    documents,
    health,
    integrations,
    knowledge,
    provider_keys,
    repositories,
    runs,
    webhooks,
    work_items,
)
from engine.config import get_settings
from engine.db.session import dispose_engine
from engine.events.bus import dispose_bus
from engine.jobs import dispose_jobs
from engine.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(get_settings().log_level)
    # Resume runs the last process left behind (docs/architecture/RUN_RECOVERY.md).
    # Runs in the background so startup never blocks on an interrupted run; a
    # shutdown mid-recovery just leaves the runs for the next startup. Inline
    # mode only: in queue mode the worker owns runs, and the API must not
    # resume one a healthy worker may still be executing (BACKGROUND_WORKER.md).
    recovery: asyncio.Task | None = None
    if get_settings().run_recovery_enabled and get_settings().run_queue == "inline":
        recovery = asyncio.create_task(recover_interrupted_runs())
    yield
    if recovery is not None and not recovery.done():
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery
    await dispose_jobs()
    await dispose_bus()
    await dispose_engine()


app = FastAPI(
    title="ASEP Engine",
    version="0.1.0",
    description="AI engine for the ASEP platform: chat, agents, repository intelligence.",
    lifespan=lifespan,
)

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
app.include_router(repositories.router)
app.include_router(webhooks.router)
app.include_router(work_items.router)
app.include_router(knowledge.router)
app.include_router(documents.router)
app.include_router(provider_keys.router)
app.include_router(integrations.router)
