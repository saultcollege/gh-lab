import argparse

from gh_lab.commands.setup_check import parser as setup_check_parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gh-lab",
        description="GitHub lab repository management tools.",
    )

    subparsers = parser.add_subparsers(required=True)

    setup_check_parser.register(subparsers)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())