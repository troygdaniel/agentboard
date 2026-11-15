# Agent status: design

Design only. Nothing here is built and nothing will be until the owner approves it (card `agent-status-visibility`). The mock-up is
[status-visibility-mockup.html](status-visibility-mockup.html) (captures: [light](status-visibility-light.png), [dark](status-visibility-dark.png),
[narrow](status-visibility-narrow.png)); every name, count and time in it is made up.

## After the owner looked at slice 1 (Nov 14)

Decision 1 changed once there was something to look at. The first draft replaced Watch's tiles with a row per agent under a strip of five counts; the owner liked the calm of the second draft
(one state word, detail on hover, room) and asked for **Watch to keep its 3x3 tiles and for the strip of counts to go**. So slice 1 is: one state word in one colour on each tile, the
"heard" line on hover, a tint on each tile in the hue of its word (asked for on seeing it: the first pictures looked too alike), and the one quiet board-asleep line. The rows, the strip and the six-hour strips below describe the design as approved; the page now draws only the tile words and
the sleep line. The server still works out the counts and a row per agent (`status.py`) for the digest and the Ask box. The eight words must read the same for any kind of card; the track
under a card (slice 3) will be one per kind: a build (build, review, merged, gated, signed off), research or design (draft, review, signed off), an errand or a call (prepare, your approval, done).

## In one paragraph

Put **the answer to "is anyone waiting on me, what is stuck, who waits on whom?" on one page**, computed from facts the board already holds, so the
status check needs no human relay. Each agent gets one row: a state word from a short closed list, the card, where the card is in its life (six steps),
how long, and what it waits on. A strip of five numbers sits above the rows, and the things everyone shares (the test slot, merge, the gate) sit beside
them. Nothing new is asked of an agent. One rule fixes a false alarm the board raises today: **time the board itself was asleep never counts as silence.**

## Why (from the board's own data)

- **The ritual is the cost.** In three hours on 14 Nov (13:24 to 16:19) nine "status check from the owner" lines reached one agent. Each was answered with the card,
  the percent and the next step, all of which the board already held. The game retrospective counts 21 such checks over 40 hours, and ORCH wrote 279 chat lines (51%).
- **The board cannot tell a sleeping Mac from a gone agent.** At 20:11, just after the Mac woke (ORCH said so at 20:09), the roll-up listed three agents as *abandoned*
  (quiet 2h44 to 4h19). How much of that was the Mac sleeping the board cannot say: the state is computed from the card's age alone (`STALE_MIN` 10, `ABANDONED_MIN` 120
  in `hud.py`), so every sleep makes every agent look gone, and ORCH's own heads-up on 15:51 had to tell everyone not to trust the timeouts after one.
- **The states that matter are invisible.** Waiting for the one test slot was 30.8 hours in the retrospective (median 7.5 min, p90 48 min, longest 1.6 h), found only in test
  logs. Waiting for a merge, for a gate, or for the owner is spread over chat, git and the card log. Percent and "doing" are all the board shows.

## What the owner sees

1. **One look** (five counters): Waiting on you · Stuck · Waiting on others · Working · Idle. Each has its oldest age. This replaces flipping Watch to Now and asking.
2. **Every agent, one row**: avatar and state word, the card and one line of what it says, a six-step track (Building, Tests, Review, Merged, Gated, Signed off) with the
   current step lit, and the time with who it waits on. A row waiting on the owner is tinted, the only tint on the page.
3. **The last six hours, one strip per agent**, coloured by state, with the **board-asleep** window hatched across every strip.
4. **What everyone shares**: the test slot (who holds it, who waits, how long, today's median), merge, the gate.
5. **Since you last looked**: three or four counted lines, and an Ask box ("what does echo need?") answered from the same data. This is the last slice.

## The states (a closed list of eight)

| State | Means | Comes from | Today |
|---|---|---|---|
| Working | open card touched in the last 10 awake minutes | `agentstates.agent_state` | yes |
| Silent | open card untouched 10 to 120 awake minutes; over that, *presumed gone* (today's "abandoned") | the same, with sleep taken out | the words yes, the sleep rule is new |
| In queue | waiting for a shared resource, and which one | a wait note from the project's test runner | new (slice 2) |
| Blocked | an unfinished `blocked_by`, and by what | the card's field | yes |
| Waiting on you | every open card is a question to the owner | `needs_input` | yes |
| In review | the card waits for sign-off, then merge, then the gate | `review` and the sign-off row | the first part; merge and gate are slice 3 |
| Idle | no card, a wait running (listening) | listeners | yes |
| Away | no card, nothing running | listeners | yes |

## The board-asleep rule

The server samples every minute (`agentstates.sample`) and writes a line at least every 15 minutes, so **a stretch with no lines is time the board was not watching**; that
is already in the module's own comment. The rule: when a sample finds that more than 3 minutes passed since the last, it writes one `asleep` line for the gap. Silent and
presumed-gone are then counted in awake minutes only (`updated` to now, less the asleep time). No agent is asked anything and there is no new field. A roll-up written after a wake would
show how much of each quiet stretch was the board asleep, and only the rest would count. Size: small, and it is the first thing to build.

## Build in slices (each is useful alone)

| Slice | What the owner gets | What it needs | Size |
|---|---|---|---|
| 1 | The one look and the agent rows with the eight states; the board-asleep rule | `agentstates`, the sign-off row, `blocked_by`: all built | M |
| 2 | The shared queues beside the rows, and the state *In queue* | `agentboard note wait <seconds> <lock\|rerun\|owner>` (insights capture 10), called by a project's test runner; the game's lock calls it | M |
| 3 | The six-step track | a merge stamp (`done --merged <hash>`, capture 7) and one event from the gate | S |
| 4 | The strip per agent for six hours, the digest and the Ask box | `agent-states.jsonl` (built) and a counted digest | M |

## What this does not do

No new notification (a push for state changes is a separate card), no change to chat, no new duty for an agent in slices 1, 3 and 4, nothing started or stopped by the
board. It does not make percent a single source of truth (the card's subtask mean stays what it is); that is its own, smaller card.

## Decisions for the owner

1. **Where does it live?** Recommended: **fold it into Watch** (the tile grid becomes these rows; Now and Map stay as they are). The alternative is a fourth page, which adds one more place to look.
2. **The eight state words**: are they the ones you want to read? (The mock-up uses them.)
3. **Board asleep never counts as silence.** Agreed? This alone stops a sleeping Mac from raising "abandoned".
4. **Queues**: a generic `agentboard note wait` that a project's test runner calls (recommended, one line in the runner), or no queue view at all?
5. **Order**: slice 1, then 2, 3, 4 as above, or stop after slice 1 and look?
6. **Since you last looked and the Ask box**: build them (slice 4) or leave them out?
