"""The secrets scanner: which added lines of a diff count as a leak.

Design note: docs/architecture/SECRETS_SCANNING.md.
"""

from engine.security.secrets_scanner import scan_diff


def _diff(path: str, *added: str) -> str:
    """A minimal unified diff that adds `added` lines to a new file `path`."""
    body = "\n".join(f"+{line}" for line in added)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(added)} @@\n"
        f"{body}\n"
    )


def test_flags_aws_access_key():
    # A real AWS access key id is exactly AKIA + 16 uppercase/digit characters.
    findings = scan_diff(_diff("app/config.py", 'AWS_KEY = "AKIA0000TESTKEY00000"'))
    assert len(findings) == 1
    assert findings[0].rule == "aws_access_key_id"
    assert findings[0].path == "app/config.py"
    assert "AKIA0000TESTKEY00000" not in findings[0].redacted  # secret is masked


def test_flags_private_key_block():
    findings = scan_diff(_diff("id_rsa", "-----BEGIN OPENSSH PRIVATE KEY-----"))
    assert [f.rule for f in findings] == ["private_key"]


def test_flags_github_and_stripe_tokens():
    findings = scan_diff(
        _diff(
            "deploy.sh",
            "export GH=ghp_" + "a" * 36,
            "STRIPE=sk_live_" + "b" * 24,
        )
    )
    assert {f.rule for f in findings} == {"github_token", "stripe_secret_key"}


def test_labelled_assignment_is_flagged_but_placeholders_are_not():
    leak = scan_diff(_diff("settings.py", 'password = "hunter2primaryDB"'))
    assert [f.rule for f in leak] == ["labelled_secret_assignment"]

    for placeholder in (
        'password = "changeme"',
        'password = "${DB_PASSWORD}"',
        'password = "<your-password>"',
        "password = os.environ['DB_PASSWORD']",
    ):
        assert scan_diff(_diff("settings.py", placeholder)) == []


def test_only_added_lines_are_scanned():
    # A removed line and a context line carrying a key must not be flagged.
    diff = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        '-old = "AKIA0000TESTKEY00000"\n'
        ' context = "AKIA0000TESTKEY00000"\n'
        "+added = 1\n"
    )
    assert scan_diff(diff) == []


def test_line_numbers_track_the_new_file():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -10,1 +10,3 @@\n"
        " keep = 1\n"
        "+harmless = 2\n"
        # A Google API key is AIza + 35 more characters.
        '+token = "AIza' + "0" * 35 + '"\n'
    )
    findings = scan_diff(diff)
    assert len(findings) == 1
    assert findings[0].rule == "google_api_key"
    assert findings[0].line == 12  # 10 (context) + 1 (harmless) + 1


def test_clean_diff_has_no_findings():
    assert scan_diff(_diff("app/main.py", "def add(a, b):", "    return a + b")) == []
