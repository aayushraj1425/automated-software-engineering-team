"""Prompt drift detection: a prompt edit must be a visible decision.

The agent prompts are runtime assets the registry reads from disk — without
this test, editing one changes agent behavior with zero test signal. The
checked-in snapshot (prompt_snapshots.json) records each prompt's SHA-256;
any difference fails the suite and names the file.

Deliberate change? Review the diff, then refresh the snapshot and commit
both together:  uv run python tests/test_prompt_snapshots.py
Design note: docs/architecture/PROMPT_SNAPSHOTS.md.
"""

import hashlib
import json
from pathlib import Path

SNAPSHOT_FILE = Path(__file__).parent / "prompt_snapshots.json"
PROMPTS_DIR = Path(__file__).parent.parent / "src" / "engine" / "agents" / "prompts"

REFRESH_HINT = (
    "review the change, then refresh the snapshot with "
    "`uv run python tests/test_prompt_snapshots.py` and commit both files"
)


def _snapshot_of(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "lines": len(text.splitlines()),
    }


def _current_snapshots() -> dict[str, dict]:
    return {path.name: _snapshot_of(path) for path in sorted(PROMPTS_DIR.glob("*.md"))}


def test_every_prompt_matches_its_snapshot():
    recorded: dict[str, dict] = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    current = _current_snapshots()

    unrecorded = sorted(set(current) - set(recorded))
    assert not unrecorded, f"new prompt file(s) without a snapshot: {unrecorded} — {REFRESH_HINT}"

    missing = sorted(set(recorded) - set(current))
    assert not missing, f"snapshot(s) whose prompt file is gone: {missing} — {REFRESH_HINT}"

    changed = sorted(name for name in current if current[name] != recorded[name])
    assert not changed, f"prompt(s) changed since their snapshot: {changed} — {REFRESH_HINT}"


def test_the_snapshot_covers_every_registered_role():
    """The registry is the consumer — every spec's prompt file must be under
    snapshot protection (a prompt outside the registry is dead weight)."""
    from engine.agents.registry import all_agent_specs

    registered = {spec.prompt_file for spec in all_agent_specs()}
    recorded = set(json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8")))
    assert registered == recorded


if __name__ == "__main__":
    SNAPSHOT_FILE.write_text(
        json.dumps(_current_snapshots(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"snapshot refreshed: {SNAPSHOT_FILE}")
