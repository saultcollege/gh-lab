# Architecture

## Overview

`gh lab` is a GitHub CLI extension written in Python.

The application is organized so that individual operations can be implemented, tested, and reasoned about independently of the command-line interface.

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
        setup_check.py
        accept_invites.py
```

The top-level CLI is responsible primarily for:

* parsing command-line arguments;
* selecting the appropriate command;
* passing inputs to that command;
* rendering command results;
* choosing an appropriate process exit status.

Business logic should not be embedded in argument parsing or CLI dispatch code.

Command implementations should be callable independently of the CLI so that they can be unit tested and potentially reused by other interfaces.

## External tools

GitHub operations may use Git (`git`) and the GitHub CLI (`gh`) where it provides a straightforward and stable interface.

Interactions with external systems should be isolated from core decision-making logic where practical so that behaviour can be tested without requiring live Git or GitHub access.

## Design principles

Prefer:

* small, focused modules;
* explicit inputs and outputs;
* independently testable logic;
* straightforward Python over unnecessary framework abstractions.

Architecture should grow in response to concrete requirements rather than anticipated future complexity.
