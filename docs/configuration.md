# Configuration

`gh lab` is configured by two JSON documents:

* **`.lab/config.json`**, committed in the root of a lab repository and written
  by the lab template. It describes one lab.
* **the course configuration**, held in a private repository owned by the course
  organization. It lists the people on the course — faculty, and optionally
  students — and is shared by every lab in it.

## `.lab/config.json`

```json
{
  "repo-name": "csd110-lab-1",
  "template-repo": "https://github.com/saultcollege-csd110/lab-1-template",
  "course-config": "saultcollege-csd110/course-config/26f.json",
  "branch-pattern": "lab-{lab}",
  "lab": "1"
}
```

| Property | Required | Meaning |
| --- | --- | --- |
| `repo-name` | yes | The name a student's repository must have. |
| `template-repo` | yes | The template the repository must be created from. A `https://github.com/owner/name` URL or an `owner/name` shorthand. |
| `course-config` | yes | Where the course configuration lives. See below. |
| `branch-pattern` | no | The expected branch name, with `{lab}` replaced by the lab. Defaults to `lab-{lab}`. |
| `lab` | no | Which lab this repository is for. See below. |

There is no `course-org` property. The course organization is, by definition,
whoever owns `template-repo`, so it is derived from it rather than stated twice.

### `lab`, and the two lab styles

The `lab` property is what makes one command serve both course styles. It is the
only difference between them.

**One repository per lab.** Each lab has its own template, so the template knows
which lab it is. Set `lab`, and the student runs the command with no arguments:

```console
$ gh lab setup-check
```

**Several labs in one repository.** A single template serves the whole term, so
it cannot know which lab a student is working on. Omit `lab`, and the student
names it:

```console
$ gh lab setup-check 2
```

If `lab` is set and the student also passes one, the command line wins. If
neither is present, the command explains that it needs one.

### `course-config`

Three spellings are accepted, because whoever writes the template is as likely to
paste a link from the browser as to type the short form:

```jsonc
"course-config": "saultcollege-csd110/course-config/26f.json"
"course-config": "saultcollege-csd110/course-config/26f.json@main"
"course-config": "https://github.com/saultcollege-csd110/course-config/blob/main/26f.json"
```

The short form is `owner/repo/path`, where everything after the repository name
is the path to the file. An optional `@ref` pins a branch, tag, or commit;
without it the repository's default branch is used. A ref containing a `/`
cannot be written in the short form — use the URL form for those.

### `branch-pattern`

`{lab}` is substituted with the lab. With the default `lab-{lab}`,
`gh lab setup-check 2` expects a branch named `lab-2`. A course that numbers work
differently can set, say, `week-{lab}` or `assignment-{lab}`.

It lives here rather than in the course configuration deliberately — see
[Why the split is where it is](#why-the-split-is-where-it-is).

## The course configuration

```json
{
  "faculty": [
    { "name": "Bob Bob", "github": "bobber24" }
  ],
  "students": [
    { "name": "Stu Dent", "github": "student" }
  ]
}
```

| Property | Required | Meaning |
| --- | --- | --- |
| `faculty` | yes | Who must be a collaborator on every student repository. May be empty. |
| `students` | no | Who is enrolled in the course. Defaults to empty. |

The file is held in **two** repositories, named by convention:

| Repository | Visibility | Holds |
| --- | --- | --- |
| `<org>/course-info` | public | `faculty` |
| `<org>/course-info-private` | private | `students` |

The path is the same in both, so one delivery of a course is one filename and
several can sit side by side: `config/26f.json`, `config/26w.json`,
`config/27f.json`.

**Nothing ever names both.** `course-config` in `.lab/config.json` and
`--config-file` both point at the *public* file; the private roster is found
beside it by appending `-private` to the repository name. A reference that
already names the private repository is used as-is, so a course that keeps
everyone in one private file still works — see [One file or two](#one-file-or-two).

The faculty list is public so that `setup-check` can read it with whatever
authentication a student's environment already provides. That is what lets a
student open a Codespace and run it with no sign-in at all; see
[Why the split is where it is](#why-the-split-is-where-it-is). Student names
and GitHub handles are not public, which is why they are held separately.

Unrecognised properties are ignored, so a file still carrying a `course-org` or
`branch-pattern` from an earlier version of this tool will not break.

### `faculty`

Each entry is an object. Only `github` is used for checking; `name` is optional
and only makes messages friendlier — `Bob Bob (@bobber24)` instead of
`@bobber24`. Any other properties are ignored, so the same file can carry contact
details used elsewhere.

```json
{ "name": "Bob Bob", "github": "bobber24", "email": "bob@example.com" }
```

An entry without a `github` property is an error, and the message names its
position in the array, because the person who has to fix the file is the one who
wrote it.

### `students`

Each entry has the same shape as a faculty entry: `github` is required, `name` is
optional, and any other property is ignored. An entry without `github` is an
error naming its position, exactly as for `faculty`.

The property itself is optional and defaults to empty, so a course configuration
written before it existed still works.

`setup-check` does not read it. It is read by `gh lab admin invites send`, which
invites everyone named in the file — faculty and students alike — to the course
organization. A course that never runs that command does not need a `students`
array at all.

## One file or two

Both arrangements work, and `gh lab` tells them apart on its own.

**Two files** is the arrangement above and the one to prefer: `faculty` in the
public `course-info`, `students` in the private `course-info-private`. The
private file needs no `faculty` array — if it carries one it is ignored, so a
course can split an existing file simply by copying it and deleting the array
it does not need from each.

**One private file** holding both is what courses had before, and still works.
`setup-check` cannot read it from a Codespace, which is the reason to move, but
nothing breaks. `admin invites send` looks for the `-private` companion, does
not find it, and uses the `students` the file itself carries. It says which
files it read, so a mistyped repository name shows up as a message rather than
as a course with nobody enrolled:

```text
Would invite 13 people to saultcollege-csd217
from saultcollege-csd217/course-info/config/26f.json
and saultcollege-csd217/course-info-private/config/26f.json
```

To migrate, publish `course-info` with the faculty list, move the roster to
`course-info-private`, and re-point `course-config` in each lab template. Repos
already created from an older template keep the reference they were built with,
so leave the old file readable until that cohort is done.

## Why the split is where it is

Only the course roster lives in the course configuration. Everything else is
stated in `.lab/config.json` or derived from it. That is not arbitrary.

`setup-check` has to run in three places, and what its authentication can *see*
differs in each.

* **A devcontainer on the student's own machine** uses the student's own GitHub
  credentials, so it can read a private repository in the course organization.
* **A GitHub Actions workflow** on their pull request **cannot.** The token
  available to a workflow is scoped to the repository it runs in.
* **A Codespace cannot either**, for the same reason: the platform supplies a
  `GITHUB_TOKEN` scoped to the repository the codespace belongs to. This is
  easy to miss, because the student is unmistakably signed in — every check
  that only asks about *their own* repository passes.

Reading another repository would require a GitHub App or a personal access
token stored in the student's own repository, and neither is acceptable for
student-owned repos. Nor can a codespace be granted the access: GitHub's
`customizations.codespaces.repositories` may only name repositories in the same
account or organization as the one the codespace is for, and a lab repository
lives in the student's personal account by design — see the check that it is
not owned by the course organization.

**This is why the faculty list is public.** It is the only thing `setup-check`
needs from outside the student's own repository. Everything else it asks for —
the repository's name, visibility and template, and its collaborator list — is
about the student's own repository, which the Codespace token can read and
write. Publish the faculty list and a Codespace needs no sign-in at all; keep
it private and the faculty check is the one thing a student cannot run without
arranging credentials of their own.

Publishing it is cheap. Who teaches a course is not a secret, and the file
holds nothing else. Who is *enrolled* is a different matter, which is why
`students` lives in `course-info-private` and is never published.

The remedies `setup-check` prints work in a Codespace too. Adding a
collaborator needs write access, which the Codespace token has; only
`gh repo rename`, `gh repo create` and changing visibility need more, and those
are one-time steps a student takes when creating the repository rather than
from inside it.

So anything kept in the *private* file is unavailable to the check when it runs
in Actions or a Codespace. The faculty check is skipped in Actions for a second
reason anyway — listing collaborators needs write access the workflow token
does not have. `students` is read only by faculty-facing commands, which run on
a faculty machine and never in Actions, so keeping it private costs nothing.
Putting `branch-pattern` in either file would have cost the branch check, which
is the one most worth having on a pull request.

`branch-pattern` therefore lives in exactly one place. If the course
configuration could override it, a student would see one expected branch locally
and a different one in CI, which is worse than not being able to change it
centrally.

## What `setup-check` verifies

| Check | Needs |
| --- | --- |
| Repository name matches `repo-name` | GitHub |
| Current branch matches `branch-pattern` | git, or the workflow environment |
| Repository was generated from `template-repo` | GitHub |
| Repository is private | GitHub |
| Every faculty member is a collaborator | GitHub, and the course configuration |
| Repository is not owned by the course organization | GitHub |

A check that cannot run — because the GitHub CLI cannot reach GitHub, or
because the token it is using cannot read the course configuration — is
reported as **not checked** rather than as a failure, and does not fail the
command. The summary at the end names which of those it was, and suggests
signing in only where signing in is actually possible.

### In GitHub Actions

`setup-check` works inside a workflow, with two differences:

* The branch is read from `GITHUB_HEAD_REF` (on pull requests) or
  `GITHUB_REF_NAME` (on pushes), because the checkout is not on a branch.
* **The faculty check is skipped entirely**, and the course configuration is not
  fetched. Faculty discover a missing invitation by being unable to open the
  repository when they come to review it.

Every other check behaves exactly as it does locally. Failures are also emitted
as workflow annotations, so they appear inline on the student's pull request.

## A caution on trust

Both documents are reachable from the student's own repository:
`.lab/config.json` is a file they can edit, and it names where the course
configuration is fetched from. A student can therefore make `setup-check` pass by
editing them.

This is fine, because `setup-check` is a self-service tool: its job is to help a
student find their own mistakes before submitting. **A green result is not
evidence of anything**, and it should not be used as a grading gate. Verification
that needs to be trustworthy has to run somewhere the student cannot edit.
