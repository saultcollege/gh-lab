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
gh lab admin invites send
```

should have corresponding command implementations such as:

```text
src/gh_lab/
    cli.py
    course_config.py
    commands/
        setup_check/
            command.py
            config.py
            shell.py
        admin_invites/
            command.py
            shell.py
```

A package may own more than one verb where they share their subject matter, as
`admin_invites` owns both `send` and `accept`. The split between `shell.py` and
`command.py` is unchanged by that; `shell.py` simply registers more than one
parser and exposes a handler for each.

The top-level CLI is responsible primarily for:

* registering commands and their argument parsers;
* selecting the appropriate command;
* delegating execution to that command;

Business logic should not be embedded in argument parsing or CLI dispatch code.

Each subcommand is divided into a shell layer (`shell.py`) and a command layer (`command.py`). 

The shell layer owns CLI-specific concerns, including argument parsing, terminal output, and exit codes. In practice `shell.py` exposes `register(subparsers)`, which declares the subcommand and its arguments, and a handler taking the parsed arguments, which calls the command layer, reports its result, and maps it to an exit code. A package owning several verbs exposes one handler per verb.

The command layer implements the operation itself using ordinary Python inputs and structured outputs and must not depend on argparse, presentation concerns, or the shell layer. The command layer should be callable independently of the CLI so that it can be unit tested and potentially reused by other interfaces.

### Shared modules

A command package owns what only it reads. Anything read by more than one command belongs beside `cli.py` instead, so that no command has to import from another command's package.

`course_config.py` is the first of these. The course configuration document describes the course as a whole — who teaches it, and who is enrolled in it — and is read both by `setup-check`, to check repository access, and by the invite commands, to decide who to invite. Parsing it therefore lives at the top level, alongside the `ConfigError` type and the small validation helpers it shares.

The lab configuration (`.lab/config.json`) is read only by `setup-check`, so `commands/setup_check/config.py` keeps it.

Promote a module only when a second command actually needs it. This mirrors the principle below: architecture grows from concrete requirements.

## Command-line grammar

Commands serve one of two audiences, and identify a lab differently as a result.

**Student-facing commands** take the lab as an optional positional argument *after* the subcommand, falling back to the `lab` property of `.lab/config.json`:

```text
gh lab setup-check          # lab comes from .lab/config.json
gh lab setup-check 2        # one repository holding several labs
```

**Faculty-facing commands** operate across many repositories rather than within one, so they select their subject with options rather than a positional, for example `--config-file` and `--org`:

```text
gh lab admin invites send --config-file my-org/course-info/26f.json
gh lab admin invites accept --org my-org
```

### Command groups

Faculty-facing commands are grouped under `admin`, so that what a student runs and what an instructor runs are not interleaved in one list.

A group is a parser with subparsers of its own and no behaviour: naming one alone is a usage error, exactly as a bare `gh lab` is. Groups are registered in `cli.py` rather than by any command package, so that a second group can be added beside an existing one without either package knowing about the other. Dispatch is unaffected by the extra depth — the parser for a verb sets `handler` and `main` calls it, at whatever level the verb sits.

Nesting is worth its cost only where a noun genuinely has several verbs. `setup-check` stays a single top-level command because it is one operation, and wrapping it in a group would add a word to the line students type most often.

This matches the grammar of the GitHub CLI itself, which is uniformly verb-then-identifier: `gh pr view 42`, `gh issue close 17`, `gh run view <run-id>`. There is no `gh pr 42 view`.

Hoisting the lab ahead of the subcommand (`gh lab 2 setup-check`) reads well and has been proposed more than once, but it was tried and rejected. `argparse` binds the first positional argument greedily, so an optional leading positional silently swallows the subcommand of any command that takes its own positional or has a nested group. Supporting it means splitting the lab off `sys.argv` by hand before `argparse` runs, and that cost is not worth the gain.

## External tools

Commands may use Git (`git`) and the GitHub CLI (`gh`) where it provides a straightforward and stable interface.

Interactions with such external should be isolated from core decision-making logic where practical so that behaviour can be tested without requiring direct access. These interactions should be implemented behind adapters in the `adapters` package, which can be mocked or stubbed in tests.

**Reach GitHub through `gh`, not over plain HTTP.** `gh` already carries the authentication the environment provides — from the host in a devcontainer, from the platform in a Codespace — so reading a private resource needs nothing of the user. A direct HTTP request would work only for public data and would need a token supplied from somewhere for anything else. An earlier `http` adapter was removed for this reason when the course configuration moved into a private repository.

## Design principles

Prefer:

* small, focused modules;
* explicit inputs and outputs;
* independently testable logic;
* straightforward Python over unnecessary framework abstractions.

Architecture should grow in response to concrete requirements rather than anticipated future complexity.
