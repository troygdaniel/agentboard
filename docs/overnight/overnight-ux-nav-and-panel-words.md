# Overnight: plain tooltips for the header, the ORCH pill and Copy prompt (overnight-ux-nav-and-panel-words)

Branch `overnight/overnight-ux-nav-and-panel-words` (worktree `~/dev/agentboard-on-ux3`), stacked on `overnight/overnight-ux-init-agent-instructions`
(which is stacked on `overnight/overnight-ux-firstrun`). Nothing merged, nothing pushed.

## What a first-time developer could not tell (the walk)

Header and card, as a person who has never seen the board (read from the page source and the rendered DOM; the browser extension dropped out
partway through the night, so the screenshots are headless Chrome and the checks are DOM reads):

| Control | Before | After (tooltip only; the label is unchanged) |
|---|---|---|
| **Board** tab | no tooltip | Every task in three columns: Todo, Doing and Done |
| **By agent** tab | no tooltip | One lane per agent: who is doing what |
| **Load** tab | no tooltip ("Load" of what?) | A live view of who is working and who is waiting on you (h) |
| **Later** button | no tooltip | Tasks parked for another day (l) |
| **Copy prompt** on a Todo card and in the card panel | no tooltip | Copy this task's instructions, to paste into an agent's terminal to start it (c) |
| **ORCH** pill | "Talk to ORCH" | Talk to ORCH, the coordinator session for this board |

Already fine and left alone: the Done column's Summary, Reports and Clear links, the report chip, the Later arrow on a card, the "No subtasks yet" flag
(its tooltip says agents add them as soon as they start a card), and every empty-state line (the first-run card rewrote the column ones).
I looked for more agents-only words in the empty states and the panel (Conversation, Terminal) and found nothing that a sentence does not already explain.

## Try it

    cd ~/dev/agentboard-on-ux3 && rm -rf build && pipx install . --force     # restart any running board
    agentboard demo && agentboard serve --port 8799                         # then hover the header

## Checks

- `tests/test_plain_tooltips.py` (7 tests): each tab and button has its words, the shortcut keys in them match the real keys, no tooltip uses ORCH, HUD,
  backlog or telemetry, the labels did not change, the Copy prompt words name what is copied and where it goes, the ORCH pill's accessible name is unchanged.
- 10 mutants (a tooltip removed, a tab renamed, "HUD" or "backlog" put back in a tooltip, the ORCH words reverted), all caught.
- Rendered DOM, headless Chrome on a throwaway board: the four header titles are on the live page.
- One existing pin updated on purpose: `test_byagent_drawer` expects the Later button's new `title`.
- Full suite and `python3 tests/publiccheck.py`: see the end of this file.

## Risks

Tooltips only: no label, layout or behaviour changes. A native tooltip appears after a hover pause and not on a phone; the 60-second tour (first-run branch) is the
same explanation for those.

- Full suite on this branch: **1241 tests, OK**; `python3 tests/publiccheck.py`: 0 findings.
