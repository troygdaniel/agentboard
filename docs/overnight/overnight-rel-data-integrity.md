# Overnight reliability: core data integrity and crash recovery

Branch `overnight/overnight-rel-data-integrity` (public repo, not merged; Troy reviews). AGENT-1, Nov 7 night.

## What changed

- **One way to write state** (`src/agentboard/statefile.py`, new). The small JSON files beside `tasks.json` (the sessions file, the chat hour counts, a run's `run.json`) were written in place with `write_text`; the chat cursors and the listeners file got their own locked, atomic writers on `main` meanwhile (`cursors.py`, chat-f2 and chat-f4), and `.claude/settings.json` its own `write_settings` (mode kept, `.orig` and `.bak`), which this branch now uses as they are; a crash or a `kill -9` between the open and the close left half a file. They now go through the same atomic write as the board: a temp file in the same folder, flushed, renamed over the old one. An update (the cursor an agent records after reading its inbox) is a locked read-modify-write (`flock` on `<file>.lock`), so two agents writing at the same moment lose nothing, and a cursor only moves forward.
- **Crash recovery says which copy is good.** A `tasks.json` that is not JSON used to fail with "restore latest (or previous)". Now the one line names the copy that is actually good and the exact command: `tasks.json.bak (the version before the last save) is good, 41 tasks: run agentboard restore previous`; else the newest snapshot by name with `restore latest`; else where to look. A corrupt state file is read as empty (state is rebuilt from use) and `agentboard verify` names it.
- **Leftover temp files are swept.** A writer killed between its temp write and the rename leaves `.tasks.json-xxxx.tmp`. The next save removes any such file older than ten minutes (a write in flight is never touched); `verify` lists them until then.
- **`agentboard verify` checks more.** Besides `tasks.json`, `.bak`, the newest snapshot and its age: every state file is valid JSON, no leftover temp files, and a **restore test**: the newest snapshot is put back into a scratch folder and loaded as a board (`ok  restore test: tasks-20261107-2300.json.gz restores to a board of 41 tasks`). Exit 1 on any BAD line, as before.
- **`agentboard verify --fix`** removes the leftover temp files now (a minute old or more) and sets a state file that is not JSON aside as `<name>.broken-<stamp>`, so the next write starts fresh and the broken file is still there for a look. It never touches `tasks.json`: that is what `restore` is for, and the recovery line names the copy to restore.
- **Soak tests** (`tests/test_data_integrity.py`, 15 tests, about 11 s): eight threads and four processes updating one state file lose nothing while a reader never sees half a file; five processes adding cards at once lose none; eight writer processes killed with `SIGKILL` at random moments leave a valid board holding every card they printed; `agentboard serve` killed with `SIGKILL` while four clients post keeps every card it answered 200 for and restarts on the same folder; corrupt board and state files give the lines above and `restore previous --yes` heals the board; a source scan refuses any new in-place JSON write in the package.

## Test runs

- `tests/test_data_integrity.py`: 15 tests OK (about 11 s alone).
- Full public suite on this branch after the rebase onto `main` 5e7a929 (chat-f2..f7 and the hook fixes merged): **1287 tests OK** (Nov 8); before the rebase 1201 OK (23:54 on Nov 7, load average 8). An earlier run at 23:20 under a load average of 14 (eight agent sessions running suites at once) had two timing checks fail, `test_redact_dos` (2.2 s against a 2.0 s limit; it failed on `main` under the same load, the masker is untouched here) and `test_doctor.Cli` (passes alone); neither is touched by this branch. `python3 tests/publiccheck.py`: 0 findings.

## Before and after

| | before | after |
|---|---|---|
| chat cursor written by two agents at once | last writer wins, one cursor lost | locked update, both kept |
| kill -9 while writing `chat-listeners.json` | half a file, read as empty, no word | old file or new file, never half |
| `tasks.json` corrupt | "restore latest (or previous)" | names the good copy, its card count and the one command |
| leftover `.tasks.json-xxxx.tmp` | stays forever | swept on the next save after ten minutes; `verify` lists it meanwhile |
| `verify` | board, .bak, snapshot, age | plus state files, temp files, restore test |

## How to try it

```
PYTHONPATH=src:tests python3 -m unittest tests.test_data_integrity          # the soak and recovery tests alone
agentboard verify                                                          # on any board: look for the restore test line
python3 - <<'EOF'
# corrupt a throwaway board and read the recovery line
import tempfile, pathlib
from agentboard.store import Store, BoardError
d = pathlib.Path(tempfile.mkdtemp()) / ".agentboard"; d.mkdir(); s = Store(d); s.add("one"); s.add("two")
(d / "tasks.json").write_text("{broken")
try: s.load()
except BoardError as e: print(e)
EOF
```

## Risks

- `statefile.update` takes a lock file beside each state file (`chat-cursors.json.lock` and so on); these are tiny and never removed. On a platform without `fcntl` the write is still atomic but two simultaneous updates can lose one; the board's own `tasks.json` lock already had the same caveat.
- The temp sweep removes `.*.tmp` files in the board folder older than ten minutes. Nothing else writes such names there; a plugin that did would lose a stale temp file of its own, which is what a stale temp file is for.
- The restore test in `verify` reads the newest snapshot and writes only to a scratch folder; it adds the cost of one gunzip and one parse per `verify`.
- No change to the board file format, the API or the page.

## Not done (candidates for a next card)

- A second server on the same board is refused by the port only; a `.agentboard/server-*.json` check could say so in words.
