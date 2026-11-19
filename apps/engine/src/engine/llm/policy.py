"""An organization's model policy as the runner needs it.

The runner (or team assembler) loads this once per run and passes
`org_overrides=policy.level_pins` and
`allow_open_source_auto=policy.allow_open_source_auto` to `ModelRouter.resolve_seat`.
Without a stored row an organization has no pins and open source stays out of auto.
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import OrganizationModelPolicy
from engine.llm.catalog import SeatLevel


@dataclass(frozen=True)
class OrgModelPolicy:
    level_pins: dict[str, str] = field(default_factory=dict)
    allow_open_source_auto: bool = False


async def load_org_model_policy(db: AsyncSession, org_id: str | None) -> OrgModelPolicy:
    """The stored policy, or the safe default when none exists or there is no org."""
    if not org_id:
        return OrgModelPolicy()
    row = await db.get(OrganizationModelPolicy, org_id)
    if row is None:
        return OrgModelPolicy()
    levels = {level.value for level in SeatLevel}
    pins = {level: model for level, model in (row.level_pins or {}).items() if level in levels}
    return OrgModelPolicy(pins, bool(row.allow_open_source_auto))
