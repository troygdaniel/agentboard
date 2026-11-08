# Overnight reliability: an agent reports only on the card it holds

Branch `overnight/overnight-rel-agent-protocol-3` (public repo, not merged; Troy reviews), stacked on `-protocol-2`, on its own branch
so the first two can be taken without it. AGENT-5, Nov 8 night. Card `overnight-rel-agent-protocol-3` (the third improvement filed
in the agent-protocol area under the overnight rules).

## What changed

- **`update`, `review` and `ask` from a session that does not hold the card are refused, with the fix.** The CLI passes the
  session's name (`AGENTBOARD_NAME`, what every agent session carries) to the store; when the card is held by another agent the
  store answers: `export-pipeline is held by AGENT-3, not AGENT-9: claim it first (agentboard claim export-pipeline --name AGENT-9;
  that is refused while AGENT-3 has it in Doing, so ask AGENT-3 or ORCH), and if AGENT-3 is gone, agentboard watchdog releases it`.
  Nothing on the card changes.
- **Who is let through:** the holder (any case), ORCH, the owner (by name or "you"), a caller with no name (the server, the owner's
  plain shell), and any name on a card that has no holder. A subtask with no holder of its own answers to its parent's holder, so a
  second agent cannot report on the subtasks of someone else's card either.
- This is the first half of "two agents on one card": the watchdog's `split-card` finding (branch 1) catches the case after the fact
  (a subtask claimed with `--force` by a second agent); this one stops the quiet version, where the second agent never claims and just
  writes status lines, questions or a review on a card it does not hold.

## Before and after

| | before | after |
|---|---|---|
| AGENT-9 runs `agentboard update <AGENT-3's card> 40 "…"` | accepted; the card now carries two agents' stories | refused in one line that says what to do |
| AGENT-9 runs `agentboard review <AGENT-3's card> "done"` | the owner is asked to sign off work by the wrong agent | refused |
| ORCH writes a status line on any card | fine | fine |
| the owner, from the board or a shell with no name | fine | fine |

## How to try it

```
PYTHONPATH=src:tests python3 -m unittest tests.test_hold                           # 4 tests
AGENTBOARD_NAME=AGENT-9 agentboard update <a card AGENT-3 holds> 40 "mine now"     # refused, with the fix
AGENTBOARD_NAME=ORCH agentboard update <the same card> "a status line"             # fine
```

## Test runs

- `tests/test_hold.py`: 4 tests OK; `tests/test_core.py` and `tests/test_watchdog.py` unchanged and green.
- Full public suite on this branch: **1261 passed, 0 failed** (02:05 on Nov 8, `PYTHONPATH=src .venv/bin/python -m pytest -q`).
- `python3 tests/publiccheck.py`: 0 findings.

## Risks

- Any flow where one named session legitimately reports on another's card now needs ORCH's name or a claim. On this board the known
  one is ORCH closing or annotating cards, which is exempt; `agentboard edit --append` (a note by any name) is untouched. If Troy
  wants a softer rule, the check is one function, `_must_hold` in `store.py`, and the CLI's three `by=` arguments.
- The server's own calls pass no name, so the board page behaves as before.

## After the cross-review (AGENT-8, card xr-protocol3-env-only-undocumented)

- The rule is now written where agents read: `agentboard instructions` says you may only update, ask or review the card you hold, that
  the board reads the session's name from `AGENTBOARD_NAME` (so a session that only ran `agentboard me`, or a shell carrying a stale
  name, is judged by that variable), that ORCH and the owner are the exceptions, and that two sessions under one name both pass. ORCH's
  prompt carries the same sentence beside `update`. The CHANGELOG says the same and the bullet sits in its own place.
- The refusal names the column the card is really in (`while AGENT-3 holds it in Done that is refused`) instead of always "in Doing".
- Full public suite on the top of the stack after the four cross-review fixes (branches 1, 2 and 3 at 872b073, 5537221, eb43220): **1264 passed, 0 failed** (02:40 on Nov 8).

## Not done

- `claim --force` by a second agent is still allowed (it is the documented override) and lands in the watchdog's `split-card` row.
