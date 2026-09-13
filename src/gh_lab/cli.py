"""Top-level command-line interface for gh-lab.

This module registers commands and dispatches to them. Business logic belongs in
each command's ``command.py``, and presentation in its ``shell.py``.
"""

import argparse
import os
from collections.abc import Sequence

from gh_lab import __version__
from gh_lab.commands.setup_check import shell as setup_check_shell


def program_name() -> str:
    """Return the name the CLI was invoked as.

    The GitHub CLI sets ``GH_EXTENSION=1`` when it runs an extension, so usage
    and help text can read ``gh lab ...`` in that case and ``gh-lab ...`` when
    the CLI is run directly, for example via ``uv run gh-lab``.
    """
    return "gh lab" if os.environ.get("GH_EXTENSION") == "1" else "gh-lab"


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """Build the top-level argument parser.

    Args:
        prog: Program name to display in usage text. Defaults to
            :func:`program_name`.
    """
    parser = argparse.ArgumentParser(
        prog=prog or program_name(),
        description="GitHub lab repository management tools.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        required=True,
    )

    setup_check_shell.register(subparsers)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and run the selected command, returning its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
