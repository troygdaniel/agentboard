# Changelog

## Unreleased

### Round two (ux-six)
- **Desktop notifications from the tab.** A bell in the top bar; on, the board uses the browser's Notification API (local only) while the tab is in the background: an ask at once and again every 15 minutes while it waits, a review once, an agent gone quiet once. Clicking one brings the tab back and opens the card. Stored as the `agentboard-notify` preference.
- **Edit in place on the card.** In the panel the title and the description are editable where they are (click, or `e` for the title); Save or ⌘↵, Esc cancels; one log line per change, marked as yours. The subtask list ends in an add row (Enter adds a subtask under the card), and a Blocked by row takes any open card by its title and shows the blockers as chips with a remover. Agents and columns never change this way. New: `Store.edit`, `POST /api/edit`.
- **Assign and Hand to… put the prompt on the clipboard.** Picking an agent also copies the card's prompt, which now names that agent (`claim <id> --name "AGENT-3" --color …`) while the card waits in Todo with a holder; the one step left is the paste into that agent's terminal. `agentboard prompt <id>` says the same.
- **Hand to… on quiet cards.** The Your move row of an agent gone quiet (and the panel of any live card) opens the same picker as Assign, idle agents first, without the current holder; one pick sends the card to the top of Todo under the new agent, clears its ask/review state, releases the old agent, takes the open subtasks along, and tells ORCH in the chat (`ORCH: Troy handed <id> from <old> to <new>; hand it over.`). "Nobody yet" sends it back to Todo unassigned. The panel of a queued card gets Assign / Reassign. New: `Store.hand_to`, `POST /api/hand`.
- **Quick replies on asks.** The options an ask names become one-tap chips (`3 or 5?` gives 3 and 5; `x, y or z?`, `(1) … (2) …` lists and yes/no questions likewise), plus Go ahead, Hold and Your call on every ask. On the Your move row the chips replace the Reply button and sit beside a small typed box; on the card and in the panel they sit above the reply box. A tap sends the reply the usual way (`/api/reply`, read with `agentboard answer`).

### Five UX ideas (ux-five)
- **HUD: one chart per agent, idle agents folded.** Each active row carries a stepped chart of its card's % over the last hour with a tick per update, on the same axis as the load track; `/api/hud` adds `chart` per agent and an `idle` fold. Idle agents collapse into one row of chips (name, how long ago, signed off today) that opens on click. `[orch] agents` peers with no card yet show as idle.
- **Assign from a Todo card.** An Assign button on every Todo card opens a picker of agents, idle ones first (from the HUD's view plus `[orch] agents`), then the busy ones with what they hold; a click hands the card to that agent (it stays in Todo with that holder until the agent claims it), and Unassign takes it back. The hook: the board posts one line to the shared chat (`ORCH: Troy assigned <id> to <agent>; hand it over.`), which ORCH follows; the ORCH prompt says to act on it. New: `Store.assign`, `POST /api/assign`, `GET /api/agents`.
- **One top bar.** The board, the HUD, the Done summary, the reports list and every card report share one bar: the brand and four tabs (Board, HUD, Summary, Reports), the current page lit, every link under the board's own `/b/<name>` prefix. On the board the HUD tab is the old HUD button; in the HUD the Board tab closes it (or opens the board from the pop-out). Report pages now follow the board's chosen theme too. New module `nav.py`.
- **Done column: a 7-day ribbon and day groups.** Under the Done header, one bar per day (today at the right) as tall as that day's finished cards, with the count and the weekday; click a day to see only its cards. The column groups cards by calendar day (Today, Yesterday, then the weekday and date, Earlier past the week), each group with its count.
- **Your move strip.** Every card that needs you sits in one strip under the header, asks first, then reviews, then agents gone quiet, each with its action right there (Reply, Mark done, Send back, Open, To Todo) and a bar of how long it has waited. Hidden when nothing needs you.

### Keep it simple
- The ORCH prompt (Copy ORCH, and the one-shot and instructions variants) gains a named `Keep it simple` block that ORCH must copy word for word into every card description and assignment it writes: one sentence, one idea, detail on demand. Instructed only; nothing checks it.
- `agentboard update`, `ask` and `review` take a first line plus a body: `--body` / `--body-file`, or a multi-line text whose first line is the sentence and the rest the body. On the card the sentence is the large first line and the rest sits behind a collapsed `Details` fold.

### Voice
- Mic buttons on the add-card box, the chat box and the reply boxes (on the card and in the panel): record in the browser, transcribe on this Mac with whisper.cpp through `POST /api/transcribe`, text inserted at the caret. `agentboard dictate [--paste] [--file f] [--mic i]` does the same for a terminal: Enter, speak, Enter, text on the clipboard. Local only: no browser speech API, no upload, no account; hidden when `whisper-cli` or a model is missing. `[voice] model` / `AGENTBOARD_WHISPER_MODEL` pick the model.

### Done summary
- A Summary button on the Done column header opens `/summary` (`?since=1d|7d|30d|all`, `&project=<id>`): the finished cards as a page about the work itself. One number and three plain facts; a bar of the kinds of change (added, fixed, improved, tested, documented, explored; from the titles and asks); a work map (projects split into work areas found from shared title words, sized by cards, coloured by the main kind; click an area for its cards); each project as collapsed work areas with one row per card (title, outcome with numbers in bold) that opens to the ask, the full result, the timeline and links to the card and its report. Search and a kind filter scope the whole page; inline SVG only, both themes, phone width. Copy text (markdown), Copy Mermaid (a mindmap of projects and areas) and Save as HTML. `agentboard summary [--since 7d] [--project id] [--html path] [--mermaid]`.
- An opened card is readable, not a blob: a numbered ask becomes a step chain plus the items, an ACTION/STATUS/WHY result becomes three coloured bands, other text is one sentence per line; paths, flags and files in code style, numbers bold, asides muted, a leading name as a chip. "How it went" is a bar of the time the card spent in each status, with the timeline folded under it.

### Card reports
- A card entering review or done gets an HTML report in `.agentboard/reports/` (action first, then number tiles for commits, tests and files, a few built points, a short timeline, commits with links, bars of where it changed, numbered steps to try it, Mark done / Send back; no run-on paragraphs). A report button on the card, a list at `/reports/`, `agentboard reports [--purge]`, and an ageing sweep (`[reports] keep_hours`, default 24; the newest per card always stays). `POST /api/send-back` sends a card back with a note the agent reads with `agentboard answer`.

### One sentence to Troy
- Every prompt (Copy prompt, run prompt, instructions snippet, ORCH prompt) ends with the reporting rule: one sentence, the ACTION first then one fact; no action needed = one line of status; more = one sentence then offer the detail. The ORCH prompt now says agents report to Troy directly, when ORCH may speak to him, daytime vs sleep assigning, and what is never done without his own words.
- Ask and review cards show that sentence as the first line, large, with a reply box on the card. The reply is stored on the card and read with `agentboard answer <id> [--wait]`; it clears when the agent moves on.

### Text the board
- `agentboard sms serve`: an opt-in Twilio inbound-SMS webhook on its own port (`127.0.0.1:8766`) that adds and moves cards and replies with one line. Needs `[sms] enabled`, an allowlist, an https `public_url` and the auth token in the environment. Signature check, sender allowlist, MessageSid replay protection and an hourly cap; refused requests get nothing back. `agentboard sms try TEXT` runs a command locally. SECURITY.md updated.
- Texting is two-way: plain words become a Todo card; questions (status of a card or agent, what is ready, blocked, today, asks) get one short sentence; `reply <text>` or a bare yes/no answers an ask card. Every reply is one sentence, 160 characters at most.
- `AGENTBOARD_NO_SMS=1` locks texting off on a machine: `agentboard sms serve` refuses to start whatever the config says.

### One-shot agents
- `agentboard run <card>` runs a card with a non-interactive `claude -p` in its own git worktree, under a hard time limit and a spend cap, with a per-run log in `.agentboard/runs/`. On exit the card moves to review (or ask, with the tail of the output), records cost and duration, and the worktree is removed if clean. `agentboard runs` lists runs, `runs --kill CARD` and the card's Stop run button stop one, `--detach` returns at once. Permission settings are never widened. A `▶ run` badge shows on the card.

### Several boards
- `agentboard board new | add | list | use | rm` and a registry in `~/.agentboard/boards.toml`; `--board NAME` / `AGENTBOARD_BOARD` pick a board from any folder. One `agentboard serve` serves every registered board at `/b/<name>/` (and `/b/<name>/hud`); the default board's links are unchanged. A header dropdown switches boards and a per-board colour tints the header. Snapshots and `sync_dir` stay per board.

### New cards on top
- `agentboard add` and both web Add forms put the new card at the top of Todo or Backlog (not the bottom). Column order is still the stored list order, so drag-reorder and Alt+arrow keep working; existing cards keep their order; Doing and subtasks still append.

### Header
- ORCH sits on the left beside Later and Chat. The Auto / Light / Dark word becomes one 44px icon button (half circle, sun, moon) that cycles the same three modes, with a tooltip and an aria-label naming the mode. README screenshots retaken.

### Status colours
- Card colour follows status: orange while doing, green at review, muted when done, red edge on ask. The agent's colour is now a thin left stripe on the board. The HUD's working colour is orange and waiting-on-you is red.

## v0.3.1 (2026-10-25)

### Backups
- Atomic saves with a `.bak` of the previous file; hourly snapshots in `.agentboard/backups/` (48 hourly, 30 daily); optional nightly
  copy to a synced folder (`[backup] sync_dir`); `agentboard backup | verify | restore`; the HUD shows the age of the newest snapshot.

### Twins
- `start` reuses a card the same agent already holds instead of creating `<id>-2`; `claim` on a held card is a no-op;
  `agentboard dedupe [--apply]` merges existing twins.

## v0.3.0 (2026-10-24)

Since v0.2.0 (63 commits). Still Python 3.11+, standard library only, local only.

### HUD (`/hud`)
- One grid: every agent is one full-width row with its name and state, the text that matters
  (the ask in full, or the agent's own status line), its last notes, and on the right the card
  title, the 60-minute load bar and the progress line. One header, one time axis, the queue as the
  last row. Panel fills the window; rows share the spare height.
- Attention rows: a card that needs a person lights its agent's row (red: needs an answer or a
  sign-off; amber: the agent went quiet; cyan: the ask names another agent), rows that need you
  sort first, and clicking one opens the card.
- `/api/hud` gains `actions`: every ask / review / abandoned card as a "who must do what" row,
  parsed from the ACTION / STATUS / WHY report shape agents write.
- `[hud] retired = ["AGENT-5"]` in `config.toml` hides retired agents from the HUD (cards and
  history untouched).
- Type one step larger; lanes no longer rebuild every second; contrast fixes; narrow screens
  stack the load bar under the text.

### Board
- Readable card detail panel: ACTION band (who must act, in colour), STATUS chips, formatted
  timeline with time-ago and progress, light markdown (bold, bullets, inline code, tables), copy
  buttons on commands and links, Mark done / Reply (replies land on the card log as the user).
- Numbered steps written as "(1) … (2) …" or "1. … 2. …" render one step per line, markers kept.
- Subtasks: child cards under a parent (one level), the parent's % computed from them, a single
  total bar with a checklist, prompts that tell a subtask agent what to do.
- Dependencies (`--blocked-by`), projects (named, coloured, with a filter), bulk select / move /
  archive / assign, Later drawer from the left, columns keep their scroll position, header wraps
  instead of squeezing, undo logs a "Restored" entry.
- `agentboard tail` (live terminal feed), `agentboard wait` (block until a status), `agentboard
  report` (daily recap by agent), chat channel (`chat send` / `chat tail --follow`), opt-in macOS
  notifications on ask / review, rich markdown bodies on ask / review (`--body`, `--body-file`).
- `agentboard init` now adds `.agentboard/` to the project's `.gitignore`.
- Bug hunt across store, server, prompt, markdown and wait; parent % refused instead of dropped;
  natural sort of agent names (AGENT-2 before AGENT-10).

### Docs
- README rewritten for what exists now: install, the HUD, the ACTION / STATUS / WHY report shape,
  the orchestrator + agents workflow, config keys, CLI reference, a work-laptop section.
- SECURITY.md re-checked against this release.

## v0.2.0 (2026-10-20)
- First public release: board, HUD with per-agent swimlanes, prompts and context providers,
  local-only audit (SECURITY.md).
