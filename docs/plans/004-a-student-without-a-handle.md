# 004 — A student whose GitHub handle is not known yet

## Status

DONE

## Why

`gh lab admin invites send` refuses to run when any student in the private
roster has no GitHub handle. `parse_people` built every entry with
`require_string(entry, "github", where)`, which rejects an absent, null, and
blank value alike; nothing between there and the CLI caught it. `load_students`
handles only `json.JSONDecodeError`, `run_send` calls it before `build_roster`,
and `handle_send` turns any `ConfigError` into exit 2. One unfinished roster row
therefore stopped the entire cohort being invited — and stopped `--dry-run` too,
since the file is parsed before the dry-run branch.

That is the opposite of how the rest of the command behaves. `invite_everyone`
deliberately keeps going when one person's invitation fails, on the grounds that
a mistyped handle part-way down a roster should not decide whether the rest of
the course gets invited. A handle nobody has collected yet deserves the same
treatment: a roster is assembled at the start of a term, so being enrolled
before your handle is known is an ordinary state for the file to be in, not a
malformed file.

## The rule

`github` must be **present** on every entry, in both files. Its value may state
that it is not yet known:

| Value | Faculty | Students |
| --- | --- | --- |
| `"bobber24"` | invited | invited |
| `null`, `""`, `"   "` | error | not invited, reported |
| absent | error | error |
| not a string (`42`, `{}`) | error | error |

Presence is what makes the two cases distinguishable. An absent key is an entry
somebody has not finished writing; `null` is somebody saying "enrolled, handle
unknown". Only whoever wrote the file knows which they meant, so the file has to
say. A spreadsheet export of a roster gives `""` for a blank cell, which is the
common way this arrives.

## Decisions

* **Students only. Faculty keep the strict rule.** The faculty list is short,
  hand-written, public, and read by `setup-check` to decide who must be a
  collaborator on every student repository. A faculty member with no handle is a
  check that cannot be made, rather than an invitation that can wait.
* **`Person.github` stays `str`.** Making it `str | None` would push the optional
  into `build_roster`, `set_self_aside`, `invite_everyone` and
  `setup_check._check_faculty`, all of which call `person.github.casefold()` or
  interpolate the handle into a `gh api` command. A separate type keeps the
  invariant "a `Person` can be invited" true everywhere it is relied on.
* **A student without a handle gets its own dataclass**, `Unidentified`, holding
  where it sat in the array and the name if there was one. The position is what
  whoever fixes the file needs, and is the only identification when there is no
  name either.
* **`parse_roster` returns a `Roster`** rather than a bare tuple, so both halves
  travel together. They are separated at the parse, which is the only place that
  can tell them apart, rather than re-derived later.
* **The position comes in two spellings.** `students[3]` alone identifies an
  entry in a report that has already named the file it came from; an error
  message has named nothing, so it carries the file too.
* **The report names them, the exit code does not.** The command did everything
  it could, so it exits 0; only a failed invitation still exits 1. The line
  reads in the same voice as the existing `not inviting you, Bob Bob
  (@bobber24)`.
* **Reported on a dry run as well as a real one.** A dry run is what faculty
  check a roster with before sending, so it is the run that most needs to say
  who is not on it.
* **The absent-key message teaches the fix.** Hand-editing JSON means deleting
  the line rather than typing `"github": null`, so the message a faculty member
  actually meets is the one that has to say the value may be null. Only
  `declared_string` carries that advice: `require_string` is shared with
  `.lab/config.json`, where a null `repo-name` means nothing.
* **Rejected: skipping silently.** The point of a roster is that it accounts for
  everyone. A student quietly dropped is worse than one who stops the command,
  because nobody finds out.
* **Rejected: tolerating a bare string or a number in `students`.** Those are a
  malformed file rather than a missing field, and no reading of them says "not
  known yet".

## Tasks

1. [+] Add `declared_string` to `course_config.py`, beside `require_string` and
   `optional_string`: the key must be present, its value may be `None` or blank
   to mean "not known yet", and a non-string is an error.
2. [+] Make its absent-key message name `null` as the way to state an unknown
   value.
3. [+] Add `Unidentified` (`where`, `name`) with a `display` property mirroring
   `Person.display`.
4. [+] Add `Roster` (`students`, `unidentified`).
5. [+] Split the array and entry validation out of `parse_people` into
   `_entries`, which yields each entry with its position in both spellings, so
   `parse_people` keeps its strict behaviour for `faculty` and the roster path
   reuses the same validation without a flag argument.
6. [+] Make `parse_roster` return a `Roster`, using `_entries` and
   `declared_string`.
7. [+] Return the `Roster` from `load_students`, and pass its halves into
   `build_roster` and the report from `run_send`.
8. [+] Add `unidentified` to `SendReport`.
9. [+] Add `_unidentified` and `_students` to `shell.py`, called from both
   `render_roster` and `render_results`.
10. [+] Leave the exit codes alone. Nothing else reads `parse_roster`;
    `setup-check` reads only `faculty`.
11. [+] Update `tests/test_course_config.py`: the absent key still raising and
    naming its position, the message naming `null`, `null`/`""`/`"   "` yielding
    an `Unidentified`, a non-string handle still raising, the faculty
    equivalents still raising for every value, and the two halves kept apart.
12. [+] Update `tests/commands/test_admin_invites.py`: `stub_config` answers with
    a `Roster`, a roster holding one carries on and exits 0, and both renderers
    name them with and without a name.
13. [+] Update the `students` section of `docs/configuration.md` and the `send`
    section of `README.md`.
14. [+] Check `.github/workflows/ci.yml` per `AGENTS.md`. It exercises only
    unresolvable references and unreachable configurations, and no argument
    changed, so nothing there needed updating.
15. [+] Run the tests, `ruff check` and `ruff format --check`.
