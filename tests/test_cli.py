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
