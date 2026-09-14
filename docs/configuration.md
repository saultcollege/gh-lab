# Configuration

`gh lab` is configured by two JSON documents:

* **`.lab/config.json`**, committed in the root of a lab repository and written
  by the lab template. It describes one lab.
* **the course configuration**, served from a URL that `.lab/config.json` names.
  It describes the course and is shared by every lab in it.

Splitting them this way means details that change during a term — who is
teaching, what the branch convention is — live in one place the course controls,
rather than being baked into every template.

## `.lab/config.json`

```json
{
  "repo-name": "csd110-lab-1",
  "template-repo": "https://github.com/saultcollege-csd110/lab-1-template",
  "course-config-url": "https://saultcollege-csd110.github.io/course-config.json",
  "lab": "1"
}
```

| Property | Required | Meaning |
| --- | --- | --- |
| `repo-name` | yes | The name a student's repository must have. |
| `template-repo` | yes | The template the repository must be created from. A `https://github.com/owner/name` URL or an `owner/name` shorthand. |
| `course-config-url` | yes | Where to fetch the course configuration. Must be `http` or `https`. |
| `lab` | no | Which lab this repository is for. See below. |

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

## Course configuration

```json
{
  "course-org": "saultcollege-csd110",
  "branch-pattern": "lab-{lab}",
  "faculty": [
    { "name": "Bob Bob", "github": "bobber24" }
  ]
}
```

| Property | Required | Meaning |
| --- | --- | --- |
| `course-org` | yes | The GitHub organization that owns the lab templates. Student repositories must **not** be owned by it. |
| `faculty` | yes | Who must be a collaborator on every student repository. May be empty. |
| `branch-pattern` | no | The expected branch name, with `{lab}` replaced by the lab. Defaults to `lab-{lab}`. |

### `faculty`

Each entry is an object. Only `github` is used for checking; `name` is optional
and only makes messages friendlier — `Bob Bob (@bobber24)` instead of
`@bobber24`. Any other properties are ignored, so the same file can carry
contact details used elsewhere.

```json
{ "name": "Bob Bob", "github": "bobber24", "email": "bob@example.com" }
```

An entry without a `github` property is an error, and the message names its
position in the array, because the person who has to fix the file is the one who
wrote it.

### `branch-pattern`

`{lab}` is substituted with the lab. With the default `lab-{lab}`,
`gh lab setup-check 2` expects a branch named `lab-2`. A course that numbers work
differently can set, say, `week-{lab}` or `assignment-{lab}` without needing a
new release of `gh-lab`.

## What `setup-check` verifies

| Check | Source |
| --- | --- |
| Repository name matches `repo-name` | GitHub |
| Current branch matches `branch-pattern` | git, or the workflow environment |
| Repository was generated from `template-repo` | GitHub |
| Repository is private | GitHub |
| Every faculty member is a collaborator | GitHub |
| Repository is not owned by `course-org` | GitHub |

A check that cannot run — because the student is not signed in to the GitHub
CLI, or the course configuration is unreachable — is reported as **not checked**
rather than as a failure, and does not fail the command.

### In GitHub Actions

`setup-check` works inside a workflow, with two differences:

* The branch is read from `GITHUB_HEAD_REF` (on pull requests) or
  `GITHUB_REF_NAME` (on pushes), because the checkout is not on a branch.
* **The faculty check is skipped entirely.** The token available to a workflow
  cannot list collaborators. Faculty discover a missing invitation by being
  unable to open the repository when they come to review it.

Failures are also emitted as workflow annotations, so they appear inline on the
student's pull request.

## A caution on trust

Both documents are reachable from the student's own repository: `.lab/config.json`
is a file they can edit, and it names the URL the course configuration is fetched
from. A student can therefore make `setup-check` pass by editing them.

This is fine, because `setup-check` is a self-service tool: its job is to help a
student find their own mistakes before submitting. **A green result is not
evidence of anything**, and it should not be used as a grading gate. Verification
that needs to be trustworthy has to run somewhere the student cannot edit.
