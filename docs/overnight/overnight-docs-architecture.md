# overnight-docs-architecture (AGENT-7, Nov 8 overnight)

Branch `overnight/overnight-docs-architecture` in the public repo, worktree `~/dev/agentboard-wt/AGENT-7-arch`, rebased onto `main` at 33ecb3e (Nov 8, after the cross-review). Not
merged: Troy reviews. No push, no spend, no live text; documentation, one test and two link lines in the README.

## What changed

| File | What it is |
|---|---|
| `docs/ARCHITECTURE.md` (new, 213 lines) | The developer's map: every module grouped by layer with one line each (29 modules and the two static files), import direction, the data files with who writes and who reads each (17 rows), a request's path through the server (the three guards, the headers, the route table, error shape), the agent protocol in `store.py` terms (card fields, lifecycle methods, subtasks, blockers, chat, memory), the plugin hook (gate, the seven `api` calls, guarantees), the security model on one page, and how to run the tests with the rules the suite enforces. |
| `CONTRIBUTING.md` (new, 76 lines) | Cards and worktrees (branch names in use, the shared-stash rule, hash to the orchestrator), the six gates before "ready" (suite OK run alone, publiccheck, doctor, render-check for index.html, version in three places, `rm -rf build`), the changelog rule in the file's own shape, commit messages, docs rules, what belongs in the public repo. |
| `docs/index.md` (new) | Every document with one line: the top-level five, `CLAUDE.md`, the seven `docs/*.md`, the overnight folder, and the picture and mockup folders. |
| `tests/test_docs_architecture.py` (new, 11 tests) | Holds the pages to the code, see below. |
| `README.md` | Three links at the end of Development: ARCHITECTURE, CONTRIBUTING, the index. |
| `CHANGELOG.md` | One entry under Unreleased. |

## How every statement was verified

Two ways. First, by reading the code while writing: each module's docstring and imports (an `ast` walk over `src/agentboard`), `store.py`'s
constants, lock and lifecycle methods, `server.py`'s guards, headers, routes and `serve()` start-up, `plugins.py`'s `Api`, `backup.py`,
`hooks.py`, `cursors.py`, `listeners.py`, `serverstate.py`, `runs.py`, `reports.py`, `private.py`, `lockdown.py`, `untrusted.py`, the page's
poll (`setInterval(load, 1000)`), `agentboard --help` and `agentboard instructions`. Second, by `tests/test_docs_architecture.py`, which
fails the day the pages drift:

- every `*.py` in `src/agentboard` is named in the module map, and every module the map names exists; `static/index.html` and `voice.js` too;
- the caps it quotes (`TITLE_MAX` 200, `DESCRIPTION_MAX` 20,000, `STATUS_MAX` 1,000, `BODY_MAX` 60,000) and the statuses are the code's values;
  the one-second poll is in the page;
- every data file in the table is named in the source (`tasks.json`, `.lock`, `chat-cursors.json`, `server-`, `boards.toml`, …);
- every `/api/...` path the server section names is a literal in `server.py`; the guard messages (`bad host`, `bad origin`, `json required`) and
  the headers it describes are there;
- every `agentboard <command>` the pages name is a real subcommand (read from `--help`);
- the plugin calls listed are exactly the public methods of `plugins.Api`, and every environment variable named exists in the source;
- every `docs/*.md` is in the index, every link in the index resolves, every top-level document and every `docs/` folder is listed; the README
  links the index and CONTRIBUTING; CONTRIBUTING names gates whose files exist.

Spot checks of the prose claims the test cannot hold: the owner's reply lands in the card's `answer` through `POST /api/reply`; a blocked
card is refused by `claim` without `--force`; `chat inbox --wait` registers a listener; `hooks install --user` exists; a report's `<card>.md`
is never swept; transcripts are served only from under `~/.claude/projects`; `done` is the owner's command ("USER-APPROVED completion").

## Before and after

| | Before | After |
|---|---|---|
| A developer's first question, "where is X?" | the README (user-facing, 560 lines) and 29 docstrings | one page with a module map, a file table and a route table |
| "What must I run before saying ready?" | spread over `CLAUDE.md`, the README's install notes and tribal knowledge in the chat | six numbered gates in `CONTRIBUTING.md` |
| "Which documents exist?" | `ls docs/` (7 pages, 9 picture folders, 6 mockups, no descriptions) | `docs/index.md`, one line each |
| A doc going stale | nobody notices until a review card | `test_docs_architecture.py` fails |

## How to try it

    cd ~/dev/agentboard-wt/AGENT-7-arch
    PYTHONPATH=src python3 -m unittest tests.test_docs_architecture -v
    open docs/index.md docs/ARCHITECTURE.md CONTRIBUTING.md      # or read them on GitHub once merged

## Test results

Full suite on the branch, `python3` (3.14), run alone: **Ran 1247 tests, OK** (1236 on `main` plus the 11 new ones). `python3 tests/publiccheck.py`: 0 findings. `test_install_clean`, `test_version`, `test_plugins`, `test_public_repo_clean`: OK (they read the docs).

## Risks and what I did not do

- The pages describe `main` at 8b07a0d. Two overnight branches of mine change things they describe: `overnight/overnight-install-quickstart`
  adds `tomlread.py` (the module map would then need one row, and the test says so) and lowers the Python floor. Whoever merges second
  updates the map; the test will point at the exact gap.
- The protocol section paraphrases `agentboard instructions`; the command is the source of truth and the page says so.
- Not done: diagrams. The route table and the file table carry the same information in a form the test can check; a drawing would not be.
- Not done: a per-function reference. The docstrings are good and close to the code; the page points at them rather than copying them.

## After the cross-review (AGENT-8, cards xr-docs-architecture-fails-main and xr-docs-architecture-field-names)

- Rebased onto `main` 33ecb3e (the CHANGELOG was the only conflict). `main` had merged `chatwake.py` in the meantime, and the module test caught it
  as designed: the map now has a `chatwake.py` row, the file table has `chat-wake.json` and the `settings.json.orig` / `.bak` copies `hooks install`
  keeps, and the import sentence names `chatwake` and `listeners`.
- Field names fixed: a subtask's field is `parent_id` (the page said `parent`); the owner's answer lands in `reply` (`text`, `at`, `by`), not `answer`,
  which is the command. `report` and `run` were added to the card paragraph.
- The test now also holds the card fields: every field named in the protocol paragraph must be a literal in `store.py`. The page's first
  paragraph says what the test guarantees and what it cannot (the prose).
- `tests/test_docs_architecture.py` on the rebased branch: 12 tests OK; `test_install_clean`, `test_version`: OK; publiccheck 0 findings.
