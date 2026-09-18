# Development

## Requirements

* Python (3.11 or newer; the devcontainer uses 3.14)
* `uv`
* Git
* GitHub CLI (`gh`)

## Setup

    uv sync

## Development environment

The recommended development environment is the VS Code devcontainer defined in
`.devcontainer/devcontainer.json`.

Opening the repository in the devcontainer provides the required Python and
development tooling without requiring them to be installed on the host.

After the container is created, project dependencies are synchronized with:

    uv sync

## Run

The project can be run with:

    uv run gh-lab --help

## Run as a gh extension

To exercise the extension the way a user would, install it from the working
checkout:

    gh extension install .

`gh` installs a local checkout as a symlink, so edits to the working tree take
effect immediately with no reinstall. Run it as:

    gh lab --help

and remove it with:

    gh extension remove lab

Only one extension named `lab` can be installed at a time, so remove a local
install before installing the published one, and vice versa.

Set `GH_LAB_PYTHON` to run the extension under a specific interpreter, which is
useful for checking behaviour on the oldest supported Python:

    GH_LAB_PYTHON=/usr/bin/python3 gh lab --help

## Test

    uv run pytest

The suite never reaches GitHub, git, or the network. `tests/conftest.py` blocks
`subprocess.run` for every test, so a test that exercises an adapter has to stub
it — either `subprocess.run` itself, as the adapter tests do, or the adapter
function that calls it, as the command tests do.

A test that forgets shows up as:

    AssertionError: this test ran an external command: ['gh', 'api', 'user']

rather than as a real API call that passes and merely takes longer, which is how
one went unnoticed.

## Lint

    uv run ruff check .

## Format

    uv run ruff format --check .

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and on pushes to `main`, in
three jobs:

* **checks** — asserts the `gh-lab` entry point is mode `100755` in the Git
  index, then runs `uv sync --locked` and the lint, format and test commands
  listed above.
* **extension** (Linux) — installs the extension with `gh extension install .`
  on both the oldest and newest supported Python versions and asserts that
  `gh lab --help`, `gh lab --version`, bare `gh lab`, `gh lab setup-check` and
  the commands under `gh lab admin` behave correctly. The `admin invites accept`
  step runs under `timeout` with stdin closed: a prompt nobody can answer would
  hang the job rather than fail it, so blocking is what that step is there to
  catch.
* **platforms** (macOS, Windows) — installs the extension and runs
  `gh lab --version` and `gh lab --help`.

Because pull requests are checked before merging, CI is the gate that protects
users from a broken release. `main` is protected: changes land through pull
requests rather than direct pushes.

The **extension** and **platforms** jobs invoke `gh lab` directly, with the
arguments written out in the workflow. Nothing links those to the argument
parser, so a change to the CLI must be made in `.github/workflows/ci.yml` at the
same time: a stale invocation passes the test suite and the linter, and fails
only once it has been pushed.

The **platforms** job is deliberately minimal. Exit codes and usage text are
pure Python and already covered on Linux; what differs across operating systems
is only whether the `gh-lab` shim can resolve its own directory, find an
interpreter, and exec the package, all of which `gh lab --version` exercises.
Students run `gh lab` inside Linux devcontainers, so macOS and Windows get a
proof of life rather than full coverage.

The commands listed in this document should match the checks run by CI.

## Distribution

`gh lab` is a *script* extension: `gh` clones this repository and runs the
`gh-lab` file at its root. Two consequences matter when making changes:

* **`gh extension upgrade lab` is a `git pull` of the default branch.** It does
  not consult tags or GitHub Releases, so every commit merged to `main` reaches
  every user immediately. Merge to `main` only when users should receive the
  change.
* **The runtime must stay dependency-free.** Nothing is installed at extension
  install time; the `gh-lab` shim only puts `src/` on `PYTHONPATH`. Standard
  library only, so keep new packages in the `dev` dependency group.

The `gh-lab` shim must keep mode `100755` in Git, or `gh` cannot execute it.
Check with `git ls-files -s gh-lab`; repair with `git update-index --chmod=+x gh-lab`.

Tag versions with `git tag -a v0.1.0`, keeping the tag in step with
`__version__` in `src/gh_lab/__init__.py` and `version` in `pyproject.toml`.
GitHub Releases are optional, but **never attach assets whose names end in a
platform suffix** such as `linux-amd64` or `darwin-arm64`: `gh` treats those as
the signature of a precompiled binary extension and will stop cloning the
repository, breaking installation.
