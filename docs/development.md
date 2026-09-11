# Development

## Requirements

* Python
* `uv`
* Git
* GitHub CLI (`gh`)

## Setup

Project setup instructions will be added once the Python project is initialized.

## Development environment

The recommended development environment is the VS Code devcontainer defined in
`.devcontainer/devcontainer.json`.

Opening the repository in the devcontainer provides the required Python and
development tooling without requiring them to be installed on the host.

After the container is created, project dependencies are synchronized with:

    uv sync

## Running

Commands for running `gh lab` during development will be documented here.

## Tests

The project will use an automated test suite.

The canonical test command will be documented here once the testing framework is configured.

## Code quality

Linting, formatting, and other automated checks will be documented here as they are added.

The commands listed in this document should match the checks run by CI.
