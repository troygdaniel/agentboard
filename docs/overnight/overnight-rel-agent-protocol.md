# Overnight reliability: the agent protocol heals itself

Branch `overnight/overnight-rel-agent-protocol` (public repo, not merged; Troy reviews). AGENT-5, Nov 8 night. Card `overnight-rel-agent-protocol`.

## What changed

- **One watchdog for the ways a board gets stuck between agents** (`src/agentboard/watchdog.py`, new). `findings()` reads the board
  once and names each case with the one fix that puts it right; `heal()` does one fix, on a click or a flag, and writes one history
  line marked "the watchdog, for <owner>". Nothing happens unasked.

  | kind | what it means | the fix |
  |------|---------------|---------|
  | `stuck` | a Doing card idle past the stale threshold whose holder has no wait running (nothing wakes it) | release to Todo: history kept, holder cleared, open subtasks along |
  | `claimed-idle` | claimed, never worked (the last history line is still "Claimed by") and past the threshold | release to Todo |
  | `vanished` | an agent holding Doing cards with no wait running, no card update and no chat line past the threshold | release every one of its cards |
  | `twins` | two cards for one piece of work (`<id>` and `<id>-2`, same agent, same title) | merge the twin into its keeper (a named snapshot first) |
  | `split-card` | a Doing parent held by one agent with an open subtask held by another | hand the subtasks to the card's holder |
  | `orphan` | a subtask whose parent is not on the board | make it a card of its own |
  | `subtask-ahead` | a subtask in Doing while its parent is not | the subtask follows its parent's column |
  | `two-sessions` | two live sessions answer to one name (both wake on a line, both may answer) | none from the board: the line says to /rename one |
  | `no-session` | an agent holding Doing cards that never said who it is (`agentboard me`): the hooks cannot reach its session | none: the line says what to run |

  A card waiting on the owner (a question, a review) is never stuck; a holder with a wait running, or one that spoke in the chat
  inside the threshold, is never vanished (the HUD's own stale row already covers a quiet-but-listening card). The threshold is
  `[board].stale_minutes` (default 120), as for the rest of the board.
- **`agentboard watchdog`** lists the findings, numbered, each with its fix and the command that does it; `--fix N` (several: `1,3`;
  every one: `all`) does them and says what moved; `--json` for scripts; `--stale-minutes` to look sooner.
- **The Load view** shows the findings in a strip above the lanes, one row each with its button (`/api/hud` carries `watchdog`,
  `POST /api/watchdog-fix {action, id}` does one). A row with no board-side fix says what to run instead. The strip hides when the
  board is clean.
- **`agentboard doctor`** gains a `watchdog` line: `WARN 2 vanished, 1 claimed-idle, 1 twins: run agentboard watchdog for the list and
  the fixes`, or `PASS no stuck claim, twin, orphan or vanished agent on the board`.
- **A refused claim says the fix.** `X is already claimed by AGENT-3 (use --force)` is now `…: ask ORCH, or if AGENT-3 is gone run
  agentboard watchdog (it releases a stale claim) and claim again; --force takes it over as it stands`.

## Before and after

| | before | after |
|---|---|---|
| an agent dies holding three cards | three red "abandoned?" cards until someone edits each by hand | one row on Load, one click releases all three with their history |
| a card claimed and forgotten | sits in Doing at 5% | `claimed-idle` row, release; or `agentboard watchdog --fix 1` |
| `start` twice made `card` and `card-2` | `agentboard dedupe` if you knew to run it | the `twins` row, one click merges |
| a second agent took a subtask with `--force` | two agents report on one card, the parent's % lies | the `split-card` row, one click hands the subtasks back |
| a parent deleted under its subtasks | updates on the subtask are refused forever | the `orphan` row, one click makes it a card |
| two sessions named AGENT-1 | both answer every line | the `two-sessions` row says to /rename (the chat shows the same chip) |
| `doctor` | nothing about the protocol | a `watchdog` line |

## How to try it

```
PYTHONPATH=src:tests python3 -m unittest tests.test_watchdog                       # 13 tests: every kind, every fix, the CLI, the API, doctor, the page
agentboard watchdog                                                               # on any board; --fix N does one, --json for scripts
agentboard doctor | grep watchdog
python3 - <<'EOF2'
# a throwaway board with a claim nobody worked for three hours
import tempfile, pathlib
from datetime import datetime, timedelta
from agentboard.store import Store
from agentboard import watchdog
d = pathlib.Path(tempfile.mkdtemp()) / ".agentboard"; d.mkdir(); s = Store(d)
s.add("Queued work", task_id="queued"); s.claim("queued", "AGENT-2")
with s.transaction() as tasks:
    tasks[0]["updated"] = tasks[0]["log"][-1]["at"] = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
for f in watchdog.findings(s): print(f["kind"], f["id"] or f["agent"], "->", f["fix"] and f["fix"]["label"])
print(watchdog.heal(s, "release", "queued"), s.load()[0]["status"])
EOF2
```

Load view with the strip (throwaway board, made-up cards): `overnight-rel-agent-protocol-light.png`, `-dark.png`, `-narrow.png`.
In the headless-Chrome check the strip listed vanished, stuck, claimed-idle, split-card, twins and two-sessions rows; one click on
"Release to Todo" moved the card, its history line reads "Released to Todo: AGENT-3 had no wait running…", and the stuck row left.

## Test runs

- `tests/test_watchdog.py`: 13 tests OK (under a second).
- Full public suite on this branch: 1248 passed, 1 failed (01:15 on Nov 8): the one failure was `test_load_align`, which pins the
  HUD's exact markup and did not know the strip; it is updated in the branch's second commit and passes alone and in the follow-up
  branch's run.
- `python3 tests/publiccheck.py`: 0 findings.

## Risks

- A release is a judgement from the clock and the listener file: an agent that works for two hours without touching its card, with no
  wait running and no chat line, reads as vanished. The fix is one click away, never automatic, and the card keeps its history; the
  agent's next `update` on a released card is refused by the existing "not in Doing" rule, which tells it to claim again.
- `vanished` and `stuck` overlap on purpose (one row per agent, one per card): the agent row is the one-click for all of them.
- `merge` reuses `store.merge_twin` (what `agentboard dedupe --apply` runs) and takes a named snapshot first; `release` writes through
  the same transaction as every other board change.
- No change to the board file format. The HUD strip is new markup in `index.html` (`#h-dog`) and three CSS rules; it is hidden when
  there is nothing to show, so a clean board looks as before.

## After the cross-review (AGENT-8, cards xr-watchdog-fix-all-aborts, xr-watchdog-strip-narrow)

- `watchdog --fix all` no longer ends in an error when a vanished agent's release-all already covered its stuck rows: those rows print
  "already done" and the run goes on; `--fix abc` is refused with the accepted forms, on a clean board too.
- The strip's rows no longer shrink and overprint at phone width: each row is `flex: none`, and under 720px it is a two-line grid (kind and
  button, then the sentence). The three screenshots are re-shot from a throwaway board, the light one in the light theme this time; the
  narrow check asserts no two rows overlap.
- README has a `watchdog` paragraph beside `dedupe`; the CHANGELOG says `doctor --strict` exits 1 while a claim is stale.

## Not done (candidates for a next card)

- The board page (not only Load) could carry the same strip under the Doing header.
- A `lost session` in the strict sense (a session id in `sessions.json` whose transcript file is gone) is not reported; the hooks
  survive it, so nothing breaks, but the Terminal tab goes quiet without a word.
- The watchdog does not run on a timer; it runs when Load is open (every second with the HUD poll) and on `doctor`/`watchdog`.
