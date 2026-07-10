"""The dependency vulnerability scanner: parse manifest diffs, match advisories.

Pure-function tests (no DB, no network) mirroring the secrets-scanner tests.
Only ADDED manifest lines are scanned, and only known-vulnerable versions match.
Design note: docs/architecture/DEPENDENCY_SCANNING.md.
"""

from engine.security.dependency_scanner import scan_diff


def _diff(path: str, added: list[str], context: list[str] | None = None) -> str:
    """A minimal one-file unified diff with the given added (+) lines."""
    body = [f"+++ b/{path}", f"@@ -1,1 +1,{len(added) + len(context or [])} @@"]
    for line in context or []:
        body.append(f" {line}")
    for line in added:
        body.append(f"+{line}")
    return "\n".join(body) + "\n"


def test_flags_a_vulnerable_pinned_requirement():
    findings = scan_diff(_diff("requirements.txt", ["requests==2.30.0"]))
    assert len(findings) == 1
    assert findings[0].package == "requests"
    assert findings[0].advisory_id == "CVE-2023-32681"
    assert findings[0].ecosystem == "pypi"


def test_ignores_a_patched_requirement():
    assert scan_diff(_diff("requirements.txt", ["requests==2.31.0"])) == []


def test_ignores_an_unpinned_requirement():
    # Without a concrete version we cannot confirm it is vulnerable.
    assert scan_diff(_diff("requirements.txt", ["requests>=2.0"])) == []


def test_normalizes_pypi_names():
    # PyYAML / py-yaml style names normalize to the advisory key.
    findings = scan_diff(_diff("requirements.txt", ["PyYAML==5.3.1"]))
    assert findings and findings[0].package == "pyyaml"


def test_flags_a_vulnerable_package_json_range():
    findings = scan_diff(_diff("package.json", ['    "lodash": "^4.17.20",']))
    assert len(findings) == 1
    assert findings[0].package == "lodash"
    assert findings[0].version == "4.17.20"
    assert findings[0].ecosystem == "npm"


def test_ignores_a_patched_package_json_range():
    assert scan_diff(_diff("package.json", ['    "lodash": "^4.17.21",'])) == []


def test_ignores_non_dependency_json_pairs():
    # "name"/"version" of the project itself must not be mistaken for a package.
    diff = _diff("package.json", ['  "name": "my-app",', '  "version": "1.0.0",'])
    assert scan_diff(diff) == []


def test_flags_a_lockfile_version_paired_with_its_key():
    # The node_modules key is a context line; the bumped version is the added line.
    diff = _diff(
        "package-lock.json",
        added=['      "version": "1.2.5",'],
        context=['    "node_modules/minimist": {'],
    )
    findings = scan_diff(diff)
    assert len(findings) == 1
    assert findings[0].package == "minimist"
    assert findings[0].version == "1.2.5"


def test_ignores_a_lockfile_version_with_no_known_package():
    diff = _diff(
        "package-lock.json",
        added=['      "version": "1.0.0",'],
        context=['    "node_modules/some-safe-pkg": {'],
    )
    assert scan_diff(diff) == []


def test_only_added_lines_are_scanned():
    # A vulnerable line that is context (already in the repo), not added, is ignored.
    diff = "\n".join(
        [
            "+++ b/requirements.txt",
            "@@ -1,2 +1,2 @@",
            " requests==2.30.0",  # context (pre-existing) — not this run's to block
            "+flask==2.2.4",  # added — vulnerable, flagged
        ]
    )
    findings = scan_diff(diff)
    assert len(findings) == 1
    assert findings[0].package == "flask"


def test_a_non_manifest_file_is_never_scanned():
    diff = _diff("app/config.py", ['requests = "requests==2.30.0"'])
    assert scan_diff(diff) == []
