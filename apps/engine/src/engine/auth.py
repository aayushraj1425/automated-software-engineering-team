from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

from engine.config import get_settings


@dataclass(frozen=True)
class Principal:
    """The acting user, asserted by the BFF via a short-lived HS256 JWT (ADR-0002)."""

    user_id: str
    org_id: str | None = None
    # The caller's role in the active organization (owner/admin/member).
    # Signed in only by the destructive routes that need it
    # (ORGANIZATION_ROLES.md); absent everywhere else.
    org_role: str | None = None

    @property
    def is_org_admin(self) -> bool:
        return self.org_role in ("owner", "admin")


def _decode_bearer(request: Request) -> dict | None:
    """The verified JWT payload, or None when absent/invalid. Never raises."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        return jwt.decode(
            header.removeprefix("Bearer "),
            get_settings().engine_service_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None


def require_service_auth(request: Request) -> Principal:
    payload = _decode_bearer(request)
    if payload is None:
        raise HTTPException(status_code=401, detail="Missing or invalid service token")
    return Principal(
        user_id=str(payload["sub"]),
        org_id=payload.get("org"),
        org_role=payload.get("org_role"),
    )


def peek_principal(request: Request) -> Principal | None:
    """The verified caller, if any — used to pin the request's database
    session to that user's rows plus the active organization's shared rows
    (db/rls.py, docs/architecture/ORGANIZATION_SHARING.md). Verification is
    the same as require_service_auth; an invalid token pins nothing (and the
    route's auth dependency will 401 before the session is ever used)."""
    payload = _decode_bearer(request)
    if payload is None:
        return None
    return Principal(user_id=str(payload["sub"]), org_id=payload.get("org"))
