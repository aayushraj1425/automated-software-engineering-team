"""The path jail: agents may only touch files inside their own workspace.

Every file path an agent supplies goes through resolve_inside() before any
read or write. If the path would land outside the workspace folder — via
"..", an absolute path, a Windows drive or UNC path, or a symlink pointing
out — it is rejected. Security-critical (ADR-0008): tools call this, always.
"""

from pathlib import Path


class JailViolation(Exception):
    """The agent asked for a path outside its workspace."""


def resolve_inside(root: Path, relative: str) -> Path:
    """Turn an agent-supplied relative path into a safe absolute path.

    Raises JailViolation unless the fully-resolved result (symlinks and ".."
    included) stays inside `root`.
    """
    if "\x00" in relative:
        raise JailViolation("path contains a null byte")

    rel = Path(relative.strip())
    # Absolute paths ("/etc/passwd", "C:\\Windows") and drive-relative
    # Windows paths ("C:secret") and UNC paths ("\\\\server\\share") all
    # carry an anchor or drive — reject them outright.
    if rel.is_absolute() or rel.drive:
        raise JailViolation(f"absolute paths are not allowed: {relative!r}")

    root_resolved = root.resolve()
    # resolve() follows every symlink and folds every "..", so whatever
    # comes out is the real location we would actually touch.
    candidate = (root_resolved / rel).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise JailViolation(f"path escapes the workspace: {relative!r}")
    return candidate
