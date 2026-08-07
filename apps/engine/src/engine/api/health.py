import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from engine.db.session import get_engine

router = APIRouter()

log = structlog.get_logger(__name__)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving. Deliberately checks nothing
    external, so a transient database blip never trips a pod restart — that is
    what readiness is for."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    """Readiness: the process can serve real traffic, which means the database
    is reachable. Returns 503 when it is not, so an orchestrator or load
    balancer holds traffic back until the dependency recovers instead of
    routing requests that would only 500."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        log.warning("readiness_check_failed", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ready", "database": "ok"}
