# Overnight reliability: the watchdog on the Board page too, and in the prompts

Branch `overnight/overnight-rel-agent-protocol-2` (public repo, not merged; Troy reviews), stacked on
`overnight/overnight-rel-agent-protocol`. AGENT-5, Nov 8 night. Card `overnight-rel-agent-protocol-2` (filed as the next best
improvement in the same area, per the overnight rules).

## What changed

- **The Board page shows the watchdog's rows under the Doing header**, the same rows and one-click fixes as the Load view's strip, and
  nothing at all when the board is clean. `/api/tasks` carries `watchdog` only when there is something to show, so the Board's
  one-second poll costs nothing on a clean board beyond one extra read. A click fixes, then both strips redraw on their next poll.
- **ORCH's standing prompt** gains one line next to `list --stale`: `agentboard watchdog  # a card looks stuck? every way the board
  is stuck between agents, each with its fix (--fix N)`.
- **`agentboard instructions`** (what every agent reads) gains a short paragraph under Dependencies: a stuck card is for the watchdog,
  and never `--force` past another agent's claim to get moving: release it through the watchdog or ask the orchestrator, so the
  history says what happened.

## Before and after

| | before | after |
|---|---|---|
| a stuck card, seen from the Board | a red "abandoned?" card; the fix was on Load, or by hand | the row and its button sit above the Doing cards |
| ORCH meets a card that looks stuck | `list --stale`, then hand edits | one command with the fix per line |
| an agent meets a claimed card | the refusal said `--force` | the refusal and the instructions say to release it properly |

## How to try it

```
PYTHONPATH=src:tests python3 -m unittest tests.test_watchdog                       # 17 tests incl. the Board page, the tasks feed, the prompts
agentboard instructions | grep -A2 watchdog
agentboard serve                                                                  # on a board with a 3-hour-old claim: the rows show under Doing
```

Board page with the strip (throwaway board, made-up cards): `overnight-rel-agent-protocol-2-light.png`, `-dark.png`, `-narrow.png`.
In the headless-Chrome check the rows listed vanished, stuck, claimed-idle, split-card, twins and two-sessions; one click on
"Release to Todo" moved the card and the stuck row left; no horizontal overflow at 390 px.

## Test runs

- `tests/test_watchdog.py`: 17 tests OK.
- Full public suite on this branch: **1257 passed, 0 failed** (01:40 on Nov 8, `PYTHONPATH=src .venv/bin/python -m pytest -q`).
- `python3 tests/publiccheck.py`: 0 findings.

## Risks

- The Doing column is narrower than the Load strip; long rows are cut with an ellipsis and carry the full text in their tooltip; on a
  narrow screen they wrap. The strip is capped at a fifth of the viewport and scrolls.
- `/api/tasks` now reads the chat log and the listener and session files once per poll when the board has findings; on a clean board
  it reads them once to learn there are none. That is the same cost `/api/hud` already paid every second with Load open.

## After the cross-review (AGENT-8, card xr-watchdog-agents-may-release)

- The agent instructions no longer tell an agent to release a peer's claim: a stuck card is reported to the orchestrator in one chat line,
  and the fix is ORCH's or the owner's; `--fix` on another agent's claim and `--force` past one are both named as things an agent never
  does. An agent's own rows (its orphan subtask, a twin it made) it may fix itself. ORCH's prompt keeps the `--fix` hint.
- `/api/tasks` no longer runs the watchdog's pass on every one-second poll: the findings are cached per board for 5 seconds
  (`server._watchdog_cached`), and a fix through `/api/watchdog-fix` drops the cache so the next poll is current.

## Not done

- A `--watch` mode for the CLI, and a nightly line in the review ("the watchdog released N cards this week"), could follow.
