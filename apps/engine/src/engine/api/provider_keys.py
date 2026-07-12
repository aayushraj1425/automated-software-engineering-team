"""Provider-keys API: bring-your-own LLM keys, encrypted at rest.

The list never returns a key — not even encrypted — only which providers are
configured and their last four characters for the settings page. Setting a
key replaces any previous one for that provider. Design note:
docs/architecture/PROVIDER_KEYS.md.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import ProviderKey
from engine.db.session import get_session
from engine.llm.keys import ALLOWED_PROVIDERS
from engine.security.crypto import encrypt

router = APIRouter()


class ProviderKeyIn(BaseModel):
    key: str = Field(min_length=8, max_length=512)


class ProviderKeyOut(BaseModel):
    provider: str
    last4: str
    updated_at: datetime


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
    rows = (
        (
            await db.execute(
                select(ProviderKey)
                .where(ProviderKey.user_id == principal.user_id)
                .order_by(ProviderKey.provider)
            )
        )
        .scalars()
        .all()
    )
    return [
        ProviderKeyOut(provider=r.provider, last4=r.last4, updated_at=r.updated_at) for r in rows
    ]


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
    row = (
        await db.execute(
            select(ProviderKey).where(
                ProviderKey.user_id == principal.user_id, ProviderKey.provider == provider
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ProviderKey(user_id=principal.user_id, provider=provider, encrypted_key="", last4="")
        db.add(row)
    row.encrypted_key = encrypt(key)
    row.last4 = key[-4:]
    await db.commit()
    await db.refresh(row)
    return ProviderKeyOut(provider=row.provider, last4=row.last4, updated_at=row.updated_at)


@router.delete("/v1/provider-keys/{provider}", status_code=204)
async def delete_provider_key(
    provider: str,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    provider = _validated_provider(provider)
    row = (
        await db.execute(
            select(ProviderKey).where(
                ProviderKey.user_id == principal.user_id, ProviderKey.provider == provider
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No key stored for that provider")
    await db.delete(row)
    await db.commit()
