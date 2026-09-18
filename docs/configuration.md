# Configuration

`gh lab` is configured by two JSON documents:

* **`.lab/config.json`**, committed in the root of a lab repository and written
  by the lab template. It describes one lab.
* **the course configuration**, a pair of files owned by the course
  organization — a public one naming the faculty and a private one naming the
  students. It is shared by every lab in the course.

## `.lab/config.json`

```json
{
  "repo-name": "csd110-lab-1",
  "course-config": "saultcollege-csd110/course-info/config/26f.json",
  "branch-pattern": "lab-{lab}",
  "lab": "1"
}
```

| Property | Required | Meaning |
| --- | --- | --- |
| `repo-name` | yes | The name a student's repository must have. |
| `course-config` | yes | Where the course configuration lives. See below. |
| `branch-pattern` | no | The expected branch name, with `{lab}` replaced by the lab. Defaults to `lab-{lab}`. |
| `lab` | no | Which lab this repository is for. See below. |

There is no `course-org` property. The course organization is, by definition,
whoever owns `course-config`, so it is derived from it rather than stated twice.

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
"course-config": "saultcollege-csd110/course-info/config/26f.json"
"course-config": "saultcollege-csd110/course-info/config/26f.json@main"
"course-config": "https://github.com/saultcollege-csd110/course-info/blob/main/config/26f.json"
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

Two files, in two repositories named by convention. Public information goes in
the public one; students and anything else private go in the private one.

| Repository | Visibility | Holds |
| --- | --- | --- |
| `<org>/course-info` | public | `faculty` |
| `<org>/course-info-private` | private | `students` |

`<org>/course-info`:

```json
{
  "faculty": [
    { "name": "Bob Bob", "github": "bobber24" }
  ]
}
```

`<org>/course-info-private`:

```json
{
  "students": [
    { "name": "Stu Dent", "github": "student" }
  ]
}
```

| Property | In | Required | Meaning |
| --- | --- | --- | --- |
| `faculty` | public | yes | Who must be a collaborator on every student repository. May be empty. |
| `students` | private | no | Who is enrolled in the course. Defaults to empty. |

**Commands name only the public file.** `course-config` in `.lab/config.json`
and `--config-file` both point at it; the private file is assumed to be the
same path in a repository of the same name with `-private` appended. Nothing
ever names both.

The path is the same in both repositories, so one delivery of a course is one
filename and several sit side by side:

```text
course-info/config/26f.json          course-info-private/config/26f.json
course-info/config/26w.json          course-info-private/config/26w.json
course-info/config/27f.json          course-info-private/config/27f.json
```

The faculty list is public so that `setup-check` can read it with whatever
authentication a student's environment already provides — which is what lets a
student open a Codespace and run it without signing in to anything. Student
names and GitHub handles are not public, which is why they are held apart.

Both files are required. Listing `students` in the public file is an error
rather than an oversight to ignore, because it means the roster has been
published.

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

The array itself is optional and defaults to empty, so a course can be set up
before anyone has enrolled.

`setup-check` does not read it. It is read by `gh lab admin invites send`, which
invites everyone named in both files — faculty and students alike — to the
course organization, and names both files as it goes:

```text
Would invite 13 people to saultcollege-csd217
from saultcollege-csd217/course-info/config/26f.json
and saultcollege-csd217/course-info-private/config/26f.json
```

## Why the split is where it is

Everything `setup-check` needs about the lab itself is stated in
`.lab/config.json` rather than in the course configuration, because what a
student's authentication can *see* varies by where the check runs. A
devcontainer on their own machine uses their own credentials; a GitHub Actions
workflow and a Codespace are both given a token scoped to the one repository
they run in, so neither can read a private repository in the course
organization.

That is also why the faculty list is public: it is the only thing `setup-check`
needs from outside the student's own repository, so publishing it removes the
last reason a student would have to sign in to anything.

`branch-pattern` therefore lives in exactly one place. If the course
configuration could override it, a student would see one expected branch locally
and a different one in CI, which is worse than not being able to change it
centrally.

## What `setup-check` verifies

| Check | Needs |
| --- | --- |
| Repository name matches `repo-name` | GitHub |
| Current branch matches `branch-pattern` | git, or the workflow environment |
| Repository is not a fork | GitHub |
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
