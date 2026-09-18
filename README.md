# gh-lab

A GitHub CLI extension for managing programming lab repositories.

## Status

Early development. `gh lab setup-check` is implemented for students, and
`gh lab admin invites` for faculty.

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
        admin        Faculty-facing course administration.

    options:
      -h, --help     show this help message and exit
      --version      show program's version number and exit

`setup-check` is for students, working in one repository. The commands under
`admin` are for faculty, working across a whole course.

### `gh lab setup-check`

Checks that your lab repository is set up correctly, and explains how to fix
anything that is not. Run it from inside your lab repository:

    gh lab setup-check

If one repository holds several labs, say which one you are working on:

    gh lab setup-check 2

It checks that the repository is named correctly, is private, was created from
the lab template, is owned by you rather than the course organization, that your
faculty are collaborators, and that you are on the right branch.

Anything it cannot check — because the GitHub CLI cannot reach GitHub, or
because the token it is using cannot read your course's configuration — is
reported as *not checked* rather than as a failure, and the summary explains
which.

It needs no sign-in beyond what your environment already provides. In a
Codespace that means every check runs as soon as you open it, with nothing to
set up, provided your course publishes its faculty list — see
[docs/configuration.md](docs/configuration.md).

Options:

    --format {text,json}     Output format (default: text)
    --color {auto,never,always}

The repository it checks against is described by `.lab/config.json`, written by
your lab template. See [docs/configuration.md](docs/configuration.md) if you are
setting up a course.

It also runs in GitHub Actions, where failures appear as annotations on your
pull request. Note that a passing result is a convenience, not proof of a correct
submission — see the caution in the configuration docs.

### `gh lab admin invites`

Faculty-facing. Manages the GitHub invitations a course depends on: invitations
into the course organization, and the invitations students send for their own
repositories.

    usage: gh lab admin invites [-h] <verb> ...

    positional arguments:
      <verb>
        send      Invite a course's students and faculty to the course
                  organization.
        accept    Review and accept pending repository invitations.

    options:
      -h, --help  show this help message and exit

#### `send`

Invites everyone listed in a course configuration — faculty and students alike —
to the organization that owns it:

    gh lab admin invites send --config-file my-org/course-info/config/26f.json

The organization is not a separate argument. It is, by definition, the owner of
the repository the course configuration lives in, so the reference above invites
into `my-org`. See [docs/configuration.md](docs/configuration.md) for the file's
format.

Check before sending anything:

    gh lab admin invites send --config-file my-org/course-info/config/26f.json --dry-run

`--dry-run` resolves the configuration and prints the organization and the full
roster without contacting anyone.

You are never invited to your own course. Faculty list themselves in the course
configuration, and inviting yourself would ask GitHub to set your own membership
to *member* — at best doing nothing, at worst removing the ownership that let
you run the command. Your entry is named in the output so the omission is
visible rather than looking like a misread configuration.

Re-running is safe. Someone already in the organization is reported as such
rather than invited again, and one bad entry does not stop the rest of the
roster, so a typo can be fixed and the command run again.

Only an owner of the organization can invite people to it. If you are an
administrator of its repositories but not an owner of the organization itself,
this will report a 403.

Options:

    --config-file REF        Required. owner/repo/path, owner/repo/path@ref, or
                             a link to the file on GitHub
    --dry-run                Show who would be invited, without inviting anyone

#### `accept`

Students create their own lab repositories, so each one invites you as a
collaborator. This reviews those invitations one at a time and acts on them
together:

    gh lab admin invites accept

For each invitation you can accept, decline, or skip it; pressing Return keeps
whatever is already chosen, which is *skip* the first time through. **Nothing is
accepted or declined until you have seen the whole list and confirmed it.** At
the confirmation step you can go back and edit your choices, or cancel and
change nothing.

Reviewing needs a terminal. Run without one — in a pipe, or in CI — and it lists
what is pending and exits without changing anything.

Every pending invitation is listed. Lab repositories belong to the students who
create them, not to the course organization, so there is nothing course-shaped
to filter on.

## Troubleshooting

If `gh lab` reports that it cannot find a suitable Python, point it at one
explicitly:

    GH_LAB_PYTHON=/usr/local/bin/python3.12 gh lab --help

## Development

See [docs/development.md](docs/development.md).
