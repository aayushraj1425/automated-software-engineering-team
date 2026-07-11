"""The clone-URL guard: only safe repository URLs may reach `git clone`.

A user-controlled URL passed to git unchecked is remote code execution — the
`ext::` transport runs an arbitrary shell command, and a URL that starts with
"-" is parsed as a git option. ensure_cloneable_url() rejects both classes and
allows only https URLs and local paths that actually exist (dev fixtures).
"""

from pathlib import Path

import pytest

from engine.workspace.manager import WorkspaceError, ensure_cloneable_url


def test_https_urls_are_cloneable():
    url = "https://github.com/acme/demo"
    assert ensure_cloneable_url(url) == url
    assert ensure_cloneable_url("  HTTPS://github.com/acme/demo  ").startswith("HTTPS://")


def test_an_existing_local_path_is_cloneable(tmp_path: Path):
    assert ensure_cloneable_url(str(tmp_path)) == str(tmp_path)


def test_a_missing_local_path_is_rejected(tmp_path: Path):
    with pytest.raises(WorkspaceError):
        ensure_cloneable_url(str(tmp_path / "does-not-exist"))


@pytest.mark.parametrize(
    "url",
    [
        'ext::sh -c "id"',  # git's ext transport executes shell commands
        "--upload-pack=touch pwned",  # a leading dash becomes a git option
        "-o ProxyCommand=calc",
        "ssh://git@github.com/acme/demo",  # unsupported transport for now
        "git://github.com/acme/demo",
        "file::///etc",
        "",
    ],
)
def test_dangerous_or_unsupported_urls_are_rejected(url: str):
    with pytest.raises(WorkspaceError):
        ensure_cloneable_url(url)
