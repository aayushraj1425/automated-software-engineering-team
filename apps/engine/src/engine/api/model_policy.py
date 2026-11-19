"""Organization model policy: level pins and the open source auto switch.

Scoped to the active organization from the service token. Any member may read the
policy; only an owner or admin may change it. The switch alone never puts an open
source model into auto selection: the model also needs signed evaluation results
(docs/architecture/agents/OPEN_SOURCE_MODELS.md).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.config import get_settings
from engine.db.models import OrganizationModelPolicy
from engine.db.session import get_session
from engine.llm.catalog import SeatLevel
from engine.llm.evidence import check_evidence

router = APIRouter()


class ModelPolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # seat level (support, engineer, senior, principal) to a MODEL_CATALOG id
    level_pins: dict[str, str] = {}
    allow_open_source_auto: bool = False


class OpenSourceModelStatus(BaseModel):
    model_id: str
    eligible_for_auto: bool
    certified_strength: int
    reason: str


class ModelPolicyOut(BaseModel):
    level_pins: dict[str, str]
    allow_open_source_auto: bool
    open_source_models: list[OpenSourceModelStatus]
    updated_at: datetime | None = None


def _active_org(principal: Principal) -> str:
    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Model policy needs an active organization")
    return principal.org_id


def _open_source_status() -> list[OpenSourceModelStatus]:
    settings = get_settings()
    statuses = []
    for entry in settings.model_catalog:
        if entry.needs_evaluation:
            status = check_evidence(entry, settings)
            statuses.append(
                OpenSourceModelStatus(
                    model_id=entry.id,
                    eligible_for_auto=status.eligible,
                    certified_strength=min(entry.strength, status.certified_strength),
                    reason=status.reason,
                )
            )
    return statuses


def _validated_pins(pins: dict[str, str]) -> dict[str, str]:
    levels = {level.value for level in SeatLevel}
    catalog = {entry.id: entry for entry in get_settings().model_catalog}
    if pins and not catalog:
        raise HTTPException(status_code=422, detail="Pins need MODEL_CATALOG to be configured")
    for level, model in pins.items():
        if level not in levels:
            raise HTTPException(
                status_code=422, detail=f"Unknown seat level {level!r}; use {sorted(levels)}"
            )
        entry = catalog.get(model)
        if entry is None:
            raise HTTPException(
                status_code=422, detail=f"Pinned model {model!r} is not in the catalog"
            )
        if not entry.supports_tools:
            raise HTTPException(status_code=422, detail=f"Pinned model {model!r} cannot use tools")
    return dict(pins)


def _out(row: OrganizationModelPolicy | None) -> ModelPolicyOut:
    return ModelPolicyOut(
        level_pins=dict(row.level_pins or {}) if row else {},
        allow_open_source_auto=bool(row.allow_open_source_auto) if row else False,
        open_source_models=_open_source_status(),
        updated_at=row.updated_at if row else None,
    )


@router.get("/v1/model-policy", response_model=ModelPolicyOut)
async def get_model_policy(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> ModelPolicyOut:
    return _out(await db.get(OrganizationModelPolicy, _active_org(principal)))


@router.put("/v1/model-policy", response_model=ModelPolicyOut)
async def put_model_policy(
    body: ModelPolicyIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> ModelPolicyOut:
    org_id = _active_org(principal)
    if not principal.is_org_admin:
        raise HTTPException(
            status_code=403, detail="Changing the model policy takes an organization admin"
        )
    pins = _validated_pins(body.level_pins)
    values = {"level_pins": pins, "allow_open_source_auto": body.allow_open_source_auto}
    await db.execute(
        insert(OrganizationModelPolicy)
        .values(org_id=org_id, **values)
        .on_conflict_do_update(
            index_elements=[OrganizationModelPolicy.org_id],
            set_={**values, "updated_at": func.now()},
        )
    )
    await db.commit()
    db.expire_all()
    return _out(await db.get(OrganizationModelPolicy, org_id))
