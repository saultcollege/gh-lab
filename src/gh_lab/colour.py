"""ANSI colour, and whether to use it.

Shared by every command that writes to a terminal, so that one decision about
when colour is appropriate serves all of them rather than each reaching its own.

Everything here is pure: :func:`use_colour` is told about its environment rather
than inspecting one, and :class:`Painter` only builds strings.
"""

from collections.abc import Mapping
from typing import TextIO

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BRIGHT_BLUE = "\033[94m"


def use_colour(
    setting: str,
    stream: TextIO,
    env: Mapping[str, str],
) -> bool:
    """Decide whether to emit ANSI colour.

    GitHub Actions renders ANSI colour in its logs even though the log is not a
    terminal, so it is treated as colour-capable.
    """
    if setting == "never":
        return False

    if setting == "always":
        return True

    if env.get("NO_COLOR"):
        return False

    if env.get("GITHUB_ACTIONS") == "true":
        return True

    if env.get("TERM") == "dumb":
        return False

    return bool(getattr(stream, "isatty", lambda: False)())


class Painter:
    """Applies ANSI styles, or not."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text

        return f"{''.join(styles)}{text}{RESET}"
