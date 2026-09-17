"""Shared setup for the test suite.

Nothing here reaches GitHub, git, or the network. Every adapter call ends up in
``subprocess.run``, so that is blocked for every test and each one that needs an
external command says so by stubbing it.
"""

import subprocess

import pytest


@pytest.fixture(autouse=True)
def no_external_commands(monkeypatch):
    """Fail loudly on an unstubbed external command.

    A test that forgets to stub an adapter would otherwise make a real API call
    and still pass, costing only time. That happened once: adding a call to ask
    who is signed in quietly sent the whole suite to GitHub, and the only symptom
    was the run taking five seconds longer.

    A test that wants a command stubs ``subprocess.run`` itself, which replaces
    this.
    """

    def blocked(args, *rest, **kwargs):
        raise AssertionError(
            f"this test ran an external command: {args}\n"
            "Stub subprocess.run, or stub the adapter function that calls it."
        )

    monkeypatch.setattr(subprocess, "run", blocked)
