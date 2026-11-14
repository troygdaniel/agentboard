# Insights: can the board recommend how to use its agents?

**Status: design only, nothing built.** Card `agentboard-recommend-improvements`, base `main` at `43de497`. Waiting on the owner's answers in "What I need decided".
First real dataset: the Long Haul retrospective (card `space-game-retrospective`, `docs/RETRO.md` in the game repo): 95 cards in 40 hours by seven agents and ORCH.

## What is asked

Can the board itself say, from what it records, how to revise its agents and their purposes: this agent waits a lot, cards of this kind go faster one way, split cards over this size, this file conflicts every time? Design first: what the board records now against what it should capture, how recommendations show, privacy (counts and timings only, local only, public-repo rules).

## What the retrospective showed (so the design starts from real numbers)

Measured from the board, its chat snapshots, git and test logs: median build 34 minutes but 10 of 87 cards over 3 hours were 48% of build hours; cards that named a blocker waited a median 3.1 hours for it (31 of 107); 27.4 of 42.5 between-card gap hours fell between midnight and 08:00; one test-list file was in 63% of conflicting merges; about 30.8 hours of runs queued for one shared lock; 2 of 4 bug cards were not game bugs. Each of these is a sentence the board could have said on day one. Each was also **reconstructed by a script after the fact**, and a few were guesses. That gap is the subject.

## What exists today (checked in the code and on the live board)

| Thing | Records | Used for | Gap the retro hit |
|---|---|---|---|
| Card log (`store._log`) | one timestamped line per event: added, claimed, started, ready for review, needs input, checkpoint, done, moved, title or description changed, blocked, sent back, restored, merged twin | the card's timeline (`summary.journey`), the HUD | events are free text; no reason, no actor on most; the log is the only history |
| `Added to ...` | when | queue time | **who made the card** (ORCH, the agent, the owner) is not on it; the retro guessed from the claim gap |
| `blocked_by` | the field, set by `add`, `start` and `edit` | the lock icon, claim refusal | `add` and `start` write **no log line**; only `edit` logs "Blocked by"/"No longer blocked" (1 and 5 lines on the whole board; 31 Long Haul cards had the field). When a blocker finishes the card unblocks at read time and nothing is logged. Blocked time had to be rebuilt from the blockers' done times. |
| `Sent back` (`store.send_back`) | the dedicated send-back, with the owner's note | the reply on the card | **0 uses on 2,878 cards.** Rework went through other paths: "Be simpler" replies (5), reopening by a move, a second "Ready for review". There is no one place that says "this came back, and why". |
| `learned` field, `## Learned` in a review body | the lesson | `rollup` | 1 of 116 Long Haul cards had one; `report` (96) and `body_md` (88) are there |
| Chat (`seq, at, sender, to, kind, topic, card, reply_to, via`) | every line | the chat panel, receipts | enough for counts, but the live file keeps **500 lines**; the retro rebuilt 547 from 53 hourly snapshots |
| Listeners and receipts (`chat-listeners.json`, `chat-delivered.json`) | who is waiting, what was delivered to which session, when | "listening", delivered/seen | state now, not history: nothing keeps "AGENT-2 was waiting for work from 02:10 to 06:40" |
| HUD (`hud.build`): working, quiet, abandoned, idle per agent | a live state | swimlanes, the stale flag | **not stored**: idle share per agent over a day cannot be read back |
| `summary` (the Done summary) | counts of cards by kind (`kind_of`, from the title) and work area | `/summary`, `agentboard summary` | deliberately "about the work, not the management of it": no timings, no waiting, no rework |
| `rollup`, `watchdog`, `wrapup` | right-now: what waits on the owner, what is stuck, what is next | ORCH's redistribution | present tense only |
| Model, size, test waits, merge time, files | **nothing** | | the model was read from commit trailers, size from lines changed in git, waits from test logs, merge time from git |

Takeaway: the card log is rich enough for the first half of what is wanted (queue, build, review, done, spec edits, re-reviews). The second half (blocked time, idle cause, rework reason, model, size, who made the card) needs a few small, specific captures.

## The proposal in one paragraph

Add a read-only **Insights** view that turns recorded facts into a short list of **observations**: each is one measured number with its sample size, a threshold, a plain sentence and a suggested change to how agents are used. It starts from what the board already has (phase 0), then adds the cheapest captures below, ranked by what they unlock. The board only **suggests**: it changes no prompt, role or card, and it never scores or ranks people. No machine learning: a small closed list of rules, each of which can be read, tested and switched off.

## Capture points, ranked by value for cost

Cost: XS = under an hour and a test; S = a few hours; M = about a day. "Unlocks" names the observation it makes exact.

| # | Capture | Cost | Unlocks | Needs agents to cooperate? |
|---|---|---|---|---|
| 1 | **Log blockers when a card is made** (`add`, `start`) and write an `Unblocked` line when its last blocker is done. | XS | blocked time per card, exactly (median 3.1 h in Long Haul) | no |
| 2 | **The actor on `Added to ...`** (the name that made it) and on every event that has one. `_log` already takes `by`. | XS | queue time split by who made the card; "cards the agent made itself" against "cards ORCH queued" | no |
| 3 | **A closing reason** on done: shipped, duplicate, not reproduced, superseded, not needed (a closed list, default "shipped"). | XS | the not-a-bug and duplicate rates (2 of 4 bug cards in Long Haul) | one word at close |
| 4 | **Agent state history**: when an agent's state changes (working, quiet, waiting for work (listening with no card), away) append one line to `.agentboard/agent-states.jsonl` (name, state, time). `hud.build` already computes the state on every HUD poll, so the change is noticed there or in a small tick. | S | idle share per agent per day, and its cause: *listening with no card* is waiting for work, *no listener and no card* is away, so nights are separable from waiting | **no** |
| 5 | **One rework event**: `Rework: <reason code>` written by every path that reopens a card, sends it back or answers a review with a change request ("Be simpler" included). The dedicated `Sent back` becomes one of them. | S | rework rate and its reasons per kind of card | no |
| 6 | **Model on the card**: `claim --model X`, or `AGENTBOARD_MODEL` read at claim time. | XS | model against kind of card, once there are cells with enough cards | one env var set per session |
| 7 | **A merge stamp**: `done --merged <hash>` (or `review --commit`) stored as fields, not in text. | XS | review-to-merge time (median 5 min in Long Haul), joined to git | one flag |
| 8 | **Size at creation** (S, M, L) and an **actual size at review** (the card's own elapsed time; lines changed only through the opt-in git reader below). | S | "split cards over size M", estimate against actual | a letter at `add` |
| 9 | **Chat counters** per day and sender (counts, no text) kept beyond the 500-line cap. | S | message volume, status-check load on agents | no |
| 10 | **A generic wait note**: `agentboard note wait <seconds> <lock\|rerun\|owner>`, called by a test runner or an agent. | S | waiting on a shared resource per card (30.8 h in Long Haul, found only in text logs) | yes, and project-specific: build last |

The first three cost almost nothing and fix the two largest reconstructions (blocked time, who made the card). Number 4 is the best single value: it makes idle time and its cause measurable **without asking any agent to do anything**.

## Observations: the first rules, and what they would have said on Long Haul

Each rule has a sample-size floor (**n of at least 5 per cell**, otherwise it says "not enough data" rather than guessing).

| Rule | Fires when | On Long Haul | Needs |
|---|---|---|---|
| Blocked cards wait | median wait for a blocker over 2 h | 3.1 h, n=26: **fires** ("cut a blocker into a contract and the rest") | existing data now; exact with #1 |
| A few cards hold the hours | cards over 3 h hold over 40% of build hours | 48%: **fires** ("split cards past about 2 h") | existing data |
| The nights are idle | over half of the between-card gap hours fall at night | 64%: **fires** ("queue ready cards before the owner leaves") | existing data now; the cause with #4 |
| One file conflicts | a file in over a quarter of conflicting merges | 63%: **fires** ("make that file generated or per-card") | opt-in git reader only |
| Bugs that were not bugs | over a quarter of bug cards close as not reproduced | 2 of 4, n=4: **not enough data** | #3 |
| Rework | share of cards reviewed twice or sent back over 20% | 5 of 87 (6%): quiet | #5 for the reasons |
| Kind against agent or model | a cell with n of at least 5 where one agent's median is under 70% of the others' | only one cell has 5 or more cards: **not enough data**, which is the honest answer | #6 |
| Holding a card | an agent held a card under 40% of the window | 26% (BuildBot): would fire, **wrongly**: work with no card is invisible. The sentence must say "holds a card X% of the time; the board cannot see work that has no card". | #4 |

A rule that would have fired wrongly is in the table on purpose: the view always shows the number, the sample size and what the board cannot see, next to the suggestion.

## How recommendations show

1. **`agentboard insights [--since 7d] [--agent NAME] [--json]`** first: plain text, the same as `summary`, read-only.
2. **`/insights`**, read-only, linked from the Summary page: one card per observation (the sentence, the number, the n, "what this cannot see", the suggestion). Nothing is ranked by person; an agent's name appears only inside the sentence that is about it.
3. **ORCH's `rollup`** gains the top two observations, one line each, so ORCH sees them where it already looks.
4. An observation can be **dismissed for 7 days**; that is a line in `.agentboard/insights-state.json`, local.

## Privacy

- **Counts, timings and ids only.** Observation text is built from templates and numbers; no chat text, no card description, no review body is copied into an observation or a stored line. A card title appears only where the owner already sees it.
- **Local only**: files under `.agentboard/`, no outside request. The server starts no program, so `selfcheck` and the work profile stay as they are.
- **Git and test logs are opt-in and outside the core**: the conflict-file and merge-time rules read git through a separate command (like `tools/retro-stats.py` in the game repo), never from the server, and are off until the owner runs it.
- New files follow the public-repo rules (`tests/publiccheck.py`); screenshots come from a throwaway board.

## Smallest first build (only after the owner approves)

One card, `agentboard-insights-v0`, behind `[insights] enabled = false`:

- captures #1, #2 and #3 (XS each), plus `agentboard insights` with four rules that need only existing data: blocked cards wait, a few cards hold the hours, the nights are idle, holding a card (with its caveat);
- tests that build a throwaway board of made-up cards and check each rule's number against a hand count, and that a board with fewer than 5 cards in a cell says "not enough data";
- acceptance: on a board shaped like Long Haul the medians match the retro within rounding (build 0.57 h, blocked wait 3.1 h, night share 64%); no new network, program start or personal data; the work profile's `selfcheck` still passes.

Size: M, about a day. #4 (agent state history) and #5 (one rework event) follow as their own cards once v0 shows the view is wanted.

## What I need decided

1. **Scope of v0**: is "captures 1 to 3 plus four rules, CLI first" the right first step, or do you want the `/insights` page in the first card?
2. **Agent state history (#4)**: a small write on every state change, noticed where the HUD already computes it. It is the best value and needs no agent cooperation, but it is the one capture that adds a recurring write. Yes or no for the second card?
3. **Asking agents for things** (#6 model, #8 size): one env var and one letter per card. Worth it, or only what the board can see by itself?
4. **Where git facts live**: a separate opt-in command (proposed) or never inside the board?
5. **Thresholds**: the numbers in the rules table (2 h, 40%, 50%, 25%, n of 5) are my starting points; say if you want others.
6. **Non-goals confirmed?** No scoring or ranking of agents, no automatic change to a prompt, role or card, no text from messages.
