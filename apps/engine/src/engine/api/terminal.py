"""Terminal API: run one command in a finished run's sandboxed session.

The same guards as the other workspace write panels (finished runs only,
run-page visibility scoping), and ADR-0008's boundary intact — commands
execute in the sandbox container, never on the host.
Design note: docs/architecture/IN_BROWSER_TERMINAL.md.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from engine.api.runs import _load_run_workspace, _require_editable, _visible_run
from engine.auth import Principal, require_service_auth
from engine.db.session import get_session
from engine.sandbox.terminal import (
    MAX_COMMAND_LENGTH,
    TerminalUnavailable,
    reset_terminal,
    run_terminal_command,
)

router = APIRouter()


class TerminalCommandIn(BaseModel):
    command: str = Field(min_length=1, max_length=MAX_COMMAND_LENGTH)


class TerminalCommandOut(BaseModel):
    output: str
    exit_code: int
    fresh_session: bool


@router.post("/v1/runs/{run_id}/terminal")
async def run_command(
    run_id: uuid.UUID,
    body: TerminalCommandIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> TerminalCommandOut:
    """One command in the run's sandboxed scratch copy of the workspace."""
    run = await _visible_run(db, run_id, principal)
    _require_editable(run)  # in-flight workspaces belong to the agent loop
    ws = _load_run_workspace(run)
    if not body.command.strip():
        raise HTTPException(status_code=422, detail="The command is empty")
    try:
        result = await run_terminal_command(run_id, ws.path, body.command)
    except TerminalUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return TerminalCommandOut(
        output=result.output,
        exit_code=result.exit_code,
        fresh_session=result.fresh_session,
    )


@router.delete("/v1/runs/{run_id}/terminal", status_code=204)
async def reset(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Discard the session — the next command starts from a fresh copy."""
    await _visible_run(db, run_id, principal)
    await reset_terminal(run_id)
