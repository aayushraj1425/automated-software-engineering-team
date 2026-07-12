"""Integrations API: link external services, owner-scoped and encrypted at rest.

Mirrors the provider-keys API. The list never returns a secret config — only
which services are connected, their non-secret label, and whether they are
enabled. Setting a connection replaces any previous one for that kind; the test
endpoint sends a message now so the settings page can prove a webhook works.
Design note: docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import IntegrationConnection
from engine.db.session import get_session
from engine.integrations import slack
from engine.integrations.connections import (
    ACTIVE_KINDS,
    ConfigError,
    build_config,
    encrypt_config,
    load_config,
)

router = APIRouter()


class ConnectionIn(BaseModel):
    # A small per-kind config: for Slack, {"webhook_url": "..."}.
    config: dict[str, str]


class ConnectionOut(BaseModel):
    kind: str
    label: str
    enabled: bool
    updated_at: datetime


class TestResult(BaseModel):
    ok: bool
    dry_run: bool
    detail: str


def _connection_out(row: IntegrationConnection) -> ConnectionOut:
    return ConnectionOut(
        kind=row.kind, label=row.label, enabled=row.enabled, updated_at=row.updated_at
    )


def _active_kind(kind: str) -> str:
    if kind not in ACTIVE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported integration; available: {', '.join(ACTIVE_KINDS)}",
        )
    return kind


@router.get("/v1/integrations")
async def list_integrations(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[ConnectionOut]:
    rows = (
        (
            await db.execute(
                select(IntegrationConnection)
                .where(IntegrationConnection.user_id == principal.user_id)
                .order_by(IntegrationConnection.kind)
            )
        )
        .scalars()
        .all()
    )
    return [_connection_out(row) for row in rows]


@router.put("/v1/integrations/{kind}")
async def set_integration(
    kind: str,
    body: ConnectionIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> ConnectionOut:
    kind = _active_kind(kind)
    try:
        json_config, label = build_config(kind, body.config)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.user_id == principal.user_id,
                IntegrationConnection.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationConnection(user_id=principal.user_id, kind=kind, encrypted_config="")
        db.add(row)
    row.encrypted_config = encrypt_config(json_config)
    row.label = label
    row.enabled = True
    await db.commit()
    await db.refresh(row)
    return _connection_out(row)


@router.delete("/v1/integrations/{kind}", status_code=204)
async def delete_integration(
    kind: str,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    row = (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.user_id == principal.user_id,
                IntegrationConnection.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No connection for that integration")
    await db.delete(row)
    await db.commit()


@router.post("/v1/integrations/{kind}/test")
async def test_integration(
    kind: str,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> TestResult:
    """Send a test message now, so the settings page can prove it works."""
    kind = _active_kind(kind)
    config = await load_config(db, principal.user_id, kind)
    if config is None:
        raise HTTPException(status_code=404, detail="No connection for that integration")
    try:
        sent = await slack.post_message(
            config["webhook_url"], "🔔 ASEP test message — your integration is connected."
        )
    except slack.SlackError as exc:
        return TestResult(ok=False, dry_run=False, detail=str(exc))
    return TestResult(
        ok=True,
        dry_run=not sent,
        detail="Sent to Slack." if sent else "Dry run — no message sent.",
    )
