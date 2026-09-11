# AGENTS.md

## Project

This repository contains `gh lab`, a GitHub CLI extension for managing and validating programming lab repositories.

The project is written in Python and managed with `uv`.

## Repository documentation

Before making significant changes, consult the relevant documentation:

* `README.md` — project overview and user-facing usage
* `docs/architecture.md` — architecture and design conventions
* `docs/development.md` — development environment, commands, testing, and tooling

Follow the architecture documented in `docs/architecture.md`. Do not introduce a substantially different architectural pattern without explaining why.

## Development environment

The repository is intended to be developed inside the included VS Code
devcontainer.

Agents should assume commands are being run from within the devcontainer
unless explicitly told otherwise.

Do not modify the devcontainer to provide Docker daemon or host Docker socket
access unless a task specifically requires Docker.

## Working practices

* Inspect the existing implementation before making changes.
* Keep changes scoped to the requested task.
* Do not make unrelated refactors unless they are necessary for the task.
* Prefer simple solutions over unnecessary abstractions.
* Add or update tests when behaviour changes.
* Do not add production dependencies unless they are necessary.
* Build core functionality around pure, side-effect-free functions that return plain data; where side-effects are required, keep effectful functions as simple as possible and delegate logic and calculation to pure functions.

## Validation

Before considering implementation work complete:

1. Run the project's tests.
2. Run the configured linting and formatting checks.
3. Review the resulting diff for unrelated changes.
4. Report any tests or checks that could not be run or did not pass.

Exact commands are documented in `docs/development.md`.
