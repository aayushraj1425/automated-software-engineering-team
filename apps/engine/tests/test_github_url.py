"""parse_github_repo gates PR creation, so it must recognise the URL shapes a
user actually pastes — including one copied from the browser with a trailing
path or query — and still reject non-GitHub URLs."""

import pytest

from engine.github import parse_github_repo


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octocat/hello-world",
        "https://github.com/octocat/hello-world.git",
        "https://github.com/octocat/hello-world/",
        "git@github.com:octocat/hello-world.git",
        "https://github.com/octocat/hello-world/tree/main",  # copied from the browser
        "https://github.com/octocat/hello-world/pull/42",
        "https://github.com/octocat/hello-world?tab=readme-ov-file",
        "https://github.com/octocat/hello-world#readme",
        "  https://github.com/octocat/hello-world  ",  # stray whitespace
    ],
)
def test_extracts_owner_and_repo(url):
    assert parse_github_repo(url) == ("octocat", "hello-world")


def test_keeps_a_dotted_repo_name_intact():
    assert parse_github_repo("https://github.com/octocat/octocat.github.io") == (
        "octocat",
        "octocat.github.io",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/octocat/hello-world",  # not GitHub
        "/home/user/local-repo",  # a local path
        "https://github.com/octocat",  # no repo segment
        "",
    ],
)
def test_returns_none_for_non_github_repo_urls(url):
    assert parse_github_repo(url) is None
