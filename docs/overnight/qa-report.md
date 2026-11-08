# Overnight QA: clean room, suite, soak, render (Nov 7-8, 2026)

Card `overnight-qa-cleanroom`, branch `overnight/overnight-qa-cleanroom`, AGENT-6. Nothing here is merged; Troy reviews in the morning.
Everything ran on throwaway folders, throwaway boards and spare ports; no live board, no network beyond localhost except where a step
says "network allowed" (pip and pipx fetching build tools), no spend, no text.

**Read first.** One real startup bug: on Python 3.11 the package installs and then every command dies with a SyntaxError (one f-string in
`reports.py`, legal only from 3.12). README and pyproject promise 3.11. The one-line fix and a guard test are on their own small branch,
`fix-python-3-11-fstring` (6cc2742), for ORCH to merge tonight; the same two files are on this branch. Second, for the locked-down work PC:
neither documented install works without the package index; a prebuilt wheel in a venv does. Everything else held up: the suite is green
on 3.12 to 3.14, the server took 400 cards, 12 agents at once and 10 restarts without losing an update, and every page renders clean at
1440 and 390 wide in light and dark.

## PASS/FAIL table

| Area | Check | Result | Evidence |
|---|---|---|---|
| Install | `git clone` + `pipx install .` (network allowed) | PASS | `tests/qa/cleanroom.sh`, fresh HOME and PIPX_HOME |
| Install | `agentboard --version` prints 0.3.1 | PASS | |
| Install | `init` makes tasks.json and config.toml, adds `.agentboard/` to .gitignore | PASS | |
| Install | `doctor`, `instructions`, add/claim/update/review/done | PASS | |
| Install | `serve`: `/`, `/hud` 200, log without Traceback, second serve on the same port says so politely | PASS | binds 127.0.0.1 only (`server.py:435`) |
| Install | upgrade `rm -rf build && pipx install . --force`; `hooks install`; `pipx uninstall` removes the command | PASS | |
| Install | README venv path, `python3.X -m venv` + `pip install .` on 3.12, 3.13, 3.14 | PASS | |
| Install | README venv path on **3.11** | **FAIL** | installs, then `agentboard` dies: SyntaxError in reports.py line 322. Card `qa-python-3-11-syntaxerror`. Fixed on this branch and on `fix-python-3-11-fstring` |
| Install | **offline** `pipx install .` (PIP_NO_INDEX=1) | **FAIL** | pipx upgrades its shared pip to >=23.1 from the index first, even for a prebuilt wheel. Card `qa-offline-install-needs-index` |
| Install | **offline** venv + `pip install .` on 3.11-3.14 | **FAIL** | the isolated build env wants setuptools>=68 from the index |
| Install | offline venv + `pip install agentboard-0.3.1-py3-none-any.whl` | PASS | the wheel needs nothing; `--version` prints 0.3.1 |
| Install | publiccheck on the clone | PASS | 0 findings |
| Suite | full suite, Python 3.14, alone | PASS | 1201 tests OK in 188 s |
| Suite | full suite, Python 3.11, after the f-string fix | 5 FAIL | 1201 tests; 4 redact timing tests and 1 Unicode-table test, see "Suite notes" |
| Suite | full suite, Python 3.12 and 3.13 | see below | `tests/qa/suite_matrix.sh` |
| Suite | shuffled order (`tests/qa_random_order.py`), several seeds and Pythons | see below | |
| Suite | three suites at once on one machine | 3 FAIL | load flakes in timing tests; the same suite alone is green |
| Soak | seed 400 cards, `list` them | PASS | `tests/qa/soak.py` |
| Soak | 12 agents x 6 cards through the CLI at once (claim, 3 updates, chat, ask or review) | PASS | 15 s, no CLI error, no lost update, tasks.json and .bak valid |
| Soak | chat: tail shows the lines; `inbox --wait` exits 1 at the timeout and 0 within 0.2 s of a line | PASS | |
| Soak | 10 server restarts: up within 10 s, every GET route 200 (JSON where expected), a POST edit each time, no Traceback, nothing over 2 s | PASS | |
| Soak | backups: a snapshot exists, `verify` and `backup` run | PASS | |
| Soak | hooks: install writes both hooks; `hook send-message` mirrors to chat (with agent chat on) and swallows garbage; `hook stop` blocks once, never twice | PASS | |
| Soak | `doctor` on the soaked board | PASS | an earlier run flagged 2 entries made by my seeding through the Store API under umask 022; the CLI and server set umask 077 themselves (`private.py`), and the soak now does too. Not a bug |
| Soak | stop hook wording | LOW | "a line you types there" when the owner has no name. Card `qa-stop-hook-reason-grammar` |
| Render | board, HUD, By agent at 1440 and 390 wide, light and dark | PASS 12 of 12 | no console error, no failed load, no horizontal overflow, no unnamed control; `docs/overnight/qa-shots/` |
| Render | deep link to a card that no longer exists; a script-shaped hash | PASS | toast "That task no longer exists.", nothing runs; the only console line is the 404 fetch |
| Render | text under 11px | note | one 10px span (the ORCH avatar initial) on every page |

## Suite notes

- **3.14 alone: 1201 OK.** The first 3.14 run showed 3 failures because the 3.14, 3.11 and the home plugin suites were running at the same
  time; alone it is green. Treat a red suite on a busy machine as "run it again alone" before anything else.
- **3.11 after the fix: 5 failures, none a product bug.** Four are the redact timing tests (`test_redact_dos`, `test_redact_fullwidth`,
  `test_redact_invisible.StillFast`): 3.11's regex engine is slower and the thresholds are tuned on 3.14; the run also overlapped with
  the home gate. One is `test_redact_invisible.TheSetIsSound`: it asserts every code point in the invisible set has a known category, and
  U+13439 (an Egyptian hieroglyph format control) is unassigned in 3.11's Unicode 14 tables (3.12 has 15.0, 3.14 has 16.0). The masker still
  strips it; only the test's assumption is version-bound. Filed as one card, `qa-redact-tests-assume-3-14`.
- **3.13 alone: 1201 OK** (155 s). **3.12: 1200 of 1201**; the one failure is `test_redact_dashes.StillFast`, a timing test, while a
  12-process CLI burst of mine overlapped the run (the same load sensitivity as above).
- **Shuffled order: no order dependence found.** Six shuffled runs (seeds 309066, 979817, 146070, 463803, 100727 on 3.14, 290127 on 3.11)
  first showed the same 9 failures every time; all nine were the runner's doing (seven modules import `tests.test_doctor`-style helpers,
  which need the repo root on the path, as `python -m unittest` from the root has it). With that fixed, seed 146070 on 3.14 is 1201 tests,
  0 failing in 182 s. The 3.11 shuffle also had the Unicode-table test above.

| Python | Full suite, normal order | Shuffled |
|---|---|---|
| 3.14 | 1201 OK (alone); 3 timing flakes when three suites ran at once | 1201 OK, seed 146070 |
| 3.13 | 1201 OK | not run |
| 3.12 | 1200 OK, 1 timing flake under load | not run |
| 3.11 | 1196 OK after the f-string fix; 4 timing, 1 Unicode-table (card) | same Unicode-table test |

## Bugs filed (one card each)

| Card | Severity | One line |
|---|---|---|
| `qa-python-3-11-syntaxerror` | HIGH (startup) | f-string with nested quotes in reports.py; fixed on `fix-python-3-11-fstring` 6cc2742 and here; guard test `tests/test_min_python_syntax.py` |
| `qa-offline-install-needs-index` | MEDIUM (work PC) | no documented install works with the index refused; a prebuilt wheel in a venv does; README needs an "Offline install" paragraph and the release needs the wheel |
| `qa-redact-tests-assume-3-14` | LOW (tests) | timing thresholds and the Unicode-table assertion fail on 3.11 |
| `qa-stop-hook-reason-grammar` | LOW (wording) | "a line you types there" |

## What changed on this branch

- `src/agentboard/reports.py`: one f-string uses single quotes inside its braces (the 3.11 fix).
- `tests/test_min_python_syntax.py`: compiles `src/` with the oldest promised interpreter when it is on PATH; checks README and pyproject
  agree on the floor.
- `tests/qa_random_order.py`: the whole suite in a shuffled order with a printed seed.
- `tests/qa/`: `cleanroom.sh`, `soak.py`, `render_check.py`, `suite_matrix.sh` (the scripts behind this table).
- `docs/overnight/qa-report.md` and `qa-shots/`.

## How to try it

```
bash tests/qa/cleanroom.sh /tmp/agentboard-cleanroom          # 31 steps, about 3 minutes; needs pipx, python3.11-3.14, curl
python3 tests/qa/soak.py /tmp/agentboard-soak src              # about 2 minutes; prints PASS/FAIL per check
pip3 install --target tests/qa/pylibs websocket-client         # once, for the render check
python3 tests/qa/render_check.py http://127.0.0.1:<port> /tmp/agentboard-render   # against a throwaway board you serve first
bash tests/qa/suite_matrix.sh /tmp/agentboard-matrix           # full runs per Python plus shuffled runs; about 25 minutes
python3 tests/qa_random_order.py --seed 12345                  # one shuffled run, the same order again
```

The scratch dir is the only thing `cleanroom.sh` and `soak.py` delete, and only one they made themselves: a path that does not exist
yet, or a dir holding the marker file they wrote (`.agentboard-qa-scratch`). Your home, a project, a board folder or an existing dir
without the marker is refused with exit 2 (cross-review card `xr-qa-rm-rf-unguarded`).

## Risks and what this does not prove

- The clean room cloned this checkout, not GitHub (no network rule), so a stale GitHub main is not caught here.
- Windows was not run (no Windows here); the README says macOS.
- The render check reads the DOM and console; it does not judge contrast or spacing (that is `overnight-ux-visual-polish`).
- The soak drives the CLI and HTTP; a real Claude Code session with the hooks attached was not in the loop.
