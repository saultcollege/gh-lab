# Architecture

## Overview

`gh lab` is a GitHub CLI extension written in Python.

The application is organized so that individual operations can be implemented, tested, and reasoned about independently of the command-line interface.

## Extension entry point

`gh` runs a script extension by executing a file at the repository root whose name matches the repository (`gh-lab`). A single invocation flows through:

```text
gh lab <args>
    gh-lab                      bash shim: interpreter discovery, PYTHONPATH=src
    python -m gh_lab            src/gh_lab/__main__.py
    gh_lab.cli.main             argument parsing and dispatch
    commands/<name>/shell.py    output and exit code
    commands/<name>/command.py  the operation itself
```

The `gh-lab` shim is the only shell script in the project. It must stay free of application logic: its sole responsibility is to locate a supported Python interpreter and hand off to the package.

Because `gh` installs a script extension by cloning the repository, **nothing is installed at extension install time**. The shim simply adds `src/` to `PYTHONPATH`. The runtime must therefore depend only on the Python standard library; development tooling belongs in the `dev` dependency group.

## Commands

Each `gh lab` subcommand should be implemented as an effectively standalone Python component.

For example:

```text
gh lab setup-check
gh lab accept-invites
```

should have corresponding command implementations such as:

```text
src/gh_lab/
    cli.py
    commands/
        setup_check/
            command.py
            shell.py
        accept_invites/
            command.py
            shell.py
```

The top-level CLI is responsible primarily for:

* registering commands and their argument parsers;
* selecting the appropriate command;
* delegating execution to that command;

Business logic should not be embedded in argument parsing or CLI dispatch code.

Each subcommand is divided into a shell layer (`shell.py`) and a command layer (`command.py`). 

The shell layer owns CLI-specific concerns, including argument parsing, terminal output, and exit codes. In practice `shell.py` exposes `register(subparsers)`, which declares the subcommand and its arguments, and `handle(args)`, which calls the command layer, reports its result, and maps it to an exit code.

The command layer implements the operation itself using ordinary Python inputs and structured outputs and must not depend on argparse, presentation concerns, or the shell layer. The command layer should be callable independently of the CLI so that it can be unit tested and potentially reused by other interfaces.

## Command-line grammar

Commands serve one of two audiences, and identify a lab differently as a result.

**Student-facing commands** take the lab as an optional positional argument *after* the subcommand, falling back to the `lab` property of `.lab/config.json`:

```text
gh lab setup-check          # lab comes from .lab/config.json
gh lab setup-check 2        # one repository holding several labs
```

**Faculty-facing commands** operate across many repositories rather than within one, so they select their subject with options rather than a positional, for example `--lab` and `--org`.

This matches the grammar of the GitHub CLI itself, which is uniformly verb-then-identifier: `gh pr view 42`, `gh issue close 17`, `gh run view <run-id>`. There is no `gh pr 42 view`.

Hoisting the lab ahead of the subcommand (`gh lab 2 setup-check`) reads well and has been proposed more than once, but it was tried and rejected. `argparse` binds the first positional argument greedily, so an optional leading positional silently swallows the subcommand of any command that takes its own positional or has a nested group. Supporting it means splitting the lab off `sys.argv` by hand before `argparse` runs, and that cost is not worth the gain.

## External tools

Commands may use Curl (`curl`) Git (`git`) and the GitHub CLI (`gh`) where it provides a straightforward and stable interface.

Interactions with such external should be isolated from core decision-making logic where practical so that behaviour can be tested without requiring direct access. These interactions should be implemented behind adapters in the `adapters` package, which can be mocked or stubbed in tests.

## Design principles

Prefer:

* small, focused modules;
* explicit inputs and outputs;
* independently testable logic;
* straightforward Python over unnecessary framework abstractions.

Architecture should grow in response to concrete requirements rather than anticipated future complexity.
