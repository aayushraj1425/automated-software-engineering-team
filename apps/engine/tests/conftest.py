import asyncio
import os
import sys
import time

# Must be set before any engine import â€” Settings is lru_cached and real env
# vars take priority over .env files.
os.environ["LLM_FAKE"] = "1"
os.environ["ENGINE_SERVICE_SECRET"] = "test-service-secret-0123456789abcdef"
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://asep:asep@localhost:5433/asep_test")
# Tests must never reach the real Docker daemon; sandbox tests opt back in
# with a monkeypatched settings object and a fake docker call.
os.environ["SANDBOX_ENABLED"] = "0"
# Integration adapters must never reach a real Slack workspace; dry-run makes
# them report success without the network (EXTERNAL_INTEGRATIONS.md).
os.environ["INTEGRATIONS_DRY_RUN"] = "1"
# Startup recovery would resume runs other tests deliberately left mid-state;
# the recovery tests call recover_interrupted_runs() directly instead.
os.environ["RUN_RECOVERY_ENABLED"] = "0"

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import jwt  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from engine.config import get_settings  # noqa: E402
from engine.db.models import Base  # noqa: E402
from engine.db.rls import apply_row_level_security  # noqa: E402


def make_service_token(
    user_id: str = "user_test",
    secret: str = "test-service-secret-0123456789abcdef",
    org_id: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, object] = {"sub": user_id, "iat": now, "exp": now + 60}
    if org_id is not None:
        payload["org"] = org_id
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_headers(user_id: str = "user_test", org_id: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_service_token(user_id, org_id=org_id)}"}


def _ensure_test_database() -> None:
    url = get_settings().database_url
    dsn = url.replace("postgresql+psycopg", "postgresql")
    base, _, dbname = dsn.rpartition("/")
    with psycopg.connect(f"{base}/postgres", autocommit=True) as conn:
        row = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if row is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


@pytest.fixture(scope="session")
async def prepared_db():
    _ensure_test_database()
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # The whole suite runs under FORCE ROW LEVEL SECURITY, so every
        # owner-scoped test exercises the policies (ROW_LEVEL_SECURITY.md).
        await apply_row_level_security(conn)
    await engine.dispose()
    yield


@pytest.fixture
async def client(prepared_db):
    from engine.main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
