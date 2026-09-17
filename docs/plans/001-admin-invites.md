Status: Active

# Invite management commands

Create faculty-facing subcommands to manage GitHub invites for courses: sending course org invites to students and faculty, and accepting repository invites from students.

## Assumption

Course config files have (at least) the following JSON schema:

```json
{
    "course-code": "csd217",
    "term": "26f",
    "faculty": [
        {
            "name": "Pro Fessor",
            "email": "pro.fessor@school.com",
            "github": "prof"
        },
        ...
    ],
    "students": [
        { "name": "Stu Dent", "github": "student" },
        ...
    ]
}
```

`students` is optional and defaults to empty so that existing course configs continue to parse. `docs/configuration.md` already states that unrecognised properties are ignored, so this schema extension is compatible in both directions: an old config works with the new code, and a config carrying `students` works with the currently released `setup-check`.

Each student entry follows the same `{ name, github }` shape as a faculty entry. `github` is required; `name` is optional. Validation errors name the array index, as `faculty[<index>]` already does.

## Decisions

### Command grammar: nested

The grammar is `gh lab admin invites <verb>`.

`README.md` and `docs/architecture.md` currently document a flat `gh lab accept-invites`, and architecture.md uses `accept_invites/` as its worked example of a second command's directory layout. Those documents are out of date; the nested grouping is the cleaner design and the docs are to be updated to match. This extends the single-level `register(subparsers)` convention in `cli.py` to a nested subparser tree, which is an architectural addition and must be documented in `docs/architecture.md` rather than left implicit.

### Target organization: derived from the config file

`send` invites into the organization that owns the `--config-file` reference. For `--config-file saultcollege-csd217/course-info/config/26f.json` the org is `saultcollege-csd217`. There is no `--org` argument.

`--config-file` is required, and accepts the three spellings that `parse_course_config_ref` already supports: `owner/repo/path`, `owner/repo/path@ref`, and a browser blob/raw URL.

### Already-invited users: use an idempotent endpoint

Use `PUT /orgs/{org}/memberships/{username}` with `role=member`. It is idempotent and reports state `pending` for a newly created invitation or `active` for someone who is already a member, so a re-run is safe and the response distinguishes the two outcomes for reporting.

`POST /orgs/{org}/invitations` is *not* suitable: it fails when the user has already been invited. Confirm the exact response shape against the current GitHub API documentation before building against it.

### Safety: `--dry-run`

`send` supports `--dry-run`, which resolves the config, prints the target org and the full roster it would invite, and exits without calling GitHub. A normal invocation proceeds without an interactive confirmation prompt, so the command stays scriptable.

### `accept` interaction: stdlib prompts, no TUI

A keyboard-navigable list is achievable with the standard library (`termios`/`tty` on POSIX, `msvcrt` on Windows), but it is a meaningful amount of hard-to-test code and the CI matrix includes macOS and Windows. Start with a one-at-a-time prompt loop built on `input()`.

The hard requirement stands regardless of presentation: nothing is accepted or rejected until the user has reviewed the entire list, after which they are shown their selections for confirmation and may confirm, edit their selections, or cancel. Only on confirmation is the list processed in bulk.

The command must also behave sanely without a TTY (CI, piped input) rather than blocking on a prompt.

### `accept` filtering

`accept` takes an optional `--org` to restrict the listing to invitations from one organization. Faculty will generally have unrelated pending invitations, and `docs/architecture.md` states that faculty-facing commands select their subject with options rather than positionals. With no `--org`, all pending invitations are listed.

## Commands

### Send course org invites

Example:

`gh lab admin invites send --config-file saultcollege-csd217/course-info/config/26f.json`

- `--config-file` is required.
- Sends "Member" invites to all students AND faculty listed in the config file.
- The organization is the owner of the config file reference.
- `--dry-run` prints the resolved org and roster and makes no API calls.
- Reports per-person outcome: newly invited, already a member, or failed.

### Accept student repo invites

Example:

`gh lab admin invites accept`

- Present all the current user's pending invites (current user assumed to be faculty; if they're not they won't have the necessary privileges to do the GH commands).
- `--org` optionally restricts the listing to one organization.
- INTERACTIVELY allow user to accept/reject/skip individual invites; skip is the default.
- Accepting does NOT happen until the user has reviewed the ENTIRE list, after which they are presented with their final list of choices for confirmation. If they confirm, the whole list is processed in bulk. They also have the option to edit their selections or cancel.

## Tasks

Each task is independently delegatable and should end with the project's validation steps from `AGENTS.md`: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and a review of the diff for unrelated changes.

1. [+] **Promote course-config parsing to a shared module.** Move `CourseConfig`, `Faculty`, `parse_course_config`, `parse_faculty`, `parse_course_config_ref`, `normalise_repo_ref` and `ConfigError` out of `src/gh_lab/commands/setup_check/config.py` into a new shared `src/gh_lab/course_config.py`, leaving lab-config parsing where it is. Update `setup_check` imports and `tests/commands/test_setup_check_config.py` accordingly. Document the shared module in `docs/architecture.md`. No behaviour change.

2. [+] **Add `students` to the course config schema.** Extend the shared parser with an optional `students` array parsed into the same person shape as `faculty`, defaulting to empty, with index-naming validation errors. Add tests covering: absent, empty, valid, missing `github`, and missing optional `name`. Update `docs/configuration.md`.

3. [+] **Extend the GitHub adapter for write requests.** Add request-method and field support to `src/gh_lab/adapters/github_cli.py` (currently `_run_text`/`_run_json` have no `-X` or `-f` handling), and add `set_org_membership(org, username, role)` over `PUT /orgs/{org}/memberships/{username}` returning the resulting state. Follow the existing `AdapterError` translation for missing binary, timeout, non-zero exit and unexpected shapes. Add tests to `tests/test_adapters.py` using the existing `FakeCompleted` + `monkeypatch` pattern, asserting on the argv actually passed to `gh`.

4. [+] **Support nested subcommand groups in the CLI.** Extend `src/gh_lab/cli.py` so a command package can register a group with its own verbs, keeping the `set_defaults(handler=...)` dispatch mechanism. Create `src/gh_lab/commands/admin_invites/` with the established `shell.py` / `command.py` split. Add a CLI-level test that `gh lab admin invites --help` works and that bare `gh lab admin` exits 2 with usage.

5. [+] **Implement `admin invites send`.** Pure core in `command.py`: derive the org from the config ref, build the invite roster from faculty + students, and turn per-person API results into a structured report of plain dataclasses. Thin effectful layer for loading the config and calling the adapter. `shell.py` owns argparse, `--dry-run`, output and exit codes, following `setup_check`'s 0 / 1 / 2 convention.

6. [+] **Test `admin invites send`.** Pure functions called directly with plain data; effectful functions monkeypatched on the module object, as `test_setup_check.py` does. Cover: dry run makes no API calls, org derivation from each accepted config-ref spelling, an empty roster, already-a-member versus newly-invited reporting, and a partial failure. Include a `test_argument_surface_is_stable` guard test mirroring the existing one, since CI invokes the CLI directly.

7. [+] **Add repository-invitation adapter functions.** `GET /user/repository_invitations` to list, `PATCH /user/repository_invitations/{id}` to accept, `DELETE /user/repository_invitations/{id}` to decline. Pure helpers to shape the listing into dataclasses and to filter by org. Tests as in task 3.

8. [+] **Implement `admin invites accept`.** The review/confirm/edit/cancel flow as a pure state machine over plain data, so it can be tested without a terminal, with a thin `input()`-driven shell around it. Bulk-process only on confirmation. Handle a non-TTY stdin explicitly rather than blocking.

9. [ ] **Test `admin invites accept`.** Drive the state machine directly for review, edit, cancel and confirm paths; stub stdin for the prompt loop; assert that no accept or decline call is made before confirmation. Add the argument-surface guard test.

10. [ ] **Update user-facing documentation.** `README.md` (including the embedded `--help` block and both "`gh lab accept-invites` is planned" mentions), `docs/architecture.md` (the nested grammar, the shared course-config module, and the `accept_invites/` example), and `docs/configuration.md` (the `students` array).

11. [ ] **Update CI.** `.github/workflows/ci.yml` invokes the CLI directly, so a stale invocation fails only after push. Add `admin` to the `gh lab --help` grep, and add a smoke invocation of `gh lab admin invites send --dry-run` against a throwaway config plus `gh lab admin invites accept` in a non-TTY context, following the existing `printf`-based config setup. Keep `docs/development.md`'s command list in step.
