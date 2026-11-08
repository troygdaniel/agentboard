# Overnight branches: cross-review for the morning (2026-11-08, 06:00 pass)

Reviewer: AGENT-8 (card `overnight-crossreview`), independent of the branch authors. Read-only on every branch; every suite ran from a
clean `git archive` of a tip, one at a time; render checks ran headless Chrome against throwaway boards; twelve read-only code reviews, each
claim checked against the code before it was kept. First pass 00:55 (18 tips), this pass 06:00 to 07:00 (21 tips, 14 more full suite runs, main c4aca6a).

## The short version (read this, then decide)

**ORCH's merge kit already did the merge for you, as a dry run.** `overnight/combined-11` (59b848e, 03:58) is every overnight branch merged
in a working order plus the cross-branch fixups, built by the kit on `overnight/overnight-morning-merge-kit` (script, per-branch
resolutions, the night's result table). Its suite: **1583 passed, 1 failed**, and the one failure is closed by `f23d1e8` on the sign-off branch
(see step 2). It renders exactly like main (12 of 16 views, the same four script-side false failures). Every HIGH and MEDIUM the first pass
found has a fix committed on its branch, and the fixes I could reproduce are in the combined tree (verified at 06:00: `init --demo` seeds the
right board, the selfcheck canaries are documentation addresses, `stop` checks the pid is an agentboard server, the agent instructions tell
agents to report a stuck card rather than release a peer's claim).

**Recommended morning path:**

1. Merge `overnight/combined-11` onto main (clean trial merge; main gained one commit since its base, c4aca6a, which auto-merges).
2. Then, in this order, the five small branches that sit **on top of** combined-11 (each merges clean onto main):
   `overnight-sec-signoff-pack` f23d1e8 (the one failing test's fix) → `overnight-rel-server-lifecycle` 4359186 (its stop/pid fix is in) →
   `overnight-agent-prompts` 63909aa (after a README line) → `overnight-config-validation` 580059f (**after the HIGH below**) →
   `overnight-perf-scale` fd03e24 (**after the HIGH below**; CHANGELOG conflict with lifecycle, keep both).
3. Two decisions that are yours, not the review's: the **Python 3.9 floor** (install-quickstart, inside combined-11 already) and the
   **hold check** (protocol-3, inside combined-11 already: `update`/`review`/`ask` refused on a card another agent holds). Both are sound
   and tested; both change what every user sees. If you want either out, the kit's per-branch resolution files say how to drop it.
4. One housekeeping question: every branch ships its evidence under `docs/overnight/` in the public repo (agents, worktrees, the night's
   workflow). `publiccheck` is clean; decide once whether that folder belongs in the public tree.

**New since 00:55 (reviewed this pass):** three branches landed on top of the combined tree after 00:30 and are not in the kit's order:
`config-validation` (**HIGH**: `agentboard config show` prints `[redact] extra` patterns, `[knowledge]` paths and plugin strings verbatim),
`perf-scale` (**HIGH**: the page records the new ETag while a reply box holds the render, then gets 304 and stays stale until the next
change; its own size-budget test also fails), `agent-prompts` (README still quotes the old wording). Five cards filed; all three are
MERGE AFTER FIX.

**Cards:** 24 `xr-*` in all; 19 from the first pass are fixed on their branches (each status line says where), 5 from this pass are open.

## One row per branch (06:00 tips)

| Branch (tip) | What it does | Suite (clean archive) | State at 06:00 | Recommendation |
|---|---|---|---|---|
| `combined-11` (59b848e) | The kit's merge of every branch below plus cross-branch fixups (selfcheck tables, repoguard) | 1583 passed, 1 failed (`test_signoff_files` settings mode; fixed by f23d1e8) | clean onto main c4aca6a; renders like main | **MERGE** (step 1) |
| `overnight-morning-merge-kit` (2ff9318) | The kit itself: `docs/overnight/merge-kit.sh`, per-branch resolution files, dry-run notes and result tables | 1305 passed | clean onto main; docs and scripts only | MERGE (the record of how combined-11 was made) |
| `overnight-sec-signoff-pack` (f23d1e8, AGENT-8) | Two-page sign-off, network guard in the suite, file-table test, doctor `masking` line; f23d1e8 fixes the table for `write_settings` (existing mode kept, 0600 when created) | 1588 passed on combined + fix | one commit on combined-11, clean onto main | MERGE (step 2; author's view) |
| `overnight-rel-server-lifecycle` (4359186) | `status`/`stop`/`restart`, `serve --background`, graceful SIGTERM, `/api/health` | 1591 passed at 4359186 (+ the one settings-mode failure every combined-based tip shares until f23d1e8 lands) | fix for `xr-lifecycle-stop-any-pid` landed (71cf43b: `ps` check, no proxy, rolled log); four commits on combined-11 | **MERGE** (step 2) |
| `overnight-agent-prompts` (63909aa) | `rules.py`: one source for every agent prompt (wait block, working rules, report rule), a test that the surfaces agree | 1620 passed at 63909aa (+ the shared settings-mode failure) | hold, watchdog, subtasks and standing-wait rules survive verbatim; README still quotes `--force to override` and `--wait 120` (`xr-prompts-readme-stale`) | **MERGE AFTER FIX** (one README line) |
| `overnight-config-validation` (580059f) | `configschema.py`, `agentboard config show/check/docs`, invalid values fall back to defaults, plugins register sections | 1598 passed at 580059f (+ the shared settings-mode failure) | **HIGH** `config show` prints secret-bearing strings (`xr-config-show-prints-secrets`); **MEDIUM** false WARN on the real `providers.label` key and `import tomllib` in tests against the 3.9 floor (`xr-config-check-label-and-tomllib`) | **MERGE AFTER FIX** |
| `overnight-perf-scale` (fd03e24 reviewed; tip moved to 25112c6 at 06:2x, see note) | Per-board derived cache keyed on a stat per request, sha1 ETag with 304 on the polled routes, faster HUD stamp parsing, no re-read after a commit, a Todo fold past 200 cards, budgets in a test | 1591 passed at 25112c6 (+ the shared settings-mode failure); the HUD size-budget test passes there, so that card looks fixed | **HIGH** stale board after typing (`xr-perf-etag-stale-while-typing`, one-line fix); **MEDIUM** `test_perf_budgets` fails on its own tree (`xr-perf-hud-budget-fails`); cache freshness across processes reproduced OK; guards intact; HUD output byte-identical | **MERGE AFTER FIX** |
| `overnight-ux-doctor-agents-line` (d9d463a, UX stack tip; carries firstrun, init-agent-instructions, nav-and-panel-words) | Welcome and guided `init` with sample cards, `init --instructions`, plain tooltips, `doctor` agents line | 1265 passed (d9d463a) | the HIGH (`init --demo` wrong board) and both MEDIUMs (AGENTS.md mode, symlink) fixed in 13aede6 / fb05ed4 and verified in combined-11 | in combined-11 |
| `overnight-rel-agent-protocol-3` (9b2c907; carries -1 and -2) | Watchdog (nine stuck states, one fix each; strips on Load and Board; doctor line) and the hold check | 1261 passed (9b2c907) | all four cards fixed (872b073, 5537221, 9b2c907): `--fix all` finishes, strip reads at phone width, agents report instead of releasing, the hold rule is in the instructions and ORCH's prompt | in combined-11; **the hold check is your decision** |
| `overnight-rel-data-integrity` (b5b4d66) | `statefile.py` atomic state files, recovery hints, `verify` restore test and `--fix` | 1284 passed (b5b4d66) | rebased by its author onto main; uses main's `cursors.py` and `write_settings`, so the HIGH (cursor regression) and the settings-mode MEDIUM are closed | in combined-11 |
| `overnight-sec-workpc-profile` (3f1d46a) | Work profile switch wired through the master lock, `selfcheck` (+ `--live`), connection cap, nosniff, JSON-bomb 400, report symlink 404 | 1332 passed (3f1d46a) | all three MEDIUMs fixed in 3f1d46a (honest counts, documentation-range canaries, profile source reported) | in combined-11 |
| `overnight-install-quickstart` (7d15096) | Python 3.9 to 3.14 (`tomlread.py`, a possessive-quantifier shim), install/upgrade/uninstall docs, doctor defers to the masker | 1293 passed (7d15096) on 3.13; redact + tomlread tests pass on 3.9 | rebased onto main 33ecb3e; both MEDIUMs fixed (shim is a tokenizer; masker shapes from main) | in combined-11; **the 3.9 floor is your decision** |
| `overnight-qa-cleanroom` (350195a) | Manual QA tools (`tests/qa/`), random-order runner, QA report and screenshots | 1341 passed (350195a) | `rm -rf` guard landed (e88422e); `render_check`'s `/#summary` view still 404s on every build (LOW, in the card) | in combined-11 |
| `visual-polish-3-audit-and-fix-the-views` (0c6f531; carries ux-visual-polish) | CSS polish, phone header three rows, report and summary contrast | 1205 passed (0c6f531) | summary link colour fixed (0c6f531) | in combined-11 |
| `overnight-docs-architecture` (a2687ad) | ARCHITECTURE.md, CONTRIBUTING.md, documents index, a test that pins the module list to the code | 1294 passed (a2687ad) | rebased onto main 33ecb3e; `chatwake.py` row and field names fixed (both cards) | in combined-11 |

## Conflicts

- Onto main c4aca6a: `combined-11` and all five branches on top of it merge clean. The standalone tips (protocol-3, workpc, UX stack,
  polish-3, docs-architecture, install-quickstart) conflict with main only in files the combined tree already resolved (CHANGELOG, doctor.py,
  cli.py, index.html, redact.py); that is why the path is "merge combined-11", not the branches one by one.
- Between the five on top: `perf-scale` x `rel-server-lifecycle` conflict in CHANGELOG only (both add an Unreleased section; keep both);
  server.py auto-merges (both add the same `import os`). The others are disjoint.
- The first pass's pairwise map (which branch touched which shared file) is in the kit's resolution files and in the 00:55 version of this
  document (`git log -- docs/overnight/review-summary.md` on this branch).

## Render checks (headless Chrome, 1440 and 390 wide, light and dark, throwaway boards)

Every build checked (main, the UX stack, polish-3, workpc, protocol-3, **combined-11**) gives 12 of 16 views clean with no console error or
overflow of its own; the four "failures" on every build are the QA script's `done-summary` URL (`/#summary`, read by the page as a card id,
404 on `/api/task`) and a pre-existing 10 px span. `combined-11` answers `/api/health` 404 because the lifecycle branch sits on top of it.

## Bugs filed (all `xr-*`, Todo; the status line on each says where the fix landed)

- Fixed on their branches and verified or re-tested at 06:00 (19): `xr-firstrun-demo-wrong-board` (HIGH), `xr-reldata-cursor-regression` (HIGH,
  closed by the author's rebase), `xr-docs-architecture-fails-main` (HIGH), `xr-init-instructions-agents-md-mode`, `xr-init-instructions-symlink`,
  `xr-workpc-profile-off-message`, `xr-workpc-selfcheck-live-canaries`, `xr-workpc-selfcheck-overclaims`, `xr-reldata-settings-mode`,
  `xr-polish3-summary-link-colour`, `xr-qa-rm-rf-unguarded`, `xr-watchdog-fix-all-aborts`, `xr-watchdog-strip-narrow`,
  `xr-watchdog-agents-may-release`, `xr-install-redact-resolve-main`, `xr-install-strip-possessive`, `xr-protocol3-env-only-undocumented`,
  `xr-docs-architecture-field-names`, `xr-lifecycle-stop-any-pid`.
- Open, from this pass (5): `xr-config-show-prints-secrets` (HIGH), `xr-perf-etag-stale-while-typing` (HIGH), `xr-config-check-label-and-tomllib`,
  `xr-perf-hud-budget-fails`, `xr-prompts-readme-stale`.

## How this was done

- Inventory: `git branch --list "overnight/*"`, each tip's merge base and distance from main, at 00:30 and again at 05:55.
- Trial merges: `git merge-tree --write-tree` of every tip onto main, and of each pair of branches on their own merge base (first pass).
- Suites: `PYTHONPATH=src python -m pytest -q` in a `git archive` copy of each tip, one at a time (29 full runs over the night). Every
  tip based on combined-11 shares one failure, `test_signoff_files` settings mode, which f23d1e8 closes; nothing else failed.
- Render checks: the QA branch's `tests/qa/render_check.py` against `agentboard serve` of each build on a seeded throwaway board.
- Reviews: twelve read-only passes (one per branch or stack, three for the branches that landed after midnight), each finding reproduced or
  read in the code before it was kept; the fixes for the first pass's HIGHs were re-verified in the combined tree by hand.
