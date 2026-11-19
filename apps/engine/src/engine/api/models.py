"""Public model metadata, authenticated like the rest of the engine API."""

from fastapi import APIRouter, Depends

from engine.auth import require_service_auth
from engine.config import get_settings
from engine.llm.catalog import ModelEntry
from engine.llm.evidence import check_evidence

router = APIRouter()


@router.get(
    "/v1/models", response_model=list[ModelEntry], dependencies=[Depends(require_service_auth)]
)
async def list_models() -> list[ModelEntry]:
    # No keys, caller availability, or endpoint URLs are exposed here (base_url is
    # excluded from serialization). Empty means the server still uses legacy
    # MODEL_* settings. For open source entries `evaluated` reports verified
    # evidence, not the operator's configured flag.
    settings = get_settings()
    return [
        entry.model_copy(update={"evaluated": check_evidence(entry, settings).eligible})
        if entry.needs_evaluation
        else entry
        for entry in settings.model_catalog
    ]
