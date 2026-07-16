"""Who can see a shared resource — the one place the rule is written.

A repository or agent run is visible when the caller owns it, or when its
``org_id`` matches the caller's *active* organization (the membership-checked
``org`` claim in the service JWT). Route filters use these helpers for
friendly 404s and correct lists; the row-level-security policies (db/rls.py)
state the same rule inside Postgres. Conversations, provider keys, and
integrations stay owner-only and never come through here.
Design note: docs/architecture/ORGANIZATION_SHARING.md.
"""

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from engine.auth import Principal


def can_access(principal: Principal, owner_id: str, org_id: str | None) -> bool:
    """Point-lookup check: the caller owns the row or shares its organization."""
    if owner_id == principal.user_id:
        return True
    return org_id is not None and org_id == principal.org_id


def visible_clause(
    owner_column: InstrumentedAttribute[str],
    org_column: InstrumentedAttribute[str | None],
    principal: Principal,
) -> ColumnElement[bool]:
    """The same rule as a SQLAlchemy filter, for list and dedupe queries."""
    owned = owner_column == principal.user_id
    if principal.org_id is None:
        return owned
    return or_(owned, and_(org_column.is_not(None), org_column == principal.org_id))
