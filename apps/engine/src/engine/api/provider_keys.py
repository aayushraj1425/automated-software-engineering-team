"""Provider-keys API: bring-your-own LLM keys, encrypted at rest.

The list never returns a key — not even encrypted — only which providers are
configured and their last four characters for the settings page. Setting a
key replaces any previous one for that provider. A key can be explicitly
shared with the active organization — one org key per provider, visible to
and replaceable by any member. Design note:
docs/architecture/PROVIDER_KEYS.md.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import ProviderKey
from engine.db.session import get_session
from engine.llm.keys import ALLOWED_PROVIDERS
from engine.security.crypto import encrypt

router = APIRouter()


class ProviderKeyIn(BaseModel):
    key: str = Field(min_length=8, max_length=512)
    # A secret is never shared by default — this is an explicit choice.
    share_with_organization: bool = False


class ProviderKeyOut(BaseModel):
    provider: str
    last4: str
    updated_at: datetime
    shared: bool = False  # shared with the active organization


def _key_out(row: ProviderKey) -> ProviderKeyOut:
    return ProviderKeyOut(
        provider=row.provider,
        last4=row.last4,
        updated_at=row.updated_at,
        shared=row.org_id is not None,
    )


def _validated_provider(provider: str) -> str:
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider; allowed: {', '.join(ALLOWED_PROVIDERS)}",
        )
    return provider


@router.get("/v1/provider-keys")
async def list_provider_keys(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[ProviderKeyOut]:
    personal = and_(ProviderKey.user_id == principal.user_id, ProviderKey.org_id.is_(None))
    visible = (
        or_(personal, ProviderKey.org_id == principal.org_id) if principal.org_id else personal
    )
    rows = (
        (await db.execute(select(ProviderKey).where(visible).order_by(ProviderKey.provider)))
        .scalars()
        .all()
    )
    return [_key_out(r) for r in rows]


@router.put("/v1/provider-keys/{provider}")
async def set_provider_key(
    provider: str,
    body: ProviderKeyIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> ProviderKeyOut:
    provider = _validated_provider(provider)
    key = body.key.strip()
    if len(key) < 8:
        raise HTTPException(status_code=422, detail="That does not look like a provider key")
    if body.share_with_organization and not principal.org_id:
        raise HTTPException(
            status_code=400,
            detail="Sharing a key needs an active organization — pick one in settings first",
        )
    # A shared key replaces the org's key (any member may — equal
    # collaborators); a personal key replaces the caller's own.
    if body.share_with_organization:
        scope = ProviderKey.org_id == principal.org_id
    else:
        scope = and_(ProviderKey.user_id == principal.user_id, ProviderKey.org_id.is_(None))
    row = (
        await db.execute(select(ProviderKey).where(scope, ProviderKey.provider == provider))
    ).scalar_one_or_none()
    if row is None:
        row = ProviderKey(
            user_id=principal.user_id,
            org_id=principal.org_id if body.share_with_organization else None,
            provider=provider,
            encrypted_key="",
            last4="",
        )
        db.add(row)
    row.user_id = principal.user_id  # the latest contributor
    row.encrypted_key = encrypt(key)
    row.last4 = key[-4:]
    await db.commit()
    await db.refresh(row)
    return _key_out(row)


@router.delete("/v1/provider-keys/{provider}", status_code=204)
async def delete_provider_key(
    provider: str,
    shared: bool = Query(default=False, description="Remove the organization's shared key"),
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    provider = _validated_provider(provider)
    if shared:
        if not principal.org_id:
            raise HTTPException(status_code=400, detail="No active organization")
        scope = ProviderKey.org_id == principal.org_id
    else:
        scope = and_(ProviderKey.user_id == principal.user_id, ProviderKey.org_id.is_(None))
    row = (
        await db.execute(select(ProviderKey).where(scope, ProviderKey.provider == provider))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No key stored for that provider")
    await db.delete(row)
    await db.commit()
