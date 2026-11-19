"""Organization preview credentials: encrypted writes, metadata-only reads."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import AgentRun, PreviewCredential
from engine.db.session import get_session
from engine.security.crypto import encrypt
from engine.security.preview_credentials import validate_kubeconfig

router = APIRouter()


class PreviewCredentialIn(BaseModel):
    kubeconfig: str = Field(min_length=1, max_length=262144)


class PreviewCredentialOut(BaseModel):
    configured: bool
    updated_at: datetime | None = None


def _org(principal: Principal, *, write: bool = False) -> str:
    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Choose an active organization first")
    if write and not principal.is_org_admin:
        raise HTTPException(
            status_code=403, detail="Only organization admins may change preview credentials"
        )
    return principal.org_id


@router.get("/v1/preview-credentials")
async def get_preview_credential(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> PreviewCredentialOut:
    row = await db.get(PreviewCredential, _org(principal))
    return PreviewCredentialOut(
        configured=row is not None, updated_at=row.updated_at if row else None
    )


@router.put("/v1/preview-credentials")
async def put_preview_credential(
    body: PreviewCredentialIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> PreviewCredentialOut:
    org_id = _org(principal, write=True)
    try:
        validate_kubeconfig(body.kubeconfig)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    encrypted = encrypt(json.dumps({"kubeconfig": body.kubeconfig}))
    await db.execute(
        insert(PreviewCredential)
        .values(org_id=org_id, created_by=principal.user_id, encrypted_credentials=encrypted)
        .on_conflict_do_update(
            index_elements=[PreviewCredential.org_id],
            set_={
                "created_by": principal.user_id,
                "encrypted_credentials": encrypted,
                "updated_at": func.now(),
            },
        )
    )
    await db.commit()
    row = await db.get(PreviewCredential, org_id)
    assert row is not None
    await db.refresh(row)
    return PreviewCredentialOut(configured=True, updated_at=row.updated_at)


@router.delete("/v1/preview-credentials", status_code=204)
async def delete_preview_credential(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> Response:
    org_id = _org(principal, write=True)
    active = (
        await db.execute(
            select(AgentRun.id)
            .where(
                AgentRun.org_id == org_id,
                AgentRun.deployment_status.in_(
                    [
                        "approved",
                        "deploying",
                        "deployed",
                        "verified",
                        "cleanup_pending",
                        "cleanup_failed",
                    ]
                ),
            )
            .limit(1)
        )
    ).first()
    if active:
        raise HTTPException(
            status_code=409, detail="Clean up active previews before removing credentials"
        )
    row = await db.get(PreviewCredential, org_id)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return Response(status_code=204)
