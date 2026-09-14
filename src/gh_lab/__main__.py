"""Entry point for ``python -m gh_lab``, used by the ``gh-lab`` extension shim."""

from gh_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
