"""Scans a run's diff for known-vulnerable dependencies before a pull request.

A sibling of secrets_scanner: it reads only the *added* lines of a unified diff
(a vulnerable package already in the repository is not this run's to block),
extracts (package, version) pairs from recognized manifests, and matches them
against a curated, offline advisory list. Deterministic and network-free, so it
runs in tests like the secrets gate. Design note:
docs/architecture/DEPENDENCY_SCANNING.md.
"""

import re
from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

Ecosystem = str  # "pypi" | "npm"


@dataclass(frozen=True)
class Advisory:
    ecosystem: Ecosystem
    package: str  # normalized name
    specifiers: str  # PEP 440 SpecifierSet of vulnerable versions, e.g. "<4.17.21"
    advisory_id: str
    severity: str  # "high" | "medium" | "low"
    summary: str


@dataclass(frozen=True)
class DependencyFinding:
    ecosystem: Ecosystem
    package: str
    version: str
    advisory_id: str
    severity: str
    summary: str
    path: str
    line: int


# Curated, high-confidence advisories. Small on purpose — every entry is a known
# CVE with a clear fixed version. A live feed (OSV) is future work.
_ADVISORIES: tuple[Advisory, ...] = (
    Advisory(
        "pypi",
        "requests",
        "<2.31.0",
        "CVE-2023-32681",
        "medium",
        "leaks Proxy-Authorization header on redirect",
    ),
    Advisory(
        "pypi", "urllib3", "<1.26.5", "CVE-2021-33503", "high", "denial of service via crafted URL"
    ),
    Advisory(
        "pypi",
        "jinja2",
        "<2.11.3",
        "CVE-2020-28493",
        "medium",
        "regular-expression denial of service",
    ),
    Advisory(
        "pypi", "pyyaml", "<5.4", "CVE-2020-14343", "high", "arbitrary code execution via full_load"
    ),
    Advisory(
        "pypi",
        "flask",
        "<2.2.5",
        "CVE-2023-30861",
        "high",
        "possible disclosure of a cached response to the wrong client",
    ),
    Advisory(
        "npm", "lodash", "<4.17.21", "CVE-2021-23337", "high", "command injection via template"
    ),
    Advisory("npm", "minimist", "<1.2.6", "CVE-2021-44906", "high", "prototype pollution"),
    Advisory("npm", "axios", "<0.21.2", "CVE-2021-3749", "high", "server-side request forgery"),
    Advisory(
        "npm",
        "node-fetch",
        "<2.6.7",
        "CVE-2022-0235",
        "medium",
        "leaks sensitive headers/cookie on cross-host redirect",
    ),
)

# advisory index: (ecosystem, normalized name) -> advisories for that package
_INDEX: dict[tuple[Ecosystem, str], list[Advisory]] = {}
for _adv in _ADVISORIES:
    _INDEX.setdefault((_adv.ecosystem, _adv.package), []).append(_adv)

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# requirements.txt: an exact pin "name==1.2.3" (ignoring extras/markers/comments)
_PIP_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([0-9][^\s;#,]*)")
# package.json / package-lock.json: a "name": "version" pair
_JSON_PAIR = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')
# package-lock.json (v2/v3): the key that names a package, "node_modules/<name>":
_LOCK_KEY = re.compile(r'"(?:.*/)?node_modules/([^"/]+)"\s*:')
# a bare npm version range prefix to strip: ^1.2.3, ~1.2.3, >=1.2.3
_NPM_RANGE_PREFIX = re.compile(r"^[\^~>=<\s]*")


def scan_diff(diff: str) -> list[DependencyFinding]:
    """Findings for every added manifest line that pins a known-vulnerable version."""
    findings: list[DependencyFinding] = []
    path = ""
    kind = ""  # "pip" | "package_json" | "package_lock" | ""
    new_line = 0
    lock_pending_name = ""  # last node_modules key seen (context or added) in a lockfile
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = _strip_diff_path(raw[4:])
            kind = _manifest_kind(path)
            lock_pending_name = ""
            continue
        if raw.startswith(("--- ", "diff --git", "index ", "old mode", "new mode")):
            continue
        hunk = _HUNK.match(raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if not kind:
            continue

        added = raw.startswith("+")
        removed = raw.startswith("-")
        content = raw[1:] if raw and raw[0] in "+ " else raw

        # Lockfiles: track the package name from any non-removed line (a version
        # line's name usually sits on an unchanged line just above); flag only
        # added versions.
        if kind == "package_lock" and not removed:
            key = _LOCK_KEY.search(content)
            if key:
                lock_pending_name = key.group(1)

        if added:
            pair = _extract(kind, content, lock_pending_name)
            if pair is not None:
                name, version = pair
                finding = _match(kind, name, version, path, new_line)
                if finding is not None:
                    findings.append(finding)
        if not removed:
            new_line += 1  # both added and context lines advance the new-file counter
    return findings


def _extract(kind: str, content: str, lock_pending_name: str) -> tuple[str, str] | None:
    if kind == "pip":
        match = _PIP_PIN.match(content)
        return (match.group(1), match.group(2)) if match else None
    if kind == "package_json":
        match = _JSON_PAIR.search(content)
        if match is None:
            return None
        return match.group(1), _npm_base_version(match.group(2))
    if kind == "package_lock":
        match = _JSON_PAIR.search(content)
        if match is None or match.group(1) != "version" or not lock_pending_name:
            return None
        return lock_pending_name, _npm_base_version(match.group(2))
    return None


def _match(kind: str, name: str, version: str, path: str, line: int) -> DependencyFinding | None:
    ecosystem: Ecosystem = "pypi" if kind == "pip" else "npm"
    normalized = _normalize(ecosystem, name)
    advisories = _INDEX.get((ecosystem, normalized))
    if not advisories:
        return None
    try:
        parsed = Version(version)
    except InvalidVersion:
        return None
    for adv in advisories:
        try:
            spec = SpecifierSet(adv.specifiers)
        except InvalidSpecifier:
            continue
        if parsed in spec:
            return DependencyFinding(
                ecosystem=ecosystem,
                package=normalized,
                version=version,
                advisory_id=adv.advisory_id,
                severity=adv.severity,
                summary=adv.summary,
                path=path,
                line=line,
            )
    return None


def _manifest_kind(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    if name == "package-lock.json":
        return "package_lock"
    if name == "package.json":
        return "package_json"
    if name.endswith("requirements.txt") or name == "requirements.txt":
        return "pip"
    return ""


def _npm_base_version(value: str) -> str:
    """Strip a leading range operator (^, ~, >=) so "^4.17.20" → "4.17.20"."""
    return _NPM_RANGE_PREFIX.sub("", value.strip())


def _normalize(ecosystem: Ecosystem, name: str) -> str:
    lowered = name.strip().lower()
    if ecosystem == "pypi":
        return re.sub(r"[-_.]+", "-", lowered)  # PEP 503
    return lowered


def _strip_diff_path(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path
