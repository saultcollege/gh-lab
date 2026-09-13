"""Shell layer for the ``setup-check`` command.

Owns the CLI-specific concerns: argument registration, terminal output, and the
exit code.
"""

import argparse
import sys

from gh_lab.commands.setup_check.command import run


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``setup-check`` subcommand on ``subparsers``."""
    parser = subparsers.add_parser(
        "setup-check",
        help="Check whether the current lab repository is configured correctly.",
    )

    parser.add_argument("--org", required=True)
    parser.add_argument("--lab-name", required=True)

    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Run the command for parsed ``args`` and return an exit code."""
    result = run(
        org=args.org,
        lab_name=args.lab_name,
    )

    for message in result.messages:
        print(message, file=sys.stderr)

    return 0 if result.ok else 1
