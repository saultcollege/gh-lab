import argparse

from gh_lab.commands.setup_check.command import run


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "setup-check",
        help="Check whether the current lab repository is configured correctly.",
    )

    parser.add_argument("--org", required=True)
    parser.add_argument("--lab-name", required=True)

    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    return run(
        org=args.org,
        lab_name=args.lab_name,
    )