"""Tests for the shared colour decision.

Every command that writes to a terminal goes through this, so the rules about
when colour is unwelcome are worth pinning in one place.
"""

import io

import pytest

from gh_lab.colour import GREEN, RESET, Painter, use_colour


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("setting", ["auto", "always", "never"])
def test_never_and_always_ignore_everything_else(setting):
    env = {"NO_COLOR": "1", "GITHUB_ACTIONS": "true"}

    expected = {"auto": False, "always": True, "never": False}[setting]

    assert use_colour(setting, Terminal(), env) is expected


def test_a_terminal_gets_colour():
    assert use_colour("auto", Terminal(), {}) is True


def test_a_pipe_does_not():
    assert use_colour("auto", io.StringIO(), {}) is False


def test_no_color_is_honoured_even_on_a_terminal():
    """https://no-color.org/ — set by people who mean it."""
    assert use_colour("auto", Terminal(), {"NO_COLOR": "1"}) is False


def test_github_actions_gets_colour_despite_not_being_a_terminal():
    """Actions renders ANSI in its logs, which is where students read this."""
    assert use_colour("auto", io.StringIO(), {"GITHUB_ACTIONS": "true"}) is True


def test_a_dumb_terminal_does_not():
    assert use_colour("auto", Terminal(), {"TERM": "dumb"}) is False


def test_no_color_beats_github_actions():
    env = {"NO_COLOR": "1", "GITHUB_ACTIONS": "true"}

    assert use_colour("auto", io.StringIO(), env) is False


def test_a_stream_that_cannot_say_gets_no_colour():
    """Not every file-like object has isatty."""

    class Anonymous:
        pass

    assert use_colour("auto", Anonymous(), {}) is False


def test_a_disabled_painter_changes_nothing():
    assert Painter(False)("text", GREEN) == "text"


def test_an_enabled_painter_wraps_and_resets():
    assert Painter(True)("text", GREEN) == f"{GREEN}text{RESET}"


def test_painting_with_no_style_changes_nothing():
    assert Painter(True)("text") == "text"
