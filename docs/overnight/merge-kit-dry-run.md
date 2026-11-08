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

## What the morning still decides (from AGENT-8's review, unchanged by this)

- `overnight-rel-agent-protocol-3` is a protocol change (reports only on the card you hold): merge with -2, or merge -2 alone.
- `overnight-install-quickstart` lowers the Python floor to 3.9: Troy's call; the merge is mechanical once decided.
- `overnight-ux-firstrun`'s HIGH (`init --demo` seeds the wrong board) and the other `xr-*` fixes: the kit merges the branch tips as
  they are at run time; a fix that lands on a branch before the morning is picked up by the rerun.
- Whether `docs/overnight/` belongs in the public tree.

## Test runs

- The kit, quick mode, 01:50: 11 of 11 merged, page script parses after each, every module compiles.
- Full suite on the finished trial tip (626e242 in the hand-resolved clone, identical content to the kit's 316a284): appended below.

## How to run it in the morning

```
cd ~/dev/agentboard && docs/overnight/merge-kit.sh --repo ~/dev/agentboard --out /tmp/merge-kit-table.md      # about an hour with suites
docs/overnight/merge-kit.sh --repo ~/dev/agentboard --quick                                                   # a few minutes, no suites
```

Then the real merge on the live checkout is the same eleven `git merge --no-ff` in this order, with
`python3 docs/overnight/merge-kit-resolutions/<slug>.py .` at each conflict the table names, and the CHANGELOG rule by hand (both
sections, the branch's first). Any new conflict the kit did not see stops it with the files, the hunks and a suggestion.
