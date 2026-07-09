"""Scans a run's diff for leaked secrets before a pull request opens.

Only the *added* lines of a unified diff are scanned — the lines this run
introduces — because a secret already in the repository is not this run's leak
to block. Each added line is matched against a small set of high-confidence
patterns; a match yields a finding with the raw secret redacted, never stored.

Design note: docs/architecture/SECRETS_SCANNING.md.
"""

import re
from dataclasses import dataclass

# Values that look like a secret assignment but are obviously not real secrets;
# a labelled assignment whose value contains any of these is not a finding.
_PLACEHOLDER_HINTS = (
    "example",
    "changeme",
    "your",
    "placeholder",
    "redacted",
    "dummy",
    "xxxx",
    "os.environ",
    "process.env",
    "getenv",
)


@dataclass(frozen=True)
class SecretFinding:
    rule: str  # which pattern matched, e.g. "aws_access_key_id"
    path: str  # file the added line belongs to
    line: int  # 1-based line number in the new version of the file
    redacted: str  # the matched secret, masked — safe to store and display


# (rule name, compiled pattern). Order matters only for which rule is reported
# first when a line could match several; the most specific rules come first.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{36}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[0-9A-Za-z_]{22,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("stripe_secret_key", re.compile(r"\bsk_live_[0-9A-Za-z]{24,}\b")),
    (
        "labelled_secret_assignment",
        re.compile(
            r"""(?ix)                         # case-insensitive, verbose
            \b(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|
               client[_-]?secret|private[_-]?key)\b
            \s*[:=]\s*                          # = or : assignment
            (?P<qval>["'])(?P<value>[^"']{8,})(?P=qval)   # a quoted literal, 8+ chars
            """
        ),
    ),
)

# A single new-file line number tracker for a diff hunk header: @@ -a,b +c,d @@
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def scan_diff(diff: str) -> list[SecretFinding]:
    """Findings for every added line of a unified diff that matches a rule."""
    findings: list[SecretFinding] = []
    path = ""
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = _strip_diff_path(raw[4:])
            continue
        if raw.startswith(("--- ", "diff --git", "index ", "old mode", "new mode")):
            continue
        hunk = _HUNK.match(raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if raw.startswith("+"):
            finding = _scan_line(raw[1:], path, new_line)
            if finding is not None:
                findings.append(finding)
            new_line += 1
        elif raw.startswith("-"):
            continue  # a removed line has no place in the new file
        else:
            new_line += 1  # context line advances the new-file counter
    return findings


def _scan_line(text: str, path: str, line: int) -> SecretFinding | None:
    for rule, pattern in _RULES:
        match = pattern.search(text)
        if match is None:
            continue
        if rule == "labelled_secret_assignment":
            value = match.group("value")
            if _looks_like_placeholder(value):
                return None
            secret = value
        else:
            secret = match.group(0)
        return SecretFinding(rule=rule, path=path, line=line, redacted=_redact(secret))
    return None


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    if any(hint in lowered for hint in _PLACEHOLDER_HINTS):
        return True
    # Template / interpolation markers: ${VAR}, <your-key>, {{ token }}, %(x)s
    return any(marker in value for marker in ("${", "<", "{{", "%("))


def _redact(secret: str) -> str:
    """Keep a short prefix so a finding is identifiable; mask the rest."""
    if len(secret) <= 4:
        return "****"
    return f"{secret[:4]}{'*' * min(len(secret) - 4, 8)}"


def _strip_diff_path(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path
