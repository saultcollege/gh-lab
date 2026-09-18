# 003 — Provenance a Codespace can actually check

## Status

TODO

## Why

`setup-check` tells a student their repository was not created from the lab
template when it was. Reproduced against `rmartin-sc/csd217-lab-1`, which GitHub
agrees was generated from `saultcollege-csd217/lab-1-26f`.

The check reads `templateRepository` from `gh repo view`. GitHub does not expose
that link as a string. Schema introspection gives exactly one template field on
`Repository`:

    isTemplate:         Boolean (NON_NULL)
    templateRepository: Repository (OBJECT)

So the link is a *nullable pointer that must be dereferenced*, and reading the
template's name means reading the template repository itself. A viewer who may
not see that repository gets a plain `null` — not an error, because the field is
nullable rather than `Repository!`. Saying anything more would confirm that a
private repository exists, which is the same reasoning behind the 404. REST
behaves identically: `template_repository` is the whole repository object
inlined, `private` and `description` and all.

A Codespace is given a token scoped to the repository it belongs to. The lab
template is private and in another organization, so from inside a student's
Codespace `gh api repos/saultcollege-csd217/lab-1-26f` answers **404** and
`templateRepository` is **null** — confirmed by hand in the failing Codespace.
That is not an edge case: `.devcontainer/devcontainer.json` in the lab template
runs `gh lab setup-check 1` as its `postAttachCommand`, so this is the
environment nearly every student runs the check in, nearly every time.

`gather_facts` turns that null into `template_repo=None`, and `_check_template`
reads `None` as "no template was used" — `repo_view` itself succeeded, so
nothing was recorded in `unavailable` and the skip path is never reached. The
check fails, and the remediation it prints is:

    gh repo create csd217-lab-1 --private --template <template> --clone

A student whose repository is correct is told to build a new one. The note asks
them to see their instructor before deleting anything, but the check is
steering people toward discarding good work on the strength of a field it
cannot read. That, rather than the wrong message, is why this is worth fixing
now.

The token cannot be widened. No scope, header or field makes a repository-scoped
token read a repository it may not see, and `customizations.codespaces.repositories`
may only name repositories in the same account or organization as the codespace
— recorded in plan 002, and the reason the faculty list was published rather
than reached for.

## Decisions

* **`None` means "could not tell", never "no template".** This is the whole
  defect. One value is carrying two meanings that call for opposite outcomes,
  and only one of them is the student's to fix.
* **Fail on a fork, because that much is always readable.** `isFork` is
  `Boolean!` — non-null for every viewer who can see the repository at all, with
  no dependency on the template. Forking the template is a real thing students
  do, and it is the one wrong provenance we can still name with certainty.
* **Still assert the template when it does resolve.** Free signal wherever the
  token is wide enough: an instructor's laptop, or CI with a PAT. Dropping it
  because a Codespace cannot use it would lose a real check in the environments
  that can.
* **One check, not two.** Provenance stays a single line with the id `template`,
  so JSON output stays stable and a student reads one verdict rather than two
  that overlap. A separate "not a fork" check would print a reassuring tick
  about a mistake almost nobody made.
* **A skip that can never resolve must not print remediation advice.** The
  existing skip path assumes something the reader could go and fix. This one is
  permanent and blameless, so counting it as `anything_skipped` would end every
  Codespace attach with a "what to do" block about something nobody can do
  anything about. The check's own reason carries the explanation instead.
* **Accepted narrowing, stated plainly.** Inside a Codespace, a repository made
  by downloading the template as a ZIP and pushing it is now indistinguishable
  from one properly generated. That mistake goes uncaught there. The alternative
  is a check that fails everyone, which buys nothing and costs work.
* **Rejected: inferring provenance from commit shape.** A generated repository
  starts life as one squashed commit, a clone of the template carries its whole
  history. But a student who has committed anything before running the check has
  more than one commit, which is the normal case, and a ZIP-and-push looks
  identical to a generation. A heuristic that fails open on the common path is
  not worth the code.
* **Rejected: publishing the lab template.** It would make `templateRepository`
  resolve for everyone and fix this outright. The faculty list was published for
  exactly this reason in plan 002, but a lab template is coursework, not a
  roster — publishing it hands out the starting code, and in some labs the
  tests, to anyone who looks.

## Tasks

1. [ ] Add `isFork` and `parent` to `REPO_FIELDS`, and carry them on
   `RepoFacts` as `is_fork` and `forked_from`.
2. [ ] Rework `_check_template` to the four outcomes: a fork fails; a resolved
   template that matches passes; a resolved template that differs fails; an
   unresolved template is skipped as unverifiable here.
3. [ ] Word the unverifiable skip so it reads as a limitation of the
   environment and not as something the student has done wrong.
4. [ ] Keep an unverifiable skip out of `anything_skipped`, so it does not draw
   remediation advice it has no remedy for.
5. [ ] Replace the test at `tests/commands/test_setup_check.py:157`, which
   currently asserts the defect — `template_repo=None` is expected to produce
   "not created from a template".
6. [ ] Add tests for a fork, for a template that resolves and differs, and for
   an unverifiable template producing a skip with no advice.
7. [ ] Update the `setup-check` table in `docs/configuration.md`, which lists
   this check as needing only "GitHub", and the paragraph on what "not checked"
   means — it currently names only the CLI and the course configuration.
8. [ ] Check `README.md:78`, which promises the check verifies the repository
   "was created from the lab template", and soften it to match.
9. [ ] Check `.github/workflows/ci.yml` for invocations that need updating, per
   `AGENTS.md`.
10. [ ] Confirm in the failing Codespace that provenance now skips rather than
    fails, and that a fork is still caught.
