"""Commit history for the changelog: real dates, real subjects, bounded.

A temporary **bare shallow clone** fetches history only — no working tree,
no blobs beyond what the log needs — and is removed afterwards. The URL goes
through the same `ensure_cloneable_url` hygiene as every other clone. A
fetch that fails (private remote, network down) returns an empty string so
the changelog can fall back to its snapshot summary honestly instead of
inventing history. Design note: docs/architecture/DOCUMENTATION_SUITE.md.
"""

import tempfile
from pathlib import Path

import structlog

from engine.workspace.manager import WorkspaceError, ensure_cloneable_url, remove_tree, run_git

log = structlog.get_logger(__name__)

# Enough commits for a meaningful changelog; small enough to fetch quickly.
HISTORY_LIMIT = 100
_LOG_FORMAT = "%ad %h %s (%an)"


async def collect_history(url: str, limit: int = HISTORY_LIMIT) -> str:
    """The repository's last commits, one `date hash subject (author)` line
    per commit (newest first) — or "" when the history cannot be fetched."""
    tmp = Path(tempfile.mkdtemp(prefix="asep-history-"))
    clone = tmp / "history.git"
    try:
        await run_git(
            tmp,
            # The fetch is anonymous by design: disable credential helpers so
            # an unreachable private remote fails fast (no GUI popup, no
            # prompt) and the changelog falls back to the snapshot.
            "-c",
            "credential.helper=",
            "clone",
            "--bare",
            "--depth",
            str(limit),
            "--quiet",
            "--",
            ensure_cloneable_url(url),
            str(clone),
        )
        return await run_git(
            clone, "log", f"--max-count={limit}", "--date=short", f"--pretty=format:{_LOG_FORMAT}"
        )
    except WorkspaceError as exc:
        # No history is a degraded mode, not an error — the changelog says so.
        log.info("changelog.history_unavailable", url=url[:200], reason=str(exc)[:200])
        return ""
    finally:
        remove_tree(tmp)
