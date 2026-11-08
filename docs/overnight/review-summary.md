# Overnight branches: cross-review for the morning (2026-11-08)

Reviewer: AGENT-8 (card `overnight-crossreview`), independent of the branch authors. Read-only on every branch; each suite ran from a clean
`git archive` of the branch tip (nothing in anyone's worktree was touched); render checks ran headless Chrome against throwaway boards; eight
read-only code reviews, one per branch or stack, each claim checked against the code before it was kept. `main` moved all night (503e291 at
the first pass, b319e87 at the trial merges, 33ecb3e by the last review); the merge order below is against **main as of 00:55**, and the 06:00
pass re-checks every tip.

**First pass written 00:55 (every row complete: 18 branch tips tested, 8 reviews, 18 cards). The 06:00 pass re-checks every tip against the main of the moment and adds any branch that lands after this.**

## The short version

- **Merge first, no fix needed (4):** `overnight-ux-visual-polish`, `overnight-ux-nav-and-panel-words`, `overnight-sec-signoff-pack`
  (mine; judge it by its evidence files), `overnight-qa-cleanroom`'s report commit. Each merges clean onto main.
- **Merge after a small, named fix (7):** `visual-polish-3` (one colour token), `overnight-ux-firstrun` (**HIGH**: `init --demo` seeds the
  wrong board), `overnight-ux-init-agent-instructions` (file mode, symlink), `overnight-ux-doctor-agents-line` (carries the two above),
  `overnight-rel-agent-protocol` / `-2` (watchdog: `--fix all` aborts, strip unreadable on a phone, the instructions let agents release a peer's
  claim), `overnight-sec-workpc-profile` (live canary addresses, misattributed `profile off`, overclaiming selfcheck lines), `overnight-qa-cleanroom`
  (unguarded `rm -rf`).
- **Rebased during the night (1):** `overnight-rel-data-integrity` had a four-file conflict with main and a cursor rewrite behind main's
  `cursors.py` that would have **regressed chat receipts** (HIGH, card filed); its author rebased it at 00:43 and the new tip merges clean. The
  06:00 pass confirms the fix; then it is a plain MERGE.
- **Your call (1):** `overnight-install-quickstart` lowers the Python floor to 3.9 with a 409-line TOML reader and a regex shim; sound after
  two fixes and a careful rebase (its masker file is older than tonight's fixes), but whether agentboard should support 3.9 at all is a product
  decision, not a review one.
- **Protocol change, your call (1):** `overnight-rel-agent-protocol-3` refuses `update`/`review`/`ask` on a card another agent holds. Sound and
  tested, but the check reads `AGENTBOARD_NAME` only and no agent-facing text says it exists; merge with -2 after that sentence is added, or
  merge -2 alone if you want no behaviour change yet.
- **One question for every branch:** each ships its evidence under `docs/overnight/` in the public repo, naming agents, worktrees and the
  night's workflow. `publiccheck` passes (no private words), but decide once whether that folder belongs in the public tree or in the private notes.
- **Already on main, delete the branch (2):** `overnight-agent-prompts`, `overnight-perf-scale` (zero commits ahead).
- **Eighteen bug cards filed** (`xr-*`, Todo), one per finding, routed to the branch author in the title.

## One row per branch

| Branch (tip) | What it does | Suite (clean archive) | Risks found | Recommendation |
|---|---|---|---|---|
| `overnight-ux-visual-polish` (2fa3b56) | CSS polish: unique layer-checkbox ids (the Touch label named the wrong element), reduced-motion glow, 24 px targets, phone header three rows not four; evidence, before/after PNGs, audit tools | 1191 passed | Phantom 8 px row from an empty `#filter-summary` on phones (cosmetic); tests mostly grep the HTML; tools import from `/tmp/qa_pylibs` | **MERGE** |
| `visual-polish-3-audit-and-fix-the-views` (368e852, stacked on the above) | Report pages keep contrast (`--ac` 7:1), Reports list reads as titles, 24 px small controls | 1200 passed | `summary.py:384` still has the 4.4:1 link blue the audit flagged (card `xr-polish3-summary-link-colour`); `_title_of` doubles ": report" | **MERGE AFTER FIX** (one token) |
| `overnight-ux-firstrun` (4f3bcba) | Welcome, guided `init` (`--demo/--no-demo`, TTY-only prompt), `demo.py` sample cards, `POST /api/demo`, New task and ? buttons, 60 s tour | 1215 passed; 2 wall-clock masker tests fail only under load (old `LIMIT = 2.0` form, pass alone) | **HIGH** `init --demo` seeds the `AGENTBOARD_DIR`/`--board` board, not the one just created: reproduced, 12 `demo-*` cards landed on the other board (`xr-firstrun-demo-wrong-board`). Bare `agentboard` now exits 0 with a welcome (was 2) | **MERGE AFTER FIX** |
| `overnight-ux-init-agent-instructions` (ffc8fa3, stacked) | `init --instructions` appends the agent block to CLAUDE.md or AGENTS.md between markers; asks only on a TTY | 1232 passed | **MEDIUM** file written 0600 under the CLI's umask 077 (`xr-init-instructions-agents-md-mode`); **MEDIUM** both files symlinks: appends through the AGENTS.md link (`xr-init-instructions-symlink`) | **MERGE AFTER FIX** |
| `overnight-ux-nav-and-panel-words` (f8cf575, stacked) | Plain `title=` tooltips on tabs, Later, Copy prompt, ORCH pill | 1238 passed (with the tip below) | none | **MERGE** (with the stack) |
| `overnight-ux-doctor-agents-line` (ab0281c, stack tip) | `doctor` agents line (names from tasks.json, whether CLAUDE.md/AGENTS.md carries the block), helpers to `agentfiles.py`, `ux-index.md` | 1248 passed | carries the three fixes above; `doctor.py run()` conflicts with main: keep both `check_stop_hook` and `check_agents` | **MERGE AFTER FIX** (fix beneath, merge the tip only) |
| `overnight-rel-agent-protocol` (8aeb447) | `agentboard watchdog`: nine stuck states each with one fix; a strip on Load; a doctor line. Nothing runs on a timer: writes only on `--fix N` or a click | 33 targeted tests pass; full suite green at the -3 tip (1258) | **MEDIUM** `--fix all` aborts after doing its work when a released agent's row is healed twice (`xr-watchdog-fix-all-aborts`); **MEDIUM** strip rows overprint at 390 px (`xr-watchdog-strip-narrow`); `doctor --strict` now exits 1 on a stale claim; README silent | **MERGE AFTER FIX** |
| `overnight-rel-agent-protocol-2` (c955388, stacked) | The strip on the Board page too (shared code), a line in ORCH's prompt and in the agent instructions | 41 targeted tests pass; full suite green at the -3 tip (1258) | **MEDIUM** the instructions tell every agent it may `--fix` and release a peer's claim (`xr-watchdog-agents-may-release`); `findings()` runs on every `/api/tasks` poll, two tasks.json parses a second per tab | **MERGE AFTER FIX** (over -1) |
| `overnight-rel-agent-protocol-3` (4c82f03, stacked) | `update`, `review` and `ask` are refused for a card another agent holds; ORCH, the owner and nameless callers pass; server routes, the home plugin and the hooks mirror unaffected | 1261 passed (archive); 1320 OK merged onto main in a scratch copy | **MEDIUM** the evidence is `AGENTBOARD_NAME` alone (a `me --name` session passes, a stale env var is refused on its own card, two terminals with one name both pass) and no agent-facing text mentions the refusal (`xr-protocol3-env-only-undocumented`); CHANGELOG bullet spliced into the previous one | **MERGE AFTER FIX** with -2; or merge -2 alone tonight if no protocol change is wanted |
| `overnight-rel-data-integrity` (148e317 reviewed; **rebased by its author at 00:43 to b5b4d66 on main 5e7a929**) | `statefile.py` (atomic, flock'd state files), corrupt tasks.json names the good copy, stale `.tmp` sweep, `verify` restore test and `--fix` | 148e317: 1196 passed (2 wall-clock masker tests fail only under load, pass alone); b5b4d66: author reports 1287 OK, (06:00) re-run | On 148e317: **HIGH** cursor rewrite behind main's `cursors.py`, four-file conflict, branch side would collapse delivered/seen receipts (`xr-reldata-cursor-regression`); **MEDIUM** `.claude/settings.json` 0600 via mkstemp (`xr-reldata-settings-mode`). The rebased tip merges clean onto main and its evidence says it now uses main's `cursors.py` and `write_settings` as they are, which closes both; to be confirmed at 06:00 | **MERGE** after the 06:00 check of b5b4d66 (was: merge after fix) |
| `overnight-sec-workpc-profile` (76457b7) | Work profile (env, machine file or config) that sets the master lock and no-plugins and installs socket/subprocess guards; `selfcheck` (AST scan + in-process server flood) and `selfcheck --live`; connection cap 128 with 503, nosniff, JSON-bomb 400, report symlink 404 | 1219 passed (5df9a5a); 1227 passed (76457b7) | **MEDIUM** canaries dial `93.184.216.34` and `8.8.8.8` if the guard ever regresses (`xr-workpc-selfcheck-live-canaries`); **MEDIUM** `profile off` blames the environment after `apply()` rewrote it (`xr-workpc-profile-off-message`); **MEDIUM** PASS lines overclaim (`xr-workpc-selfcheck-overclaims`); `--live` delta clean | **MERGE AFTER FIX** |
| `overnight-sec-signoff-pack` (de183ef, AGENT-8) | Two-page sign-off, network guard in the suite, file-table test, load-aware timing tests (merged separately as 126513c), doctor `masking` line | 1239 passed | mine: not judged here; evidence in `docs/overnight/overnight-sec-*.md`; CHANGELOG conflict only | MERGE (author's view) |
| `overnight-qa-cleanroom` (a8f90f1) | Manual QA tools under `tests/qa/` (clean-room install, soak, headless render check, suite matrix), random-order runner, QA report and screenshots; its 3.11 fix is byte-identical to main's 6cc2742 | 1198 passed (816ab21 and a8f90f1) | **MEDIUM** `cleanroom.sh:5` and `soak.py:26` `rm -rf` argv[1] with no guard (`xr-qa-rm-rf-unguarded`); `tests/qa/pylibs/` not git-ignored; version hard-coded; `render_check`'s done-summary view opens `/#summary`, which 404s on every build including main | **MERGE AFTER FIX** (rebase drops the duplicate commit) |
| `overnight-install-quickstart` (cfdad0e) | Lowers `requires-python` to 3.9: `tomlread.py` (tomllib when present, a hand parser on 3.9/3.10), a `_compile` shim that strips possessive quantifiers on 3.9/3.10, README install/upgrade/uninstall/troubleshooting, doctor's key scan defers to the masker | 1212 passed on 3.13; the reviewer also ran the redact and tomlread tests on 3.9 (164 pass) | **MEDIUM** its redact.py predates 88712d4: the rebase must take main's shapes and add only the shim (`xr-install-redact-resolve-main`, resolution verified: 118 redact tests pass on 3.13 and 3.9); **MEDIUM** the shim rewrites `+` inside `[...]` and after `\` (`xr-install-strip-possessive`); tomlread diverges from tomllib in corners (TAB in strings, five-quote literals, invalid dates traceback); 3.10 never run; README's `pipx upgrade` prints already-at-latest while the version stays 0.3.1 | **Troy's call on the 3.9 floor** (409 parser lines for a 2021 Mac's system Python); if yes, MERGE AFTER FIX as a rebase; if no, keep README/doctor, drop tomlread and the floor |
| `overnight-docs-architecture` (0a7f287) | ARCHITECTURE.md, CONTRIBUTING.md, a documents index, a test that pins the module list, plugin API, command names and links to the code | 1244 passed on the branch; **the module-map test fails on today's main** (`chatwake.py`) | **HIGH** merging as-is turns main's suite red (`xr-docs-architecture-fails-main`); **MEDIUM** field names `parent` and `answer` do not exist (`parent_id`, `reply`), store's import list understated (`xr-docs-architecture-field-names`); the test does not check the data-file table, field names or lock discipline | **MERGE AFTER FIX** (add the chatwake row, fix the names, rerun on main) |
| `overnight-agent-prompts` (8b07a0d), `overnight-perf-scale` (ad37d9b) | nothing ahead of main | n/a | none | **DROP the branch** (already merged) |

## Merge order (safest first) and what each step must resolve

1. `overnight-ux-visual-polish` then `visual-polish-3` (after the one-token fix): both clean onto main; polish-3 contains polish.
2. `overnight-sec-signoff-pack`: CHANGELOG conflict only (keep both sections).
3. `overnight-qa-cleanroom` (after the `rm -rf` guard and `.gitignore` line): clean onto main; the rebase drops its duplicate 3.11 commit.
4. The UX stack, **tip only** (`overnight-ux-doctor-agents-line` ab0281c) after the HIGH and the two MEDIUMs are fixed beneath it: `doctor.py run()`
   conflict, keep both `check_stop_hook` (main) and `check_agents` (stack). Merging `overnight-ux-firstrun` alone would ship the HIGH.
5. `overnight-sec-workpc-profile` (after its three fixes): one conflict, the `doctor.py` import line (union). It also conflicts with the UX stack in
   `cli.py` and `server.py`, so whichever of 4 and 5 goes second must be rebased onto the other first.
6. `overnight-rel-agent-protocol-2` (after its three fixes; carries -1): CHANGELOG only. It conflicts with `rel-data-integrity` and `workpc` in
   `doctor.py`/`cli.py` family files, so rebase after 5.
7. `overnight-rel-data-integrity` **last**: its author rebased it at 00:43 (b5b4d66) and the four-file conflict is gone; the 06:00 pass confirms the
   cursor code is main's and the suite is green, then it merges clean. If anything still names `write_cursor` or `chat-cursors.json.lock`, stop.
8. `overnight-docs-architecture` only after the `chatwake.py` row is added and its test passes on main (today it fails there): CHANGELOG only.
9. Your two decisions: `overnight-rel-agent-protocol-3` (protocol change; with -2) and `overnight-install-quickstart` (3.9 floor; a careful rebase).

## Conflicts between branches (trial merges with `git merge-tree` on each pair's own base; stacked pairs skipped)

- `rel-data-integrity` conflicts with every branch that touches `agentchat.py`, `cli.py`, `hooks.py` or `listeners.py`: `rel-agent-protocol`
  (all three), `sec-signoff-pack`, `install-quickstart`, and `qa-cleanroom` (`listeners.py`). Hence last, as a rebase.
- `sec-workpc-profile` conflicts in `doctor.py` with `sec-signoff-pack`, `qa-cleanroom`, `rel-agent-protocol` and `ux-doctor-agents-line`, and in
  `cli.py` + `server.py` with the whole UX stack.
- `install-quickstart` conflicts in `redact.py` and `reports.py` with `qa-cleanroom`, `rel-agent-protocol`, `sec-signoff-pack`; and with main itself.
- `rel-agent-protocol` x `sec-signoff-pack`: CHANGELOG only.
- Clean with everything: `ux-visual-polish`, `visual-polish-3`, `docs-architecture` (CHANGELOG only).

## Render checks (headless Chrome, 1440 and 390 wide, light and dark, throwaway boards)

Script: the QA branch's `tests/qa/render_check.py` (console errors, failed loads, horizontal overflow, text under 11 px, unnamed controls)
over four views. **Every branch build matched main's baseline exactly: 12 of 16 views clean**, and the four "failures" are the script's own
`done-summary` URL (`/#summary`, which the page reads as a card id and 404s on `/api/task`) plus a pre-existing 10 px span, both present on main.

| Build | Views clean | New problems vs main |
|---|---|---|
| main 503e291 (baseline) | 12 of 16 | — |
| UX stack f8cf575, seeded board | 12 of 16 | none |
| UX stack f8cf575, empty board (welcome + tour visible) | 12 of 16 | none |
| visual-polish-3 368e852 | 12 of 16 | none |
| sec-workpc-profile 5df9a5a | 12 of 16 | none |
| rel-agent-protocol-3 4c82f03 (seeded board; my stuck-card seed did not trip the threshold, so the strip stayed hidden) | 12 of 16 | none with the strip hidden; the visible strip's narrow bug is the reviewer's reading of the branch's own PNG |

## Bugs filed from this review (all in Todo, routed to the branch author in the title)

HIGH: `xr-firstrun-demo-wrong-board`, `xr-reldata-cursor-regression` (closed by the author's rebase), `xr-docs-architecture-fails-main`.
MEDIUM: `xr-init-instructions-agents-md-mode`, `xr-init-instructions-symlink`, `xr-workpc-profile-off-message`, `xr-workpc-selfcheck-live-canaries`,
`xr-workpc-selfcheck-overclaims`, `xr-reldata-settings-mode`, `xr-polish3-summary-link-colour`, `xr-qa-rm-rf-unguarded`, `xr-watchdog-fix-all-aborts`,
`xr-watchdog-strip-narrow`, `xr-watchdog-agents-may-release`, `xr-install-redact-resolve-main`, `xr-install-strip-possessive`, `xr-protocol3-env-only-undocumented`, `xr-docs-architecture-field-names`.

## How this was done

- Inventory: `git branch --list "overnight/*"`, each branch's merge base with `main`, commits and `--stat`; repeated at 00:30 because four tips
  moved and four branches appeared during the pass.
- Trial merges: `git merge-tree --write-tree` of each branch onto `main`, and of each pair of branches on their own merge base.
- Suites: `PYTHONPATH=src python -m pytest -q` in a `git archive` copy of each tip, one branch at a time (two suites at once on this laptop
  trip the older 2.0 s masker timing tests; `main` has the load-aware form since 126513c).
- Render checks as above; code review: eight read-only passes, each verified against the code; the HIGH on `init --demo` and the live canary
  addresses were reproduced by AGENT-8 directly.
