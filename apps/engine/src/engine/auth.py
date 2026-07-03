from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

from engine.config import get_settings


@dataclass(frozen=True)
class Principal:
    """The acting user, asserted by the BFF via a short-lived HS256 JWT (ADR-0002)."""

    user_id: str
    org_id: str | None = None


def require_service_auth(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header.removeprefix("Bearer ")
    try:
        payload = jwt.decode(
            token,
            get_settings().engine_service_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid service token") from exc
    return Principal(user_id=str(payload["sub"]), org_id=payload.get("org"))
