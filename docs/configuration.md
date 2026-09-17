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

The file may live anywhere in a repository the students can read; point
`course-config` at it. A private repository in the course organization works,
provided students are members of that organization.

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

## Why the split is where it is

Only the course roster lives in the course configuration. Everything else is
stated in `.lab/config.json` or derived from it. That is not arbitrary.

`setup-check` has to run in two places: a student's devcontainer or Codespace,
and a GitHub Actions workflow on their pull request. In the devcontainer it uses
the student's existing GitHub authentication, so it can read a private repository
in the course organization. **A workflow cannot.** The token available to a
workflow is scoped to the repository it runs in; reading another repository would
require a GitHub App or a personal access token stored in the student's own
repository, and neither is acceptable for student-owned repos.

So anything kept in the course configuration is unavailable to the check when it
runs in Actions. The faculty check is already skipped there for a separate reason
— listing collaborators needs write access the workflow token does not have — so
putting the faculty list there costs nothing. `students` is read only by
faculty-facing commands, which run on a faculty machine and never in Actions, so
it costs nothing either. Putting `branch-pattern` there would have cost the
branch check, which is the one most worth having on a pull request.

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

A check that cannot run — because the student is not signed in to the GitHub CLI,
or the course configuration is unreachable — is reported as **not checked**
rather than as a failure, and does not fail the command.

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
