# Development

## Requirements

* Python
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

    uv run gh-lab

## Test

    uv run pytest

## Lint

    uv run ruff check .

## Format

    uv run format --check .

The commands listed in this document should match the checks run by CI.
