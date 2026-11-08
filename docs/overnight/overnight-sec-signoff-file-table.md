# overnight-sec-signoff-file-table: evidence

Card: `overnight-sec-signoff-file-table` (AGENT-8, night of 2026-11-07), filed from `overnight-sec-nonet-guard` as the next improvement in
the same area. Branch `overnight/overnight-sec-signoff-pack` (third commit on it). Nothing merged, nothing pushed, no spend, no live text.

## What changed

- `tests/test_signoff_files.py` (new, 8 tests). A scripted day on a throwaway project with a throwaway HOME under `umask 022` (the `Session`
  helper from `tests/test_file_modes.py`: init, add, claim, a subtask, update, ask, review with a body, a chat line to the owner, backup,
  hooks install). Then:
  - every path written under the project is named in the "Every file the board writes" table of `docs/security-signoff.md`
    (`<stamp>`, `<pid>`, `<card>`, `<id>` are wildcards; `{a,b}` lists alternatives; a folder counts as documented when a documented
    path lies inside it), or the test fails with the new file's name;
  - the mode on disk is the mode the table gives: 600 / 700 inside `.agentboard/`, and `.gitignore` and `.claude/settings.json` follow the
    user's umask (644 in the session) and the table must say so;
  - nothing at all is written under HOME, and the table names `~/.agentboard/boards.toml` as the only HOME file;
  - the parser itself: the table is found, wildcards and folders match what they should, `tasks.json` does not match `tasks.json.bak`,
    and an undocumented name (`chat-nobody.json`) is reported.
- `docs/security-signoff.md`: the reports/runs row's mode cell now reads `600 (folders 700)`, which the test required (the folders are 700).
- `CHANGELOG.md`: one line under the Nov 7 entry.

## Why

On Nov 7 the public repo gained `chat-listeners.json` and `server-<pid>.json` and `SECURITY.md` kept its old list. A reviewer trusts a file
table only if it cannot drift; now the suite says so.

## Before / after

Before: the table was a snapshot, true on the day it was written. After: adding a state file without a row in the table fails the suite
with the file's name; loosening a mode fails it with the mode.

## How to try it

```
cd <worktree>; PYTHONPATH=src python3 -m pytest -q tests/test_signoff_files.py     # 8 passed, about 5 s
```
To see it catch drift: add `(self.dir / "scratch.json").write_text("{}")` anywhere in `Store.__init__` and run it; the failure names
`.agentboard/scratch.json`.

## Test runs on this branch (both runners, whole suite)

```
PYTHONPATH=src python -m pytest -q                      1204 passed, 29 subtests passed in 179.17s   (run alone, load average 8)
PYTHONPATH=src python -m unittest discover -s tests      Ran 1204 tests: 2 failures, both the 2.0 s wall-clock tests in
                                                         test_redact_dos / test_redact_fullwidth, run at the same time as the pytest
                                                         run on a machine at load 15; the two files alone right after: 28 passed
```
`python3 tests/publiccheck.py`: 0 findings. The pytest run alone is exactly green; the wall-clock pair fails only when two suites share
a loaded laptop, as recorded on the two earlier cards.

## Risks

- The scripted day does not start `agentboard serve`, so `server-<pid>.json` (written by the server) and the opt-in files (`runs/`,
  `chat-casual.json`, `chat-autopilot.json`, the sync copy) are covered by the table but not exercised here; `tests/test_server_state.py`
  and `tests/test_file_modes.py::test_serve_tightens_at_start` cover the server's files.
- The test reads the sign-off from `docs/`; renaming the heading "Every file the board writes" breaks the parser on purpose (the test says where).
- About five seconds of wall clock (a real subprocess session), the same cost as `test_file_modes.py`.
