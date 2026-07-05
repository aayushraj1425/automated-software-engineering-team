"""The path jail must reject every way of escaping the workspace (ADR-0008)."""

import os
import sys

import pytest

from engine.workspace.jail import JailViolation, resolve_inside


@pytest.fixture
def root(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    return tmp_path


def test_normal_paths_resolve_inside(root):
    assert resolve_inside(root, "src/main.py") == (root / "src" / "main.py").resolve()
    assert resolve_inside(root, "./src/../src/main.py") == (root / "src" / "main.py").resolve()
    assert resolve_inside(root, "new/deep/file.txt").is_relative_to(root.resolve())
    assert resolve_inside(root, ".") == root.resolve()


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../outside.txt",
        "src/../../outside.txt",
        "a/b/../../../outside.txt",
    ],
)
def test_dotdot_traversal_is_rejected(root, bad):
    with pytest.raises(JailViolation):
        resolve_inside(root, bad)


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "C:\\Windows\\System32\\config",
        "C:secret.txt",
        "\\\\server\\share\\file",
        "//server/share/file",
    ],
)
def test_absolute_drive_and_unc_paths_are_rejected(root, bad):
    with pytest.raises(JailViolation):
        resolve_inside(root, bad)


def test_null_byte_is_rejected(root):
    with pytest.raises(JailViolation):
        resolve_inside(root, "src/\x00evil")


def test_symlink_pointing_outside_is_rejected(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("secret")
    link = root / "innocent"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create symlinks on this system (Windows without dev mode)")
    with pytest.raises(JailViolation):
        resolve_inside(root, "innocent/secret.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path forms")
def test_windows_backslash_traversal_is_rejected(root):
    with pytest.raises(JailViolation):
        resolve_inside(root, "..\\outside.txt")
    with pytest.raises(JailViolation):
        resolve_inside(root, "src\\..\\..\\outside.txt")
