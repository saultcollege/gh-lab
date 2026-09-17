# 002 — A public faculty list, so a Codespace needs no sign-in

## Status

DONE

## Why

A student should be able to open a Codespace on their lab repository, run
`gh lab setup-check`, and get a real answer with no sign-in of their own.

They could not. `setup-check` makes three GitHub requests, and only one reaches
outside the student's own repository: the read of the course configuration, for
the faculty list. A Codespace is given a token scoped to the repository it
belongs to, so that read failed, the faculty check was skipped, and the command
advised `gh auth login` — which refuses to run while `GITHUB_TOKEN` is set.
Plan 001's successor commit fixed the advice; this plan removes the cause.

The token cannot be widened. GitHub's `customizations.codespaces.repositories`
may only name repositories in the same account or organization as the one the
codespace is for, and a lab repository lives in the student's personal account
by design.

So the fix is to need less: publish the faculty list, which is not secret, and
keep the student roster — which is — in a separate private repository.

## Decisions

* **Two repositories, named by convention**: `<org>/course-info` is public and
  holds `faculty`; `<org>/course-info-private` is private and holds `students`.
  The path is identical in both, so several deliveries of a course live side by
  side as `config/26f.json`, `config/26w.json`, and so on.
* **One reference, never two.** `course-config` and `--config-file` name the
  public file only; the private one is derived by appending `-private`. A
  second setting would be a second thing to get wrong, and would have to be
  threaded through `.lab/config.json`, which students can edit.
* **The private file is optional.** A course keeping everyone in one private
  file behaves exactly as before. This is what makes the change safe to land
  before any course has migrated.
* **A missing roster is reported, not swallowed**, so that a mistyped
  repository name does not read as a course with nobody enrolled.
* **Rejected: inlining the faculty list into `.lab/config.json`.** It needs
  nothing public and no network at all, and would make the faculty check work
  in Actions too. But the list would be fixed when the template was issued, so
  a mid-term faculty change would leave every existing student repository
  stale. Kept as the fallback if a Codespace token turns out not to be able to
  read public repositories at all.

## Tasks

1. [+] Add `private_counterpart` and `PRIVATE_REPO_SUFFIX` to `course_config`.
2. [+] Add `parse_roster`, so a students-only file need not carry `faculty`.
3. [+] Read and merge the private roster in `admin invites send`, tolerating
   its absence, and record which files were read.
4. [+] Name both files in the send report, and say when the roster was missed.
5. [+] Correct the wording that assumed the configuration is always private.
6. [+] Document the arrangement, the convention, and how to migrate.
7. [+] Confirm in a real Codespace that a repo-scoped token can read a public
   repository. It can — checked with `gh api` against a public repository from
   inside a codespace, which is what the whole arrangement rests on. GitHub's
   documentation does not say either way, so this is worth re-checking if the
   faculty check ever starts being skipped in a Codespace again.
8. [+] Publish `course-info`, move the roster to `course-info-private`.
9. [ ] Re-point `course-config` in each lab template at the public file. Until
   a template is re-pointed, repositories created from it keep reading the old
   reference, so leave that file readable for the cohort already using it.
