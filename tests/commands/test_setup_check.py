"""Tests for the ``setup-check`` command."""

import argparse

import pytest

from gh_lab.cli import main
from gh_lab.commands.setup_check import shell
from gh_lab.commands.setup_check.command import SetupCheckResult, run


def test_setup_check_appears_in_top_level_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])

    assert "setup-check" in capsys.readouterr().out


def test_setup_check_requires_org_and_lab_name():
    with pytest.raises(SystemExit) as exc_info:
        main(["setup-check"])

    assert exc_info.value.code == 2


def test_handle_forwards_arguments_to_run(monkeypatch):
    calls = []

    def fake_run(*, org, lab_name):
        calls.append((org, lab_name))
        return SetupCheckResult(ok=True)

    monkeypatch.setattr(shell, "run", fake_run)

    shell.handle(argparse.Namespace(org="acme", lab_name="lab-1"))

    assert calls == [("acme", "lab-1")]


def test_run_returns_not_implemented_result():
    """The stub must return a result rather than raising."""
    result = run("acme", "lab-1")

    assert result.ok is False
    assert result.messages


def test_handle_reports_failure_on_stderr(capsys):
    exit_code = shell.handle(argparse.Namespace(org="acme", lab_name="lab-1"))

    assert exit_code == 1
    assert capsys.readouterr().err.strip()


def test_handle_returns_zero_when_check_passes(monkeypatch):
    monkeypatch.setattr(shell, "run", lambda **_: SetupCheckResult(ok=True))

    assert shell.handle(argparse.Namespace(org="acme", lab_name="lab-1")) == 0
