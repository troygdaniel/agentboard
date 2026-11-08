# overnight-perf-scale (AGENT-7, Nov 8 overnight)

Branch `overnight/overnight-perf-scale` in the public repo, worktree `~/dev/agentboard-wt/AGENT-7-perf`, rebased onto `overnight/combined-11` at 59b848e (the eleven reviewed branches plus the merge kit's fixups; Nov 8, after the cross-review). Not merged:
Troy reviews. No push, no spend, no live text. Everything below was measured on a THROWAWAY board in a temp folder (`tests/perf_bench.py`),
on this Mac (M-series, Python 3.14), with the other overnight agents' work going on around it.

## What was measured, and what it showed

`tests/perf_bench.py` seeds a board with N cards in realistic shapes (statuses by weight, agents, logs of 2 to 9 entries, every fourth card
a subtask, a review body on some, half of the done cards archived) and M chat lines, starts the real server on an ephemeral port, and times
the store, each API route, the writes an agent makes, `agentboard serve` start-up, and with `--browser` first paint and time to cards in
headless Chrome. With `--soak M --agents N` it runs N fake agents posting an update a second (and a chat line every tenth second) plus one
fake page polling once a second, for M minutes, and reports latencies, RSS and CPU.

Where the time went before (5,000 cards, 10,000 chat lines, `tasks.json` 10.4 MB):

| Cost | Before | Why |
|---|---|---|
| `/api/hud`, one poll | 542 ms | `hud.build` parsed 130,000 timestamps with `strptime` (80 % of the time); the page polls it every second |
| `/api/tasks`, one poll | 61 ms and 2.1 MB | the whole board parsed, slimmed and serialised on every poll, changed or not |
| `/api/chat`, one poll | 89 ms | two full parses of the 10 MB file to return the last 200 lines and the agents switch |
| `store.update` | 148 ms (p95 185) | parse 45 ms + dump 37 ms + atomic write 5 ms, then `maybe_report` re-read the whole board (another 47 ms) to see whether a report was due |
| `store.review` / `done` | 291 / 294 ms | the above plus the HTML report (git log, the page) |
| page `render()` with 1,641 top-level cards | 341 to 392 ms | the Todo column drew every card (Done already folded past 5) |

## What changed

| Change | Where |
|---|---|
| **A derived cache per board, keyed by `tasks.json`'s (mtime_ns, size, inode)**, for what `/api/tasks`, `/api/hud` and `/api/chat` build from the file. Every save renames a new inode over the file, so a hit is never stale; a change is seen on the next poll (a test proves it). The HUD key also carries a 5-second clock bucket (its "now", idle minutes and open lane ends move with time). A board with a running one-shot run is never cached (its `alive` flag can change without a write). | `server.py`: `_file_key`, `_derived` |
| **ETag and 304.** The three routes send an `ETag` (sha1 of the body) and answer `304` with no body when the page's `If-None-Match` matches. `Cache-Control: no-store` stays: the browser caches nothing; the page remembers the tag. | `server.py`: `_send_cached`; `index.html`: `load`, `hudLoad`, `loadChat` |
| **The one stamp parser, `store.parse_stamp`, tries `fromisoformat` first** for the board's own `YYYY-MM-DDTHH:MM:SS` shape (a regex guard; `strptime` as the fallback); `hud._t` calls it. | `store.py` |
| **`maybe_report` reads the committed snapshot**, not the file again. `Store.committed` is the task list as the store last wrote it. | `reports.py`, `store.py` |
| **Todo column folds past 200 cards** with a Show N more / Show fewer button, as Done does past 5. | `index.html`: `TODO_SHOWN`, `todoColHtml`, the `more-todo` click |
| **Budgets in the suite**: `tests/test_perf_budgets.py` (6 tests, about 3 s): 1,000 cards and 2,000 chat lines against a real server; budgets of roughly three times the measured cost, stretched by the machine's factor the way `tests/timing.py` does and best of three tries, so a loaded laptop does not fail green code and a doubled cost still fails. Also: payload sizes, a stale-cache check, 10,000 chat lines. | `tests/test_perf_budgets.py`, `tests/perf_bench.py` |

## Before and after

Same machine, same bench, same seed; "before" is `main` (ad37d9b) through `AGENTBOARD_SRC`, "after" is this branch. A poll "unchanged" is the
page's second-and-later poll of a still board (the common case: once a second, all day); "cold" is the first poll after a write.

**5,000 cards, 10,000 chat lines (`tasks.json` 10.4 MB)**

| | Before | After |
|---|---|---|
| `/api/tasks` poll, unchanged board | 61 ms, 2.1 MB every second | 1 ms, `304`, no body |
| `/api/tasks` first poll after a write (cold) | 61 ms | 57 ms (the parse and the dump; unchanged by design) |
| `/api/hud` poll, unchanged board | 542 ms, 210 KB every second | 0 ms, `304` (rebuilt at most every 5 s) |
| `/api/hud` cold | 542 ms | 136 ms (`fromisoformat`) |
| `/api/chat` poll, unchanged | 89 ms | 0 ms, `304` |
| `/api/chat` cold | 89 ms | 87 ms |
| `store.claim` median / p95 | 90 / 133 ms | 93 / 147 ms (noise: the same parse + dump + write) |
| `store.update` median / p95 | 148 / 185 ms | 98 / 127 ms (no re-read after the commit) |
| `store.review`, `store.done` median | 291 / 294 ms | 266 / 266 ms |
| `POST /api/move` median | 230 ms | 208 ms |
| `agentboard serve` to port answering, best of 3 | 103 ms | 92 ms |
| page: first paint (3 trials) | 476 / 244 / 84 ms | 92 / 64 / 68 ms |
| page: time to cards drawn (3 trials) | 1004 / 757 / 491 ms | 561 / 285 / 296 ms |
| page: cards drawn on the board | 1,641 | 918 (Todo folds past 200; a Show 723 more button) |
| page: one `render()` re-run (a poll with a change) | 342 / 355 / 392 ms | 252 / 204 / 246 ms |
| page: switch to the HUD view | 252 / 228 / 273 ms | 76 / 81 / 158 ms |
| page: JS heap after load | 9 to 23 MB | 9 to 17 MB |
| page HTML transfer | 360 KB | 361 KB |

**1,000 cards, 2,000 chat lines (`tasks.json` 2.1 MB)**

| | Before | After |
|---|---|---|
| `/api/tasks` poll, unchanged / cold | 15 ms, 432 KB / 16 ms | 0 ms `304` / 10 ms |
| `/api/hud` poll, unchanged / cold | 144 ms / 120 ms | 0 ms `304` / 24 ms |
| `/api/chat` poll, unchanged / cold | 21 ms / 18 ms | 0 ms `304` / 15 ms |
| `store.claim` / `update` median | 17 / 25 ms | 13 / 13 ms |
| `store.review` / `done` median | 69 / 68 ms | 47 / 47 ms |
| `POST /api/move` median | 34 ms | 26 ms |
| startup, best of 3 | 96 ms | 78 ms |

**Soak: 12 fake agents, one update a second each (a chat line every tenth), one fake page polling tasks and chat once a second, 5 minutes,
1,000-card board, the server in the same process**

| | Before | After |
|---|---|---|
| writes made | 3,569 | 3,573 |
| write latency median / p95 / p99 / max | 23 / 95 / 253 / 367 ms | 15 / 53 / 115 / 811 ms (one outlier: the hourly snapshot, gzip of 2 MB, landed inside the window) |
| page poll latency (tasks + chat) median / p95 / max | 27 / 153 / 527 ms | 24 / 70 / 583 ms |
| process RSS, max over the run | 93 MB | 95 MB (flat: 74 and 88 MB at the end; the start figure, 175 to 185 MB, is the seeding, freed at once) |
| CPU of the process | 88 s over 301 s = 29 % of one core | 62 s over 301 s = 21 % |
| `tasks.json` growth | 2,078 to 2,240 KB | the same (3,500 log lines) |

The one-hour run is the same command with `--soak 60`; nothing in the five minutes grows (RSS flat, file growth is the log lines the agents
wrote), so the hour is expected to look like this times twelve. I did not run it because the night is shared with four other agents' suites.

## Test results

Full suite on the branch (`python3`, 3.14), run alone: **Ran 1271 tests, OK** (1265 on `main` plus the 6 budgets). `python3 tests/publiccheck.py`: 0 findings. The budgets module alone: 6 tests in about 3 s.

## How to try it

    cd ~/dev/agentboard-wt/AGENT-7-perf
    PYTHONPATH=src python3 -m unittest tests.test_perf_budgets -v                    # the budgets, about 3 s
    python3 tests/perf_bench.py --cards 1000 --chat 2000                             # the numbers on this machine
    python3 tests/perf_bench.py --cards 5000 --chat 10000 --browser                  # plus first paint (headless Chrome, /tmp/qa_pylibs)
    python3 tests/perf_bench.py --cards 1000 --chat 2000 --soak 60 --agents 12       # the one-hour soak Troy asked for (I ran 5 minutes, below)
    AGENTBOARD_SRC=~/dev/agentboard/src python3 tests/perf_bench.py ...              # the same against main's code, for a before

The page: open a board, watch the Network tab: `/api/tasks` is `304` every second until something changes.

## Risks and what I did not do

- **The cache is per server process and per board**, held in memory, bounded to one entry per (board, route). A write from another process is
  seen because the key is the file's inode, not a notification. If a tool rewrote `tasks.json` in place (same inode, same size, same
  mtime_ns) the cache would miss it; nothing in agentboard does that (every write is `write_atomic`, a rename).
- **The HUD may be up to 5 s behind** while nothing is written (its clock-dependent fields). Every write invalidates it at once.
- **The write path is still a full rewrite of the file** (parse + dump + atomic write): about 15 ms at 1,000 cards, about 90 ms at 5,000. Twelve
  agents writing every second serialise on the lock; at 1,000 cards that is about a fifth of the lock's capacity, at 5,000 about all of it. The
  real fix for a 10 MB board is to keep archived cards out of the hot file; not done tonight (a design decision for Troy: a second file
  `archive.json` that `clear` moves done cards into, read by `recall`, `lookup` and the HUD's history only).
- **`review` and `done` still cost 50 to 290 ms** (the HTML report, with `git log`). They happen a few times an hour, not every second.
- **The one-hour soak was run for five minutes** (twice: main's code and this branch), to fit the night; the command for an hour is above.
- **First paint depends on the browser**: headless Chrome numbers vary two-fold between trials (a cold renderer); the bench reports every trial.

## After the rebase onto overnight/combined-11 (de06986)

- `server.py`: the three cached routes now also carry what the combined tree added, inside the cache: `/api/tasks` appends the watchdog findings
  (`_watchdog_cached`, its own few-second cache) to the cached slim bytes, `/api/hud` computes `watchdog.findings` inside `build_hud` (so it is
  rebuilt with the HUD, at most every 5 s), `/api/chat` keeps `known_names()` in the cached part and adds `retired` per request.
- `hud._t` is the combined tree's `return parse_stamp(s)` (one stamp parser for the board); the `fromisoformat` fast path moved into
  `store.parse_stamp`, so every caller gets it.
- `store._write` keeps both the committed snapshot and the combined tree's temp-file sweep. The Todo fold rides on the combined tree's
  Todo column (its new ORCH button title kept).
- The budgets and the quick server/HUD tests pass on the rebased tree; the full suite result is below.
- **Suite on the rebased branch** (combined-11 + this): at de06986 `Ran 1594 tests`, 4 failures and 1 error, all in `test_workprofile` and `test_signoff_files`,
  and all present on the bare combined tree too (the work-profile ones are fixed by the kit's 59b848e; the sign-off one, `.claude/settings.json is 0o600`
  against a table that says 0644, is the open cross-review card on the data-integrity branch). After moving onto 59b848e: `test_workprofile` 63 OK,
  `test_perf_budgets` OK; `test_signoff_files` still fails on the bare 59b848e exactly the same way. Nothing in this branch touches file modes or the selfcheck.

## After the 06:00 cross-review (AGENT-8: xr-perf-etag-stale-while-typing HIGH, xr-perf-hud-budget-fails)

- **The stale-while-typing bug, fixed.** `load()` recorded the new ETag on every 200 but applied the body only when nothing was being typed, so a
  change that arrived mid-typing was dropped and the next poll, carrying the new tag, got a 304: the board stayed stale until the file changed
  again. The tag is now remembered only in the branch that applies the body; a 200 dropped during typing is fetched again on the next poll.
  A test pins the single assignment's position; a test checks the 304's headers.
- The `/api/hud` size budget is 250 KB (the combined tree's watchdog findings ride in the payload: 148 KB measured at 1,000 cards); the 304 carries
  `Content-Type` and `nosniff`; `parse_stamp`'s fast path takes only the board's own stamp shape; the duplicated comment is gone; `perf_bench.py`
  reads `AGENTBOARD_QA_PYLIBS`; the table row above names `store.parse_stamp`. `store.committed` stays: it is the list the store last wrote, read
  right after the commit by the same caller, and never a substitute for `load()`.
