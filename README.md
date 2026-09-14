# gh-lab

A GitHub CLI extension for managing programming lab repositories.

## Status

Early development. The extension installs and runs, but `setup-check` is not
implemented yet.

## Requirements

* [GitHub CLI](https://cli.github.com/) (`gh`)
* Python 3.11 or newer, available as `python3`
* Git

On Windows, `gh` runs script extensions using the Bash that ships with
[Git for Windows](https://gitforwindows.org/).

## Install

    gh extension install saultcollege/gh-lab

Then:

    gh lab --help

## Upgrade

Check whether an upgrade is available:

    gh extension upgrade lab --dry-run

Apply it:

    gh extension upgrade lab

`gh` also checks for extension updates on its own and prints a notice at most
once a day. Set `GH_NO_EXTENSION_UPDATE_NOTIFIER=1` to suppress that.

To install a specific version instead of tracking the latest:

    gh extension install saultcollege/gh-lab --pin v0.1.0

## Uninstall

    gh extension remove lab

## Usage

    usage: gh lab [-h] [--version] <command> ...

    GitHub lab repository management tools.

    positional arguments:
      <command>
        setup-check  Check that your lab repository is set up correctly.

    options:
      -h, --help     show this help message and exit
      --version      show program's version number and exit

`gh lab accept-invites` is planned.

### `gh lab setup-check`

Checks that your lab repository is set up correctly, and explains how to fix
anything that is not. Run it from inside your lab repository:

    gh lab setup-check

If one repository holds several labs, say which one you are working on:

    gh lab setup-check 2

It checks that the repository is named correctly, is private, was created from
the lab template, is owned by you rather than the course organization, that your
faculty are collaborators, and that you are on the right branch.

Anything it cannot check — because you are not signed in to the GitHub CLI, for
example — is reported as *not checked* rather than as a failure.

Options:

    --format {text,json}     Output format (default: text)
    --color {auto,never,always}

The repository it checks against is described by `.lab/config.json`, written by
your lab template. See [docs/configuration.md](docs/configuration.md) if you are
setting up a course.

It also runs in GitHub Actions, where failures appear as annotations on your
pull request. Note that a passing result is a convenience, not proof of a correct
submission — see the caution in the configuration docs.

## Troubleshooting

If `gh lab` reports that it cannot find a suitable Python, point it at one
explicitly:

    GH_LAB_PYTHON=/usr/local/bin/python3.12 gh lab --help

## Development

See [docs/development.md](docs/development.md).
