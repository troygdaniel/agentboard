# Merge kit: the night's dry run (Nov 8, 01:50; the 06:00 pass is appended below)

`docs/overnight/merge-kit.sh --repo ~/dev/agentboard` in a throwaway clone, trial branch from `main` = c11a6e7, AGENT-8's order
(`review-summary.md` on `overnight/overnight-crossreview`), tips as of 01:40. Nothing in the live checkout or any board was touched.

## Result table

| # | branch (tip) | merged | conflict | resolved by |
|---|---|---|---|---|
| 1 | `overnight-ux-visual-polish` (0fe00d3) | yes | none | clean |
| 2 | `visual-polish-3-audit-and-fix-the-views` (0c6f531) | yes | `index.html`, one line (the thread head: main's `N sessions` chip vs the branch's markup) | `merge-kit-resolutions/visual-polish-3-audit-and-fix-the-views.py`: the branch's line with the chip put back after the name |
| 3 | `overnight-sec-signoff-pack` (de183ef) | yes | `CHANGELOG.md` | the kit (both sections, the branch's first) |
| 4 | `overnight-qa-cleanroom` (e88422e) | yes | none | clean |
| 5 | `overnight-ux-doctor-agents-line` (d9d463a, UX stack tip) | yes | `cli.py` (store import line + `demo as demolib`), `doctor.py` (`run()`: `check_stop_hook` vs `check_agents`) | `overnight-ux-doctor-agents-line.py`: union of the import names, both check calls in main's order |
| 6 | `overnight-sec-workpc-profile` (1d7887a) | yes | `cli.py` (parser setup: `_Parser` vs `profilelib.apply()`; the `init` block vs `--profile`, `profile`, `selfcheck`), `server.py` (import line) | `overnight-sec-workpc-profile.py`: main's parser lines after the branch's `profilelib.apply()`; main's `init` block then the branch's flags and subcommands; both imports |
| 7 | `overnight-rel-agent-protocol-2` (5537221, carries -1) | yes | `CHANGELOG.md` | the kit |
| 8 | `overnight-rel-data-integrity` (b5b4d66) | yes | `cli.py` (`verify --fix` added where the `watchdog` subcommand block begins) | `overnight-rel-data-integrity.py`: the `--fix` line first (it belongs to `verify`), then the watchdog block |
| 9 | `overnight-docs-architecture` (a2687ad) | yes | `CHANGELOG.md`, `README.md` (two paragraphs at one spot) | the kit for CHANGELOG; `overnight-docs-architecture.py`: both paragraphs, main's first |
| 10 | `overnight-rel-agent-protocol-3` (9b2c907) | yes | `cli.py` (`cmd_update`: the branch's `by=` call vs the UX stack's out-of-range note) | `overnight-rel-agent-protocol-3.py`: the branch's call, then the note lines |
| 11 | `overnight-install-quickstart` (7d15096) | yes | `CHANGELOG.md`, `redact.py` (the branch swapped `re.compile` for its `_compile` shim on shapes main has since changed) | the kit for CHANGELOG; `overnight-install-quickstart.py`: main's shapes, compiled through the shim (AGENT-8's `xr-install-redact-resolve-main`) |

Not in the order (nothing ahead of main, drop the branches): `overnight-agent-prompts`, `overnight-perf-scale`. Not merged by design:
`overnight-crossreview` (AGENT-8's review, its own branch) and `overnight-morning-merge-kit` (this).

After every merge the page's script parsed and every module compiled (`--quick`). The full suite on the finished trial tip: see
"Test runs". Each conflict above was first resolved by hand in the clone and the resolution written down as the script the kit now
runs, so the morning's run is a rerun: `merge-kit.sh --repo ~/dev/agentboard --out docs/overnight/merge-kit-dry-run.md`.

## The combined tree: what breaks only when the branches meet (02:30)

Each branch's own suite is green; the first full suite on the finished trial tip ran **83 failed, 1469 passed**. Grouped:

| failures | cause | fix, and where it lives now |
|---|---|---|
| 76 (every chat send, `/api/chat` 500s, the work profile's live selfcheck) | `install-quickstart` replaces `import tomllib` with its reader in every module; code main added since its base (`store._roster`, from the f8 fixes) still says `tomllib.loads` and raises `NameError` | `merge-kit-resolutions/overnight-install-quickstart.py` now sweeps `tomllib.` to `tomlread.` in any module that imports the reader (same `loads()`, same `TOMLDecodeError`) |
| 2 | `docs-architecture` pins the module map against `src/`; seven other branches add modules (`agentfiles`, `demo`, `guards`, `profile`, `selfcheck`, `statefile`, `tomlread`, `watchdog`) | `_after_all.py`: one row each in `docs/ARCHITECTURE.md` |
| 1 | the same branch pins `docs/index.md` against `docs/*.md`; the sign-off pack adds `security-signoff.md` | `_after_all.py`: a row in the index |
| 2 | `sec-signoff-pack` pins its file table against what the board writes; main's chat-f7 added `chat-wake.json` | `_after_all.py`: the name joins the 600 state-file row |
| 1 | `install-quickstart`'s test wants no `import tomllib` outside the reader; `sec-workpc-profile`'s `selfcheck.py` has one | `_after_all.py`: `from . import tomlread as tomllib` |
| 1 | `test_doctor` caps the report at 20 lines; agents, watchdog, masking and profile each add one (21) | `_after_all.py`: the cap is 24 |
| 1 | **open:** the sign-off table says `.claude/settings.json` follows the umask (644); in the combined tree a new settings file is written 0600 | not papered over. AGENT-1 traced it (05:00): it is **main's** `hooks.write_settings` creating a new file 0600 (the board's private-by-default rule), against the sign-off pack's table and test, which say a project's own `.claude/settings.json` follows the umask. One line either way, and a product call: make `write_settings` respect the umask for a new file (the file is the project's, not board data), or change the table row and its test to 600. The morning picks; the kit does neither. **Closed at 04:40 by AGENT-8**: the sign-off pack's tip f23d1e8 (one commit on `combined-11`) changes the table row and its test to what `write_settings` does (an existing file keeps its mode, 0600 when agentboard creates it; `.orig` and `.bak` listed). The 05:30 run merges that tip after the eleven |

After the sweep and the fixups the combined suite is down to that one open item (the final count is in "Test runs"). The kit now runs
`_after_all.py` after the last merge as one more commit, "cross-branch fixups", and tests once more, so the table's last row is that
step.

## Rerun on the main of 04:00 (f360942) and the four branches that landed after the review

`main` took eight more merges after the first dry run (the LOWs, AGENT-1's receipts, `repoguard.py`, the By-agent fade, prefixed
subtask ids). The order replays the same way with two resolutions extended for `repoguard`: `sec-workpc-profile` now also meets main's
`doctor.py` import line (union plus the branch's `profile as profilelib`), and `install-quickstart` meets the deleted `_fake()` in
`doctor.py` (main's `repoguard` wins; the branch's edit to the deleted function is dropped). Eleven of eleven merge again.

Four `overnight/*` branches were not in AGENT-8's order because they landed after it (`overnight-agent-prompts` 8759582,
`overnight-config-validation` 8715841, `overnight-perf-scale` 868c90c, `overnight-rel-server-lifecycle` 1c25fde). The kit now appends
any such branch after the order. Against the fully merged trial tree each of them conflicts, and not in CHANGELOG alone:

| branch | conflicts with the merged tree | kind |
|---|---|---|
| `overnight-agent-prompts` | `prompt.py` 7 hunks, `hooks.py` 4, `agentchat.py` 1, `store.py` 1 (its `rules.py` import vs `statefile`) | the night's prompt wording (f1 to f8, the watchdog, the hold rule) on one side, one source for every prompt on the other: a rebase by its author, not a literal resolution |
| `overnight-perf-scale` | `server.py` 3, `index.html` 2, `store.py` 1, `hud.py` 1 | the ETag/304 routes and the derived cache meet tonight's server and page changes: the author's rebase |
| `overnight-config-validation` | `doctor.py` 2 (its `check_config_schema` beside main's `check_redact`; `run()`), `prompt.py` 1 (`tomllib` vs the reader) | small, but the `tomllib` side depends on whether `install-quickstart` is taken |
| `overnight-rel-server-lifecycle` | `cli.py` 2 (one is the whole `serve`/welcome block the first-run branch rewrote), `server.py` 1 (import line) | the first hunk needs a read of both sides: the author's rebase |

Recommendation: merge the eleven reviewed branches in the morning as above, then ask each of the four authors to rebase onto that
main (one command each, their suite, a new hash), and run the kit once more with those four in the order. Merging them blind on top
of the eleven is where the real conflicts are.

## The combined tree, published: `overnight/combined-11` (04:40)

At ORCH's ask the finished trial tree is a branch in the repo, `overnight/combined-11` at **59b848e** (main f360942, the eleven
reviewed branches merged with the resolutions above, the cross-branch fixups, and one more fixup for the work profile's selfcheck
tables, which enumerate the modules allowed to start a program and the POST routes: main's `repoguard.py`, `/api/demo` and
`/api/watchdog-fix` were missing). A branch only; main untouched; nothing pushed. Its full suite: **1 failed, 1582 passed** (the one
failure is the open settings-mode item). The authors of the four late branches rebase onto it tonight; the 05:30 kit run then merges
the eleven and the rebased four in one pass.

## The 04:25 full run: eleven plus the four rebased late branches, a suite after each merge

All four late branches were rebased onto `combined-11` by 04:20 (agent-prompts 63909aa, config-validation 580059f, perf-scale fd03e24,
server-lifecycle 6f2bb0d), so the full run started then instead of 05:30. Per merge (main f360942 as the base):

| step | branch | suite after the merge |
|---|---|---|
| 1, 2 | ux-visual-polish, visual-polish-3 | 1332, 1346 passed |
| 3 | sec-signoff-pack, **which by then sat on combined-11** (59b848e) | 1586 passed, 1 failed: the settings-mode item. Because the tip carried the whole combined tree, steps 4 to 11 read "nothing ahead" (the kit now merges a branch based on combined-11 after the rest; the per-branch resolutions were exercised in the 01:50 and 04:00 passes) |
| 13 | agent-prompts 63909aa | 1623 passed, 1 failed (the same item) |
| 14 | config-validation 580059f | 1638 passed, 1 failed (the same item) |
| 15 | perf-scale fd03e24 | 1644 passed, 1 failed (the same item); CHANGELOG by the kit |
| 17 | server-lifecycle 6f2bb0d | **13 failed**, 1641 passed: every `GET /api/hud` answers 500 |

The one real cross-branch bug of the night: `server-lifecycle`'s `/api/health` route does `import os` inside the GET router; `perf-scale`
imports `os` at the module top and calls `os.stat` earlier in the same function, so the local import makes `os` a function local there and
`/api/hud` raises `UnboundLocalError`. Fix: one line on the lifecycle branch (drop the local import; `os` is imported at the top). **Landed at 05:05 as
`overnight-rel-server-lifecycle` 4359186** (AGENT-1); `_after_all.py` carries the same change as a stopgap and does nothing once that tip is in. The run itself then tripped over a
bash 3.2 parse quirk in the kit's own summary (parentheses inside a command substitution), fixed in 415e78e; the table above is from
its log.

The settings-mode item is closed by the sign-off pack's f23d1e8 (the table row now says what `write_settings` does).

## What the morning still decides (from AGENT-8's review, unchanged by this)

- `overnight-rel-agent-protocol-3` is a protocol change (reports only on the card you hold): merge with -2, or merge -2 alone.
- `overnight-install-quickstart` lowers the Python floor to 3.9: Troy's call; the merge is mechanical once decided.
- `overnight-ux-firstrun`'s HIGH (`init --demo` seeds the wrong board) and the other `xr-*` fixes: the kit merges the branch tips as
  they are at run time; a fix that lands on a branch before the morning is picked up by the rerun.
- Whether `docs/overnight/` belongs in the public tree.

## Test runs

- The kit, quick mode, 01:50: 11 of 11 merged, page script parses after each, every module compiles.
- Full suite on the finished trial tip, before the sweep and the fixups: 83 failed, 1469 passed (02:10). After the `tomllib` sweep: 6 failed, 1546 passed (02:25). After `_after_all.py`: **1 failed, 1551 passed** (02:45): the one open item above, `test_signoff_files` on the mode of `.claude/settings.json`.

## How to run it in the morning

```
cd ~/dev/agentboard && docs/overnight/merge-kit.sh --repo ~/dev/agentboard --out /tmp/merge-kit-table.md      # about an hour with suites
docs/overnight/merge-kit.sh --repo ~/dev/agentboard --quick                                                   # a few minutes, no suites
```

Then the real merge on the live checkout is the same eleven `git merge --no-ff` in this order, with
`python3 docs/overnight/merge-kit-resolutions/<slug>.py .` at each conflict the table names, and the CHANGELOG rule by hand (both
sections, the branch's first). Any new conflict the kit did not see stops it with the files, the hunks and a suggestion.
