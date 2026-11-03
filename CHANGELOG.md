# Changelog

## Unreleased

### By agent as polished as the Board, and Motion (Nov 3)
- **By agent's lanes draw their cards the way the Board's Doing column does**: the status-tinted fill (orange running, green review, red ask), the status border and shadow, the hover glow, and a lit column head. It is one rule for both now, so no new colour was added and a change to Doing's look carries to the lanes.
- **Motion**, a Mix layer that is off until you choose it: look and sound move together. An agent's card that changes column lands at the end of its glide with the Touch settle (pitched by the column, in the agent's voice); a card reaching Done draws its check in; the view crossfades for the swish. Your own moves do not get the settle (they sounded when you made them). Off, nothing on the page changes.

### Load switches with the same one sound as the other tabs (Nov 3)
- **Opening or closing Load plays the tab swish, the same simple sound as flipping Board and By agent**, instead of its rising and falling chimes. Every switch sounds once: the tabs, `[`, `]`, `a`, `h`, Escape, Back and Forward alike, and never a swish and a chime together. The ambient bed plays straight through, and the other cues did not change.

### Board and By agent switch in place (Nov 3)
- **Flipping between Board and By agent no longer reloads the page**: the tabs, `a`, `[` and `]` redraw the board where it is, the way Load already opened and closed. The sound plays straight through, the open card and the filter stay, and the address bar and Back button still follow the view.

### Touch: the sounds of using the board (Nov 3)
- **A thin layer of UI sounds for what your hands do**, synthesized like the cues and played through the same buses (compressor, reverb send), so it reads as one instrument: a soft tick when a card takes keyboard focus; a rising pair when a card's panel opens and a falling pair when it closes, in that card's agent's voice; a lift when you pick a card up and a settle when you drop it, pitched by the column it lands in (Todo low, Doing mid, Done high; dropped back where it was, nothing); a faint click per Alt+arrow step; one swish for a tab change (the tabs, `[`, `]` and `a` alike); a quiet slide in and out for Later, Chat, Mix and the shortcuts sheet; a two-pitch click on the theme, sound, notifications and AMB switches, up for on and down for off; a tick when the filter's match count changes (nothing per keystroke); a confirm blip when a prompt is copied; a tick that rises a semitone per card selected and falls when one leaves; one low tone for a failed save or a dropped connection, never again on every poll.
- **Every one of them is at most 40% of the quietest cue and 20 to 120 ms**, only ever on your own action (never on a poll or a re-render), one per action. Mark done keeps its done cue, adding a task its added cue: nothing plays twice.
- **One Mix row, Touch, on by default with its own level**, so the whole set turns down or off in one place; SND OFF still silences everything. The cues and the bed did not change.

### Sounds on every view (Nov 3)
- **The ambient bed and the Mix layers (Rain, Wind, Pad, Pulse) play on Board and By agent too**, not only while Load is open. The sound is the same as before; opening or closing Load no longer starts or stops it.
- **One bed at a time**: with several pages or windows open, the one you start or come back to plays and the others hush; when it closes the next visible one picks it up. Cues are unchanged: Board and By agent play the board's cues, Load plays its own, never both.
- **`s` turns sound on or off on every view**, and the sound button shows the saved state as soon as the page loads (it only caught up after Load was opened).
- A fresh page waits for your first click or key before the bed starts (browsers insist); clicking the tabs to switch views carries that over.
- Pulse and the console chatter follow who is working on Board and By agent too, by the same rule By agent's lane colours use.

### Full width (Nov 3)
- **The board uses the whole browser window**: the 1800 px cap is gone, so Board, By agent and Load fill a 2560 or 3440 px screen, and the top bar stays where it is (no longer centred) on every view and width.
- The columns grow with the window and the cards fill them, on the Board (Doing, Done) and on By agent alike.
- Load's text column stops at 760 px from 1800 px up and the hour bar takes the rest.

### Todo column in both views (Nov 2)
- **By agent now has the Todo column**, the same one as on the board: one function draws both, so they cannot drift. It is narrower than before (about 17% of the width, 220 to 270 px, the Doing and Done columns get the rest), its cards are narrower too, and they no longer say *Unassigned*. Copy prompt, Later and the queued time sit in one wrapping foot row instead of floating over the title; an assigned card shows its agent's name with the time in the foot row; a project shows as a dot in the corner.
- The assigned Todo cards that waited at the foot of an agent's column as *next up* are gone: they are in the Todo column now, so no card is drawn twice.
- Stacked (a phone or a narrow window) the Todo cards keep their narrow look (340 px at most) instead of stretching across the screen.
- **By agent's header button is Later, like the Board's**: the Todo drawer is gone (Todo is a column now), so the header is the same in both views and By agent gets the Park an idea box.

### The owner's name is a setting, not the code
- **`[board] owner` in config.toml** names the human on this board; it is **"you"** until you set it. The board, the HUD, report pages, the SMS reply marker, the summary page, the dictation hints and every prompt (card, subtask, parent, run, instructions, ORCH, agent chat) read it, so nothing in the app names a particular person. Prompts say "the user" until it is set, and "they" for the pronoun. `/api/config` and `/api/hud` carry it to the page.
- **`[voice] words`** adds names to the dictation hints (the old built-in list of one person's project names is gone).
- A card that says "ACTION you: ..." or "ACTION <your name>: ..." lands in the owner's row on Load either way.

### Sound
- **Mix** (the Mix button in Load, key `m` anywhere): extra sound layers on top of the usual sound, each with its own switch and level, saved in that browser and **off until you choose it**. The sound you had is the default and did not change. Ambience, played with AMB in Load: Rain, Wind, Pad, Pulse (a heartbeat that quickens as more agents work). Effects, board and Load: Echo, Signatures (each agent's three-note call when it starts or finishes), All clear (a chord when the last card waiting on you is answered), Hourly chime. A **Hear it** button plays any layer for a few seconds before you switch it on.

### UX polish (Nov 2)
- **Load:** the idle rows are readable (their status was at 30% opacity; text is now 4.5:1 or better, still quieter than working by colour), and the Queue row stays pinned at the bottom of the list when the open idle rows push it below the fold.
- **Click areas:** the subtask toggle, the Done column's Summary / Reports / Clear and the card's Report link keep their look but are about 30px to hit.
- **Later drawer:** no repeated "Unassigned" on every row.
- **Small labels** (the day-group count, the chat topic chip, the By agent state tag, the idle fold count) reach 4.5:1 in both themes.
- **Cards and the panel** say "14% overall" for a parent's percent instead of a sigma (the CLI `list` keeps its Σ).

### Load
- The idle agents on Load are **open by default** (Nov 2), so the default view shows them without a click. The IDLE row still folds them away, and a collapse is remembered in that browser.
- The **HUD** tab is now **Load** (its address is still `/hud`, key `h`). Load no longer draws a top bar of its own: the board's header stays on screen and Load opens right under it, so Board, By agent and Load share one nav, item for item, at every width (before, Load's copy sat 12px further in between 600 and 900px, up to 24px lower below 980px, and had different items). Load's own controls (LIVE, alerts, sound, ambient, pop out, close) sit in a thin bar under the nav. The pop-out window keeps the header too. Later and Chat open over Load, Esc closes them first, and the Later and Todo buttons share one width so ORCH no longer moves between Board and By agent.

### By agent
- A fifth tab, **By agent** (`/agents`, key `a`): the board's cards as swimlane columns, Queue first, one per agent with a card in Doing (state in the header, assigned Todo cards as *next up* ghosts), then one Idle column from the HUD's roster. Todo and Done are counts in the bar. One agent per screen on a phone. Chosen from `docs/doing-by-agent-mockup.html` (option B).

### Removed (Nov 1)
- **Assign, Hand to… and the Your move strip.** You paste the card's prompt into an agent and the agent claims the card itself, so the picker (`/api/assign`, `/api/hand`, `/api/agents`), Unassign, the card holder set before a claim, the `ORCH: you assigned <id> to <agent>; hand it over.` chat line and the matching ORCH prompt rule are gone. Asks and reviews stay on their cards and in the panel that opens for them; an agent gone quiet keeps its warning on the card and the HUD. Queued prompts no longer rewrite the session name.

### Colour belongs to the agent, not the card (Nov 1)
- Cards no longer carry a colour. `start`, `claim`, `run` and `chat send` still accept `--color` (and `AGENTBOARD_COLOR` is read nowhere) but ignore it; nothing is stored, a claim no longer copies a colour to its subtasks, chat bubbles take the sender's colour by name, and `/api/color` is gone. Existing cards keep an unused `color` field.
- The board picks one hue per agent name from a six-colour palette clear of the status hues (orange running, green review, red ask); `[agent_colors]` in config.toml overrides a name. Same colours on the board, the HUD and the chat. Before, AGENT-1 to AGENT-5 were all green because each card brought its own.
- The agent's name sits in a pill tinted with its colour, with a solid avatar disc; the name is 14px bold in the same place on every card, and Unassigned is no longer faint.
- The ORCH prompt, card prompts, `agentboard instructions` and the README no longer tell agents to pass a colour; the ORCH roster lists names only (a colour in `[orch] agents` is ignored).

### Agent chat (opt-in)
- Agents can talk to each other on the shared chat once the owner turns it on (**Agents talk** in the Chat panel, or `agentboard chat agents on`; default off, board-wide, stored in the board file). Messages gain `--to`, `--topic` (status, learn, help, heads-up, handoff), `--detail` / `--detail-file`, `--card`, `--file`, `--reply-to` and `--propose`; the panel shows one line per message in the agent's colour, the detail on tap, chips for the card and files, and Approve / Decline on a proposed action (`agentboard chat approve|decline <n>`; agents read the decision with `chat approvals`). Chat never changes anything itself.
- Said casually: with `[chat] casual = true`, `agentboard serve` gives each agent line a spoken version on the cheap model (same facts, one friendly line), shown as the bubble with the line as written behind **As written**; `agentboard chat casual [--once]` by hand; `casual_per_hour` caps it.
- The real conversation, mirrored: `agentboard hooks install` adds a Claude Code hook (PostToolUse on SendMessage) that posts each message a session sends to another session on the chat, as that session, to whom it went, the rest behind Detail (`msg` chip). Sessions are named by their first `claim`, `start`, `chat` or `agentboard me --name`; `agentboard hook send-message` is the hook's command, always exit 0.
- Signal over noise: the board never speaks for an agent that spoke or touched a card in the last `live_min` minutes (default 20); drafts know the date and each card's age, treat done cards and day-old asks as closed, never post a bare acknowledgement, and end an answer with a question back; a share must tie to a card a colleague is on right now, to that agent, or it is not posted.
- The drafts speak like colleagues (short sentences, contractions, names, no lists, code only in the detail), and an idle agent with nothing to answer offers one thing from its own finished work every `share_every_min` minutes (default 60) as a *learned* line to all; `chat idle --share` by hand.
- Autopilot: with `[chat] autopilot = true`, `agentboard serve` drafts a reply on the cheaper model for every `[orch] agents` name that is idle and has unread chat, every `autopilot_every` seconds (default 180), capped at `autopilot_per_hour` (default 12); the lines are marked **auto** and show in that agent's own inbox. `agentboard chat autopilot [--once]` runs the rounds by hand.
- Flipping the switch posts one line to the chat telling ORCH and running agents what to run; the ORCH prompt says how ORCH takes part (open the channel, `chat inbox --name ORCH --wait 300` when idle, answer, name who takes a handoff, never act on a proposal).
- `agentboard chat inbox --name X [--wait N]` (unread for X, cursor kept per name), `chat tail --for X`, `agentboard recall` (the board as shared memory: cards, updates, history and chat matching a few words, one card's history, one agent's cards), and `agentboard chat idle` (one reply drafted from the inbox and the memory through the local `claude` binary on `[chat] idle_model`, default `haiku`, `--send` to post). The prompts (card, run, ORCH, instructions) carry the protocol only while the switch is on. Lines that arrive together are revealed one at a time in the panel.

### Round two (ux-six)
- **Desktop notifications from the tab.** A bell in the top bar; on, the board uses the browser's Notification API (local only) while the tab is in the background: an ask at once and again every 15 minutes while it waits, a review once, an agent gone quiet once. Clicking one brings the tab back and opens the card. Stored as the `agentboard-notify` preference.
- **Edit in place on the card.** In the panel the title and the description are editable where they are (click, or `e` for the title); Save or ⌘↵, Esc cancels; one log line per change, marked as yours. The subtask list ends in an add row (Enter adds a subtask under the card), and a Blocked by row takes any open card by its title and shows the blockers as chips with a remover. Agents and columns never change this way. New: `Store.edit`, `POST /api/edit`.
- **Assign and Hand to… put the prompt on the clipboard.** Picking an agent also copies the card's prompt, which now names that agent (`claim <id> --name "AGENT-3" --color …`) while the card waits in Todo with a holder; the one step left is the paste into that agent's terminal. `agentboard prompt <id>` says the same.
- **Hand to… on quiet cards.** The Your move row of an agent gone quiet (and the panel of any live card) opens the same picker as Assign, idle agents first, without the current holder; one pick sends the card to the top of Todo under the new agent, clears its ask/review state, releases the old agent, takes the open subtasks along, and tells ORCH in the chat (`ORCH: you handed <id> from <old> to <new>; hand it over.`). "Nobody yet" sends it back to Todo unassigned. The panel of a queued card gets Assign / Reassign. New: `Store.hand_to`, `POST /api/hand`.
- **Quick replies on asks.** The options an ask names become one-tap chips (`3 or 5?` gives 3 and 5; `x, y or z?`, `(1) … (2) …` lists and yes/no questions likewise), plus Go ahead, Hold and Your call on every ask. On the Your move row the chips replace the Reply button and sit beside a small typed box; on the card and in the panel they sit above the reply box. A tap sends the reply the usual way (`/api/reply`, read with `agentboard answer`).

### Five UX ideas (ux-five)
- **HUD: one chart per agent, idle agents folded.** Each active row carries a stepped chart of its card's % over the last hour with a tick per update, on the same axis as the load track; `/api/hud` adds `chart` per agent and an `idle` fold. Idle agents collapse into one row of chips (name, how long ago, signed off today) that opens on click. `[orch] agents` peers with no card yet show as idle.
- **Assign from a Todo card.** An Assign button on every Todo card opens a picker of agents, idle ones first (from the HUD's view plus `[orch] agents`), then the busy ones with what they hold; a click hands the card to that agent (it stays in Todo with that holder until the agent claims it), and Unassign takes it back. The hook: the board posts one line to the shared chat (`ORCH: you assigned <id> to <agent>; hand it over.`), which ORCH follows; the ORCH prompt says to act on it. New: `Store.assign`, `POST /api/assign`, `GET /api/agents`.
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

### One sentence to the owner
- Every prompt (Copy prompt, run prompt, instructions snippet, ORCH prompt) ends with the reporting rule: one sentence, the ACTION first then one fact; no action needed = one line of status; more = one sentence then offer the detail. The ORCH prompt now says agents report to the owner directly, when ORCH may speak to them, daytime vs sleep assigning, and what is never done without their own words.
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
