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
        setup-check  Check whether the current lab repository is configured
                     correctly.

    options:
      -h, --help     show this help message and exit
      --version      show program's version number and exit

`gh lab setup-check` is registered but not implemented yet; it reports that and
exits non-zero. `gh lab accept-invites` is planned.

## Troubleshooting

If `gh lab` reports that it cannot find a suitable Python, point it at one
explicitly:

    GH_LAB_PYTHON=/usr/local/bin/python3.12 gh lab --help

## Development

See [docs/development.md](docs/development.md).
