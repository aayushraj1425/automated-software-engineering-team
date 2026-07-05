"""The path jail: agents may only touch files inside their own workspace.

Every file path an agent supplies goes through resolve_inside() before any
read or write. If the path would land outside the workspace folder — via
"..", an absolute path, a Windows drive or UNC path, or a symlink pointing
out — it is rejected. Security-critical (ADR-0008): tools call this, always.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath


class JailViolation(Exception):
    """The agent asked for a path outside its workspace."""


def resolve_inside(root: Path, relative: str) -> Path:
    """Turn an agent-supplied relative path into a safe absolute path.

    Raises JailViolation unless the fully-resolved result (symlinks and ".."
    included) stays inside `root`. Paths are judged under BOTH Windows and
    POSIX rules so the jail behaves identically on a Windows dev machine and
    on Linux CI/production — "C:secret" or "\\\\server\\share" must be
    rejected everywhere, not only where the OS happens to parse them.
    """
    if "\x00" in relative:
        raise JailViolation("path contains a null byte")

    # Treat backslashes as separators on every OS (agents emit both forms).
    normalized = relative.strip().replace("\\", "/")

    # Absolute paths ("/etc/passwd"), Windows drives ("C:\\...", "C:secret")
    # and UNC shares ("//server/share") are never allowed.
    if (
        PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(normalized).is_absolute()
        or PureWindowsPath(normalized).drive
    ):
        raise JailViolation(f"absolute paths are not allowed: {relative!r}")

    root_resolved = root.resolve()
    # resolve() follows every symlink and folds every "..", so whatever
    # comes out is the real location we would actually touch.
    candidate = (root_resolved / normalized).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise JailViolation(f"path escapes the workspace: {relative!r}")
    return candidate
