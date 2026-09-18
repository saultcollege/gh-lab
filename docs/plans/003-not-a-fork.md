# 003 — Check that the repository is not a fork

## Status

ACTIVE

## Why

`setup-check` tells a student their repository was not created from the lab
template when it was. Reproduced against `rmartin-sc/csd217-lab-1`, which GitHub
agrees was generated from `saultcollege-csd217/lab-1-26f`.

The cause is that GitHub does not expose the template as a string. Schema
introspection gives one template field on `Repository`:

    isTemplate:         Boolean (NON_NULL)
    templateRepository: Repository (OBJECT)

The link is a *nullable pointer that must be dereferenced*, so reading the
template's name means reading the template repository itself. A viewer who may
not see it gets a plain `null` rather than an error, because the field is
nullable rather than `Repository!`. A Codespace token is scoped to the
repository it belongs to, and the lab template is private in another
organization, so from inside a student's Codespace `gh api
repos/saultcollege-csd217/lab-1-26f` answers 404 and the field is null —
confirmed by hand in the failing Codespace. `.devcontainer/devcontainer.json`
runs `gh lab setup-check` on attach, so that is the environment nearly every
student is in, nearly every time.

`gather_facts` turns the null into `template_repo=None` and `_check_template`
reads it as "no template was used", because `repo_view` itself succeeded and
nothing was recorded in `unavailable`. The check fails and prints `gh repo
create --template`, so a student whose repository is correct is told to build a
new one.

The first plan for this repaired that reading. This one removes the check
instead, because measuring what it protects against showed there is very little
left:

* **Forking is the only variant that causes real harm**, and it is already
  impossible. Private forks inherit the upstream's team permissions — GitHub's
  documentation says so outright — so with `default_repository_permission: read`
  a forked lab repository could be readable across the cohort while the
  `private` check still passes, because the repository genuinely is private.
  Pull requests from a fork also default their base to the upstream, which would
  aim a student's submission at the course template. Both are prevented at
  source: the organization sets `members_can_fork_private_repositories: false`
  and the template sets `allow_forking: false`.
* **Cloning differs only in history.** A generated repository is squashed to one
  commit and a clone carries everything — measured: `lab-1-26f` has 2 commits,
  the generated `csd217-lab-1` has 1. That matters only if a template's history
  ever holds something students should not have, which is a question about how
  templates are built rather than something a setup check can police.
* **Downloading the ZIP and pushing is indistinguishable from generating**, and
  harmless.
* **The other checks already cover the failure modes that matter** — name,
  owner, visibility, faculty access and branch. Beyond those, provenance caught
  only using the wrong lab's template or inventing the repository from nothing,
  both of which are immediately obvious from the files in front of the student.

So the check that earns its place is the one thing that is both harmful and
always readable: `isFork` is `Boolean!`, non-null for anyone who can see the
repository at all, and needs access to no other repository. It is kept not for
this organization, where forking is off, but because `gh lab` serves other
courses whose organizations may not be locked down.

## Decisions

* **Provenance checking goes, `template-repo` with it.** Repairing it would keep
  a check that cannot run where students work, is the only one producing false
  failures, and guards against something already prevented.
* **`course_org` moves to the owner of `course-config`.** It is derived from
  `template-repo` today, so dropping that field would take the `not-course-org`
  check with it. The course configuration reference is required, names the
  course organization just as directly, and yields the same value in both the
  real configuration and the test fixture.
* **`template-repo` is no longer read, not rejected.** `parse_lab_config` reads
  named keys, so a `.lab/config.json` that still carries it keeps parsing and no
  student has to edit a file. It simply stops meaning anything.
* **`isFork` alone, not `parent`.** Naming what a repository was forked from
  would be friendlier, but `parent` is a nullable `Repository` — the same trap
  that caused this bug, and null for exactly the private upstreams worth naming.
  A check that is certain is worth more than a message that is fuller.
* **The fork check offers no command.** There is no way to leave a fork network
  from the CLI, so the remediation is to make a fresh repository from the lab
  template and copy the work across, which needs the instructor. Inventing a
  command that half-works would be worse than a clear note.
* **No change to the advice machinery.** The fork check can only be skipped when
  `repo_view` itself failed, which already records `unavailable["repo"]` and is
  already covered. Plan 003's earlier draft needed a new advice path; this one
  needs none.
* **Documentation describes the tool as it is.** No deprecation note, no
  migration section, no mention that a template check ever existed. This plan is
  the record of the change; the docs are not.
* **Rejected: keeping template matching where it happens to resolve.** It would
  pass on an instructor's laptop and skip in every Codespace, so the one
  environment that could act on it is the one that never sees it — and it would
  keep `template-repo` alive to serve a check that nearly never runs.

## Tasks

1. [+] Derive `LabConfig.course_org` from the `course-config` owner, replacing
   the `template_repo` derivation.
2. [ ] Drop `template_repo` from `LabConfig` and stop reading `template-repo` in
   `parse_lab_config`.
3. [+] Swap `templateRepository` for `isFork` in `REPO_FIELDS`, and
   `template_repo` for `is_fork` on `RepoFacts` and in `gather_facts`.
4. [+] Replace `_check_template` with `_check_fork`: pass when the repository is
   not a fork, fail when it is, skip when the repository could not be read.
5. [ ] Reword the `not-course-org` remediation and its skip reason, both of
   which name `template-repo` today.
6. [ ] Remove `normalise_repo_ref` if tasks 1–5 leave it unused, checking the
   invite commands and the tests before deleting it.
7. [+] Update `tests/commands/test_setup_check.py`: drop the template cases,
   including the one at line 157 that asserts the defect.
8. [ ] Update `tests/commands/test_setup_check_config.py`: drop `template-repo`
   from the fixture and the required-field list, and re-point the two
   `course_org` tests at the course configuration owner.
9. [+] Add tests for a fork failing, a non-fork passing, and an unreadable
   repository skipping.
10. [ ] Update `docs/configuration.md` — the field table, the example, the
    course-organization derivation, and the `setup-check` table — and the
    sentence in `README.md` listing what is checked.
11. [ ] Check `.github/workflows/ci.yml` per `AGENTS.md`. It greps `--help`
    output for `setup-check` and never invokes the check, so this is expected to
    need nothing.
12. [ ] Run the tests, `ruff check` and `ruff format --check`.
