# Night queue: agents take the next card themselves

Card `retro-night-queue` (retro rec 13, docs/retro-2026-11-15.html). Mockup (light, dark, narrow): `docs/night-queue-mockup.html`. Every card and name in it is made up.

**What it is.** A board-wide Night switch, off by default. While it is on, ORCH keeps an ordered queue of specified cards, and an agent with a free hand takes the next one itself with one command, instead of waiting for a message from ORCH. Nothing else about the board changes: with the switch off (or never used) no command, line or screen differs from today.

**Why.** 56% of the hours agents sat between cards fell between midnight and 08:00 (retro rec 13). The rule it keeps: no auto-assign while the owner is awake, so the switch ends by itself.

## The three pieces

| Piece | Who | What |
|-------|-----|------|
| The switch | the owner, or ORCH at the owner's word | `agentboard night on [--until HH:MM]`, `night off`, `night status`; a button in Settings > Agents and chat |
| The queue | ORCH or the owner (a worker agent is refused) | `agentboard night queue add ID...`, `remove ID...`, `clear`, and `night queue` to list it |
| The take | any agent | `agentboard night next --name NAME` claims the first card in the queue that is ready, and says what it took |

### The switch

- Off until someone turns it on; the setting lives in its own small file, `.agentboard/night.json` (no file until it is first used, and no new key in `tasks.json`).
- `night on` ends by itself at `--until` (default 08:00: the next time that is on the clock). A forgotten switch cannot run into the day. After that, `night next` says night mode ended at 08:00.
- A change posts one line to the chat, as the chat switch does: "Night mode on until 08:00: 3 cards queued. Take the next with: agentboard night next --name <you>".
- The board shows it: a header chip `Night · 3 queued · until 08:00` while it is on, and a row in Settings > Agents and chat with the button and the queue in order. No chip when it is off.

### The queue

- A card goes in only if it is Todo, unclaimed, on the board and not a subtask. A card with unfinished blockers may be queued (a card that unblocks the next one is the common case); it is listed `blocked by X` and skipped until X is done.
- Order is the order added. `night queue add` appends (a card already queued keeps its place); `night queue add ID --first` puts a card at the front.
- A card leaves the queue when it is taken, claimed some other way, removed, or done.
- Cards stay queued over the morning; ORCH clears what it does not want kept.

### The take

`agentboard night next --name NAME`, in one step under the board's lock, so two agents never take the same card:

1. Night mode must be on, and not ended. Otherwise: "night mode is off: take the cards ORCH assigns".
2. NAME must not hold an unfinished card (Doing, no review, no question open). Otherwise: "you hold CARD: hand it in first".
3. The first queued card that is Todo, unclaimed and unblocked is claimed exactly as `agentboard claim` does it (same log line, subtasks, role block), plus the log line "Taken from the night queue".
4. It prints the card id, the title, the limits line (below) and the prompt command. Nothing ready: "(queue empty or all blocked: stay idle and listen)", exit code 1.

### The limits (the same as the overnight pushes)

No push, no spend, no live restarts, no personal cards. The board states them in the take, the chat line and the Settings row; it cannot enforce them. What it does: only ORCH or the owner can put a card on the queue, so a personal card gets there only on purpose; and an agent never sees a card it was not given.

## What it is not

- Not an auto-assigner: ORCH decides what is in the queue and its order; the owner decides when the switch is on.
- Not a new column or card state: a taken card is a plain claimed card.
- No new daemon. The server does nothing for it; the commands and the Settings button read and write `night.json`.

## Build plan

1. `night.py` (the state, the queue, the take), `cli.py`: `agentboard night ...`; `server.py`: `GET /api/night`, `POST /api/night` (the switch only).
2. `static/index.html`: the Settings row, the header chip.
3. Tests for the store, the CLI, the route and the page; `docs/index.md` and CHANGELOG.
