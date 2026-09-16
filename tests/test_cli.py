"""Tests for the top-level CLI and the extension entry point."""

import os
import re
import tomllib
from pathlib import Path

import pytest

import gh_lab
from gh_lab.cli import build_parser, main

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "gh-lab"


@pytest.fixture
def pyproject() -> dict:
    """The parsed contents of ``pyproject.toml``."""
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())


def test_help_exits_zero_and_lists_setup_check(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "setup-check" in capsys.readouterr().out


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert gh_lab.__version__ in capsys.readouterr().out


def test_bare_invocation_exits_two_with_usage(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_unknown_command_exits_two():
    with pytest.raises(SystemExit) as exc_info:
        main(["not-a-command"])

    assert exc_info.value.code == 2


def test_prog_is_gh_lab_when_invoked_via_gh(monkeypatch):
    monkeypatch.setenv("GH_EXTENSION", "1")

    assert build_parser().prog == "gh lab"


def test_prog_is_hyphenated_when_invoked_directly(monkeypatch):
    monkeypatch.delenv("GH_EXTENSION", raising=False)

    assert build_parser().prog == "gh-lab"


def test_version_matches_pyproject(pyproject):
    """The runtime version and the packaging metadata must not drift."""
    assert gh_lab.__version__ == pyproject["project"]["version"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="the executable bit is not meaningful on Windows; CI asserts the git index mode instead",
)
def test_extension_shim_is_executable():
    """gh cannot run a script extension whose entry point is not executable."""
    assert SHIM.is_file()
    assert os.access(SHIM, os.X_OK)


def test_shim_minimum_python_matches_requires_python(pyproject):
    """The shim's version floor must match the packaging metadata."""
    shim = SHIM.read_text()
    major = re.search(r"^MIN_PYTHON_MAJOR=(\d+)$", shim, re.MULTILINE)
    minor = re.search(r"^MIN_PYTHON_MINOR=(\d+)$", shim, re.MULTILINE)

    assert major and minor, "shim must declare MIN_PYTHON_MAJOR and MIN_PYTHON_MINOR"

    shim_floor = f">={major.group(1)}.{minor.group(1)}"

    assert shim_floor == pyproject["project"]["requires-python"]


# --- nested command groups -------------------------------------------------


def test_help_lists_the_admin_group(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "admin" in capsys.readouterr().out


def test_admin_help_lists_its_groups(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["admin", "--help"])

    assert exc_info.value.code == 0
    assert "invites" in capsys.readouterr().out


def test_admin_invites_help_lists_its_verbs(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["admin", "invites", "--help"])

    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "send" in out
    assert "accept" in out


def test_bare_admin_exits_two_with_usage(capsys):
    """A group is not a command, so naming one alone is a usage error."""
    with pytest.raises(SystemExit) as exc_info:
        main(["admin"])

    assert exc_info.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_bare_admin_invites_exits_two_with_usage(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["admin", "invites"])

    assert exc_info.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_unknown_admin_group_exits_two():
    with pytest.raises(SystemExit) as exc_info:
        main(["admin", "not-a-group"])

    assert exc_info.value.code == 2


def test_unknown_invites_verb_exits_two():
    with pytest.raises(SystemExit) as exc_info:
        main(["admin", "invites", "not-a-verb"])

    assert exc_info.value.code == 2


def test_a_nested_verb_dispatches_through_its_handler(monkeypatch):
    """Dispatch is by the handler default, unchanged by the extra nesting."""
    from gh_lab.commands.admin_invites import shell as admin_invites_shell

    seen = []
    monkeypatch.setattr(
        admin_invites_shell,
        "handle_send",
        lambda args: (seen.append(args), 0)[1],
    )

    argv = ["admin", "invites", "send", "--config-file", "org/course-config/26f.json"]

    assert main(argv) == 0
    assert len(seen) == 1


def test_an_unimplemented_verb_says_so(capsys):
    """Registered before it is implemented; better said than silently wrong."""
    assert main(["admin", "invites", "accept"]) == 2
    assert "not implemented" in capsys.readouterr().err
