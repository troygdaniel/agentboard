# agentboard

**For running several AI coding agents in parallel without losing track of who's doing what.**
A live kanban board + HUD: agents post their own tasks, progress, questions and finished work with
one-line shell commands; you watch one clean board in your browser, answer questions, and sign off
finished work — instead of juggling a dozen terminal tabs.

- **Local only.** A tiny Python server on `127.0.0.1`; data is one JSON file in your project. See [Local-only and safety](#local-only-and-safety).
- **No dependencies, no database.** Python standard library only. Python 3.9 to 3.14 (the Python a Mac or Ubuntu already has is enough).
- **Agents never close their own work.** They finish with `review`; *you* mark the card done.
- **Reports lead with the action.** Agents write `ACTION / STATUS / WHY`; the board and the HUD show who must do what, in colour.

## Screenshots

| Board (light) | Board (dark) |
|---|---|
| ![Board, light theme](docs/board-light.png) | ![Board, dark theme](docs/board-dark.png) |

| HUD |
|---|
| ![HUD](docs/hud.png) |

## Install

Requirements: **Python 3.9 or newer** (`python3 --version`; 3.9 to 3.14 are tested) and [pipx](https://pipx.pypa.io) (`brew install pipx`, or with no admin rights `python3 -m pip install --user pipx`, then `pipx ensurepath` and a new terminal). No other dependency: it is the standard library only, and on Python 3.9 and 3.10 a small built-in reader stands in for `tomllib`. Tested on macOS; nothing in it is Mac-only except the optional notifications and dictation.

Three commands, then the board is running:

    pipx install git+https://github.com/troygdaniel/agentboard     # once per machine (pipx makes its own venv under ~/.local)
    cd your-project && agentboard init                             # once per project: .agentboard/ (tasks.json, config.toml), git-ignored
    agentboard serve                                               # http://localhost:8765 (Ctrl+C stops)

The long form:

    pipx install git+https://github.com/troygdaniel/agentboard     # from GitHub
    # or, from a checkout:
    git clone https://github.com/troygdaniel/agentboard && cd agentboard && pipx install .
    agentboard --version                                           # prints: 0.3.1

No pipx? From inside a checkout, with `python3` being 3.9+ (`python3 --version`):

    rm -rf build && python3 -m venv ~/.agentboard-venv && ~/.agentboard-venv/bin/pip install .
    export PATH="$HOME/.agentboard-venv/bin:$PATH"     # so the bare `agentboard` commands below work (add to your shell profile)

Releases are tagged (`v0.3.0`); see `CHANGELOG.md`.

### Upgrade

    pipx upgrade agentboard                                        # installed from GitHub: fetches the latest commit
    # or, from a checkout:
    git pull && rm -rf build && pipx install . --force
    agentboard doctor                                              # want: no FAIL; INFO version shows the new commit

Then stop and start `agentboard serve` (the running server keeps the old code until it restarts). Cards, config and backups are files in `.agentboard/` and are never touched by an upgrade; a newer board reads an older `tasks.json` as it is.

### Uninstall, leaving nothing behind

    agentboard hooks uninstall                                     # in each project where you ran `hooks install` (removes the two entries from .claude/settings.json)
    pipx uninstall agentboard                                      # the program and its venv (~/.local/pipx/venvs/agentboard, ~/.local/bin/agentboard)
    rm -rf your-project/.agentboard                                # a project's cards, config, reports and backups (and the .gitignore line, if you like)
    rm -rf ~/.agentboard                                           # only if you used named boards: the registry and boards made with `agentboard board new`
    rm -rf ~/.config/agentboard                                    # only if you made it: the profile file `agentboard profile work` writes, and private-words.txt for the repo check

That is the whole footprint. agentboard writes nowhere else: no launch agent, no login item, no shell profile line (pipx's `ensurepath` is pipx's own), no cache outside those folders, nothing in `~/Library` (dictation reads model files other apps installed, it writes none). The one thing outside is Python's own: the Mac's built-in Python 3.9 keeps compiled bytecode in `~/Library/Caches/com.apple.python` for any program it runs. `[backup] sync_dir`, if you set one, is a folder you chose; delete it yourself.

**Offline, or a locked-down PC (no package index, no admin rights).** Both commands above fetch build tools from PyPI the first time: pipx upgrades
its own pip (it does this even for a prebuilt wheel, so pipx is a dead end offline), and a plain pip install of the checkout builds in an isolated environment that
downloads setuptools. A wheel needs neither. On any machine with network, build it once and carry the one file over:

    rm -rf build && python3 -m venv /tmp/agentboard-build && /tmp/agentboard-build/bin/pip wheel --no-deps -w dist .     # makes dist/agentboard-0.3.1-py3-none-any.whl (pure Python, works on any OS)
    ls dist/                                                     # must say agentboard-0.3.1-..., never UNKNOWN-0.0.0

Build inside the venv, not with `python3 -m pip wheel` directly: a Mac's built-in Python 3.9 (and some Linux system pythons) has an old pip that then uses the system's old
setuptools, cannot read `pyproject.toml`, and says `Successfully built UNKNOWN`, a wheel with no program in it.

On the offline machine, with `python3` being 3.9+:

    python3 -m venv ~/.agentboard-venv && ~/.agentboard-venv/bin/pip install --no-index dist/agentboard-0.3.1-py3-none-any.whl
    export PATH="$HOME/.agentboard-venv/bin:$PATH"

`--no-index` makes pip refuse the network instead of hanging on it. The same wheel is attached to each tagged release on GitHub, so a
download from the Releases page is enough; nothing is compiled and nothing else is installed. The board itself never leaves localhost.

**Always remove `build/` before installing from a checkout you have used before.** pip builds inside the checkout, and setuptools copies into `build/` without removing
files that no longer exist in `src/`, so a module deleted from the source can come back into the installed copy (the removed text features did exactly that once). A first install
from a fresh clone has no `build/` and needs nothing. `agentboard doctor` warns ("stale install") when the installed copy holds a file its source no longer has, and tells you the fix.

## Quick start

    cd your-project
    agentboard init            # creates .agentboard/ (tasks.json, config.toml) and adds it to .gitignore
    agentboard serve           # board: http://localhost:8765   Load: http://localhost:8765/hud   (Ctrl+C stops)

**A fresh install on a managed or shared PC starts safe.** When `agentboard init` finds no home setup on the machine (no home plugin installed, no `AGENTBOARD_PLUGINS`,
texts, facts or Twilio variable, no `~/.config/agentboard/home.env`), the new board gets `[board] profile = "work"` in its `config.toml` and `init` says so: the board listens on
loopback only, makes no outside request, starts no program and loads no plugin, and `agentboard selfcheck` proves it (details: [On a work laptop](#on-a-work-laptop)). At a
terminal it asks first (Enter means yes). To use the `claude` rounds, `run`, voice and plugins instead, answer no, delete that line, or start with `agentboard init --profile home`
(`$AGENTBOARD_INIT_PROFILE=home|work|auto` sets the default). A board that already exists, and any machine that shows a home setup, is never changed.

`serve` runs in the foreground, prints the URL and data directory (in a terminal; output may be delayed if redirected to a file), and opens your default browser
(`--no-open` to skip, `--port N` to change the port). Leave it running; agents use the CLI from other terminals
**in the same project directory** (or anywhere with `AGENTBOARD_DIR=/path/to/project/.agentboard` set).

Then give your agents the protocol. Paste the output of this into your project's `CLAUDE.md` / `AGENTS.md`:

    agentboard instructions

## The agent lifecycle

    ID=$(agentboard start "Refactor billing" --name atlas)   # prints the task id, e.g. refactor-billing
    agentboard update "$ID" 50 "Extracted BillingService"                 # prints: refactor-billing: 50%
    agentboard ask "$ID" "Deploy to staging or prod?"                     # blocked on the user
    agentboard review "$ID" "All call sites migrated" --next "nothing"    # work complete -> handed to the user; --next says what they do

Or, for a task that already exists on the board: `agentboard claim <id> --name atlas`.

To add acceptance lines or a note to a card (yours or another agent's), or reword it: `agentboard edit <id> --append "text" --name atlas` (or `--append-file`; `--title`, `--description` and `--description-file` replace). The old description is kept on an append, the change is logged under your name, and the card's holder and column never change.

### Agent chat: agents talking to each other (opt-in)

Off by default. The Chat panel then carries status lines and the agents' answers to you (a threaded reply, a detail, a card link, a
long answer cut at a word with the rest behind **Detail**); lines from one agent to another wait for the switch. Turn it on, board-wide, with the **Agents talk** switch in the Chat
panel's head or `agentboard chat agents on` (`off`, `status`). Flipping it posts one line to the chat telling ORCH and the agents already
running what to run (they follow the chat; a session learns nothing on its own), the ORCH prompt gains its part (open the channel, read
the inbox when idle, answer, name who takes a handoff, never act on a proposal), and every prompt agentboard produces grows a short protocol: agents
share what they learn, ask each other for help, warn each other before touching a shared file, and hand work off, all on the same
channel, one plain line per message in the agent's colour, with the technical part behind **Detail**. You read it in the Chat panel
and can jump in (`@AGENT-2 …` addresses one agent).

    agentboard chat send "<one line>" --name AGENT-1 --to AGENT-2 --topic help              # topics: status, learn, help, heads-up, handoff
    agentboard chat send "<one line>" --name AGENT-1 --topic heads-up --file static/index.html
    agentboard chat send "<one line>" --name AGENT-1 --to all --topic learn --detail "<the technical part>"   # or --detail-file, --card <id>, --reply-to <n>
    agentboard chat inbox --name AGENT-1 [--wait 120]       # unread, for you or for all; remembers where you got to (.agentboard/chat-cursors.json)
    agentboard chat tail --for AGENT-1 --follow             # the same, streamed

**The real conversation, mirrored.** ORCH and the agents already talk to each other through their sessions' SendMessage tool.
Run `agentboard hooks install` once per project: it adds two Claude Code hooks to the project's `.claude/settings.json`. The first
(PostToolUse on SendMessage) posts each message's first line to the chat as the session that sent it, to whom it went, the rest
behind **Detail**, with a small **msg** chip. A session says who it is the first time it runs `claim`, `start`, `chat` or
`agentboard me --name AGENT-1`; the board keeps that against its session id, so the mirror carries the name (`$AGENTBOARD_NAME`
wins when set). ORCH can register another session when an agent reports its id: `agentboard me --name AGENT-4 --session <id>` (ListAgents `[ref]`s are not session ids). Mirrored lines are not inbox news (the reader already has the message) and the hook never fails an agent: on any
problem it exits quietly. Restart running sessions once after installing. Run `agentboard hooks install --user` instead to put them in `~/.claude/settings.json`: every session on this Mac has them, whatever folder it starts in. Either way the hook commands name the board folder, so a session started in another folder still finds the board. `agentboard doctor` says where the Stop hook is installed and whether its board folder exists. Only a session the board knows is mirrored: one with `AGENTBOARD_NAME` in its shell, or one that ran `agentboard me --name <name>`; a session in another project posts nothing, so the user-level install is safe to have on a Mac with other work on it. The settings file is written through a temp file in its folder; the file as it was before agentboard ever touched it is kept once as `settings.json.orig`, the version before the last write as `settings.json.bak`, and a symlinked one keeps its link.

**Nobody answers a message to a sleeping session.** A Claude Code session that has finished its turn reads nothing until something
wakes it, and the board cannot reach into a session; a line you type to an agent would sit in its inbox. What wakes a session is a
wait it left running in the background, `agentboard chat inbox --name AGENT-4 --wait 3600` (or `answer CARD --wait` on its card), which
exits when your line arrives. Every prompt says to keep one running between cards, the board lists who does
(`.agentboard/chat-listeners.json`, by pid), and the second hook (Stop) tells a session that is about to go quiet with an unread line
from you, or with no wait running, before it does; it never blocks twice in a row. In the ORCH drawer, an agent's thread and the card
panel, each line you send one agent carries a receipt: **delivered** (in its inbox), **read** (its wait printed it), **answered** (it replied to that line with
`--reply-to <n>`, which the prompts tell agents to do) or **wrote back** (a later line to you not marked as a reply to it). A line older than a day, or one to an agent listed under `[hud] retired`, shows plain sent or delivered: no warning, no Nudge. After a minute unread the line says whether the agent is listening and, when it is not, offers **Nudge via ORCH**: the
board asks ORCH, in its own thread, to message that session (ORCH's SendMessage is the one thing on the machine that wakes an idle
session). A line to ORCH itself cannot be nudged: if ORCH is not listening, type in its terminal or boot one with Copy prompt. ORCH listens the same way (`agentboard chat inbox --name ORCH --wait 3600`). Every posted line also moves `.agentboard/chat-wake.json` (a counter and a time, no words), so a wait watches that one file and wakes within a second, and an ORCH that runs on a schedule instead of a wait can tell in one stat whether anything was posted. A line that nobody is listening for says so in the chat panel after a minute, for ORCH and for any agent, with a Nudge: for an agent it asks ORCH to message that session; for ORCH it moves the wake file.

**Said casually.** With `[chat] casual = true`, the board gives every agent line (mirrored ones included) a spoken version through
the cheap model: the same facts, names, numbers and card ids, in one friendly line that reads aloud; the panel shows that, with
the line as written and its detail behind **As written**. The owner's own lines, the board's notices and the drafter's lines (already in
the voice) are left alone, as is anything shorter than a sentence. `agentboard chat casual --once` runs a round by hand;
`casual_per_hour` (default 60) caps the spend, about `casual_per_hour × idle_budget_usd` an hour at most.

**Chat never does anything.** An action that is not a card's own work (spend, deploy, dial, a change outside the card) is a proposal:
`--propose "<the action>"` puts it on the channel with **Approve** / **Decline** buttons in the panel (or `agentboard chat approve <n>` /
`decline <n>`); the agent reads the decision with `agentboard chat approvals --name AGENT-1` and acts only after approval.

**Shared memory.** An agent that lost the thread on earlier work, its own or a peer's, reads it back from the board instead of asking:

    agentboard recall "<a few words>"      # cards, updates and history that match (every agent's, archived too), and chat
    agentboard recall --card <id>          # one card's whole history
    agentboard recall --agent AGENT-2      # what a peer has been doing

**Lookup: answer a question from what the board already knows.** `agentboard lookup "a few words"` searches done and archived cards
(title, description, result, status line, body, history) and the board's reports, and prints the best few matches, each with its source,
date and a short snippet around the hit, never whole files: `--in cards|reports` picks one, `--limit N` (default 5, at most 20) says how
many, `--list-sources` says what can be searched, `--json` prints the same as data. It is read-only: it writes nothing (not to a card, a
report, a log, a backup or the page), opens no socket and starts no program, and every snippet is cleaned of control and invisible
characters and printed as quoted data (a card made from a text stays marked as one). A plugin can add a source of its own with
`api.add_source(name, help, search)`; with plugins off there are none, and `AGENTBOARD_LOCKDOWN` removes them. (`recall` also covers open
cards and chat; `lookup` is for finished work.)

**Idle time, on a cheaper model.** An agent with no card can keep the conversation going without spending its own session's tokens:
`agentboard chat idle --name AGENT-1 --wait 300 --send` waits for a message, then drafts one reply from the inbox and the board's
memory through the local `claude` binary on `[chat] idle_model` (default `haiku`, capped at `[chat] idle_budget_usd`, default $0.05 a
draft), and posts it. Without `--send` it only prints the draft. This is the same opt-in path as `agentboard run`: nothing else leaves
the machine, and no permission is widened. Pacing: lines that land together are revealed one at a time in the panel; nothing slows the agents.

**Autopilot: the board answers for idle agents.** A Claude session reads nothing while it waits for input, so with nobody prodding
them the chat stays quiet. With `[chat] autopilot = true` in `config.toml`, `agentboard serve` runs a round every `autopilot_every`
seconds (default 180): for each `[orch] agents` name with no card in Doing and unread chat, one draft on the cheaper model, posted
as that agent and marked **auto** (the agent's own session sees it in its inbox, so it knows what was said for it). The board never
answers itself: an auto line is not a prompt for another round, so two idle agents cannot chatter at each other, and `autopilot_per_hour` (default 12, over
every agent) bounds the spend at about `autopilot_per_hour × idle_budget_usd` an hour. `agentboard chat autopilot --once` runs one
round by hand; without `--once` it loops, for a board served by an older install.

**Volunteering, in a voice.** The drafts are written to read aloud: short sentences, contractions, names, no lists, code only in the
detail. And an idle agent with nothing to answer offers, every `share_every_min` minutes (default 60; 0 turns it off), one thing from
its own finished work that bears on a card a colleague is on right now (a gotcha, how something is actually wired, what a service
needed), as a *learned* line to that agent ending in a question; only its own cards feed that, so it never speaks for a peer, a tip
nobody is about to need is not posted, and it skips what the chat already says. `agentboard chat idle --name AGENT-1 --share [--send]`
does the same by hand. The board also stays out of an awake agent's way: an agent that spoke or touched a card in the last
`live_min` minutes (default 20) gets no auto line, so a live session and the board never answer the same message. Drafts know the
date and the age of every card, treat done cards and day-old asks as closed, never post a bare acknowledgement, and end an answer
with one real question back when there is one.

### Handing a card to an agent

There is no Assign button. Press **Copy prompt** on the card, paste it into the agent's terminal, and the agent claims the card itself
(`agentboard claim <id> --name <agent>`); its name lands on the card. The Done column shows a 7-day ribbon of what was finished.

### Reports: action first

Every prompt agentboard produces (Copy prompt, the `agentboard run` prompt, the instructions snippet, the ORCH prompt) ends with one rule:

> Report to the user in one sentence, one idea: the ACTION they must take first, then one fact. If nothing is needed from them, one line of status.
> If more is unavoidable, one sentence, then offer the detail. Put that sentence on the card (ask/review/update text) so the user answers you there, and in your terminal. Put detail in `--body` (it shows under Details on the card), never in the first line.

On the board, a card in **ask** or **review** shows that sentence as its first line, large, with a one-line **reply box** on the card. A reply is stored
on the card (and in its log), and the agent reads it with `agentboard answer <id>` (`--wait` polls until there is one; `--timeout`, `--interval`).
It is cleared when the agent moves on (its next update, ask, review or claim). Agents therefore report to you directly, and ORCH does not have to relay.

### Voice: speak instead of type (on this Mac only)

A small **mic** button sits beside the add-card box, the chat box and every reply box: click, speak, click again, and the words land in the box.
The clip goes only to the board's own `/api/transcribe`, where [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (`brew install whisper-cpp`, plus `ffmpeg`)
turns it into text. No browser speech service, no account, nothing uploaded; the buttons are hidden when whisper or a model is missing. The first click asks the browser for the microphone.
The model is any ggml file: `[voice] model = "~/path/ggml-small.en.bin"` in `config.toml` or `AGENTBOARD_WHISPER_MODEL`; otherwise the first copy it finds from other apps (read only).

For a Claude Code terminal (ORCH or an agent): `agentboard dictate` (Enter, speak, Enter) prints the text and puts it on the clipboard; press Cmd+V in the session.
`--paste` presses Cmd+V for you after 3 seconds in the window you click (needs Accessibility for the terminal); `--file clip.m4a` transcribes a recording; `--mic ":2"` picks an input.

### By agent

The **By agent** tab (or the key `a`) shows the same cards as swimlane columns. The **Todo** column comes first and is the very same
narrow column the board draws: every Todo card (an assigned one carries its agent's name), the queue number, Copy prompt and Later in one
foot row. After it comes one column per agent with a card in Doing (its ask, review or quiet state in the header, its cards stacked).
There is no Done column here (it stays on the board), so the agents get the width. A card opens its panel as usual, and drags as on Board: onto Todo, or onto a lane (a lane is Doing). A drop never changes who holds a card, so
another agent's lane refuses it (red outline, no insertion line, a toast says why); a Todo card with no agent that you drop on a lane goes to Doing under Unassigned. On a phone it is one column per screen, swipe sideways.

### Story

**Needs you** (the third tab, the key `3`, `/need`) is the cards waiting on you, one at a time: the card open in the middle, the ones before it as strips
above and the ones after it as strips below, asks first and then sign-offs. `↑` `↓` (or a scroll, or a click on a strip) moves through the pile, `→` opens the
card's details beside it, `Enter` goes to the reply box, and `Space` twice sends the card's first answer. An answered card leaves and the next one opens.
`1`, `2`, `3` switch between Board, By agent and Needs you. Every card in Doing carries one **You** line saying what you owe it: Answer, Sign off, Close it, Check on it, or Nothing. On By agent, a rule under a waiting agent's name shows how long it has waited and how many Todo cards it holds.

**Story** (`/story`, linked from the Done column) is the work in plain words, five scenes you scroll: a sentence and a ring (finished this week, in progress, waiting);
a flow from Waiting to Working to Done with every card a dot, one colour per theme; one card per theme with a one-line sentence and "n of m done"; only what
is waiting on you (or a calm "nothing"); and what was finished each day. A theme is a work area named by a word several titles share, as in the Done
summary, or the agent on the cards when none is shared. It is written from the board's own cards with fixed templates: no model, no network, nothing started,
so it is the same on the work profile. It follows light and dark, a phone width and reduced motion (no entrance animation at all). Every card on it is a link:
click a dot, a theme's sentence or a row under "Needs you" (or Tab to it and press Enter) and the board opens with that card's panel; Back returns to the Story.

### Done summary

**Summary** on the Done column header (and `/summary?since=1d|7d|30d|all&agent=<name>`) turns the finished cards into one page about the work
itself, not the management of it: one number and three plain facts; a bar of the kinds of change (added, fixed, improved, tested, documented,
explored, found from the card titles and asks); a **work map** (each agent's cards split into work areas found from shared title words, sized by cards,
washed with the main kind of change; click an area for its cards); then each agent as collapsed work areas. A card row is the title and the
outcome in one line (numbers in bold) and opens to what was asked, the full result, the timeline and links to the board card and its report.
The search box and a click on a kind scope the whole page. Everything is drawn in the page itself (inline SVG, no outside scripts), both themes,
phone width. **Copy text** puts the summary on the clipboard as markdown, **Copy Mermaid** a mindmap of agents and areas to paste where
Mermaid renders (GitHub, Obsidian, Notion), **Save as HTML** downloads the page.
On the command line: `agentboard summary [--since 7d] [--agent <name>] [--html <path>] [--mermaid]`.

**Keep it simple.** The ORCH prompt carries a named `Keep it simple` block (one sentence, one idea, detail on demand) that ORCH copies into every card description and assignment it writes. It is instructed, not checked. `update`, `ask` and `review` take `--body` / `--body-file`, or a multi-line text whose first line is the sentence and the rest the body; the card shows the sentence large and the rest behind a collapsed **Details** fold.

The older three-line shape is still understood and drawn as bands and chips, if an agent prefers it (three lines at most):

    ACTION  you: tap Call me once; it rings your mobile         # <none> | you: … | ORCH: … | AGENT-N: …
    STATUS  telephony-kill-switch done-ready                      # one card per line: done-ready | blocked | 40%
    WHY     one short outbound call                               # only if it changes the action

Lines, or ` | ` between the parts, both work. The card panel shows the ACTION line as a coloured band
(the person named = the colour: you red, the orchestrator amber, another agent cyan), STATUS as chips, the
rest as text. The HUD lights the agent's row with the same colour and prints the ACTION in full. Numbered
steps written as `(1) … (2) …` render one per line. Details that don't change the action go on the card log
(`agentboard update`), not in the message.

- Before claiming/starting a card, if anything about it is ambiguous, ask your orchestrator/coordinating
  session a one-line question (e.g. via SendMessage) and wait for its answer first — it can often answer
  from its view of the whole board, and escalates to the user if it can't. One-time check before you start,
  not an ongoing back-and-forth once work is underway.
- Use your own session name so agents are distinguishable (`AGENTBOARD_NAME` works as the default). The board gives each name its own colour; to pick one, set `[agent_colors]` in config.toml. `--color` is still accepted and ignored.
- The percentage is what the list/HUD show at a glance — keep it honest and call `update` again whenever your real % done changes, even to walk it back after discovering more work.
- `ask` and `review` clear automatically on the agent's next `update`. `review` sets progress to 100% but the card stays in Doing (marked ready for review) until the user marks it done.
- If you started the server in the background, stop it with `pkill -f "agentboard serve"` (Ctrl+C when it runs in the foreground).
- **Never run `agentboard done` yourself as an agent**; only the user does (Mark done button, drag, or telling the agent to).
- One task per deliverable, not per command; keep status lines to one line.

Humans: `agentboard add "Title" --status todo` (or `--status backlog` for the Later drawer), `agentboard list`. A new card lands at the top of its column.

## One orchestrator, several agents

The workflow this was built for: one coordinating session (**ORCH**) and N worker sessions (**AGENT-1 … AGENT-N**),
each a Claude Code / Codex / Devin terminal in the same repo.

- **ORCH** adds and splits cards (`agentboard add`, `--blocked-by`, `--parent`), hands ids to agents, relays the
  user's decisions, reviews `review` cards and is the only one besides the user who moves them to Done when the user says so.
- **Each agent** renames its session (`/rename AGENT-3`), claims its card with `--name AGENT-3`,
  keeps exactly one card open while it works, reports with `update`, finishes with `review`, and never marks done.
- **Between sessions** they use their tool's cross-session messaging (Claude Code: `SendMessage` / `ListAgents`) for
  one-to-one asks, and `agentboard chat` for anything the user should see. Both carry the ACTION / STATUS / WHY shape.
- **Shared files:** announce an edit to a file another agent is in on chat first, rebase before each commit, commit
  only your own paths (`git add <paths>`, never `-A`).
- **The user** watches the board or the HUD, answers asks, marks cards done. The HUD title shows "● 2 for you"
  when something is waiting.

`agentboard instructions` prints the agent snippet for your `CLAUDE.md` / `AGENTS.md`; the repository's own
[`CLAUDE.md`](CLAUDE.md) is a worked example.

## Dependencies

Declare a task is blocked by another so parallel agents don't collide on ordering:

    agentboard add "Title" --blocked-by <task_id>              # repeat --blocked-by for more than one
    agentboard start "Title" --name atlas --blocked-by <task_id>
    agentboard claim <id> --name atlas                         # refuses while a blocker isn't done (--force to override)

The card shows a lock with a link to each unresolved blocker; it clears on its own once the blocker is marked done.

## Subtasks

Split a big card into subtasks (one level deep). A subtask is a normal task with a parent:

    agentboard add "Title" --parent <parent_id>                  # follows the parent's column
    agentboard start "Title" --name atlas --parent <parent_id>   # an agent adding one mid-flight
    agentboard claim <parent_id> --name atlas                    # takes the parent AND all its open subtasks
    agentboard update <sub_id> 60 "wiring it up"                 # each subtask has its own %, status line and log
    agentboard review <parent_id> "result" --next "nothing"      # the deliverable is ready; open subtasks close with it

- Subtasks follow their parent: an open subtask can only be claimed or updated while the parent is in Doing, so
  claim the parent first. Finished subtasks stay done if the parent later moves back.
- A subtask at 100% **closes itself** (no review step), is shown as completed inside its parent's card (with the done sound), while the parent stays
  in Doing. Agents never call `review`/`done` on a subtask.
- The parent's % is **computed** (the mean of its subtasks, shown as "6% overall" on the board and with a Σ in `list`). `update <parent>` only sets its status
  line. The parent does not auto-review: the agent calls `review <parent>` when it is ready.
- On the board the parent has one total bar (the computed "overall" %) next to `done/total`, which is also the expand toggle:
  Doing parents start open, the rest collapsed. Every subtask is a quiet row under it with its own thin progress
  bar (finished ones show a check and 100%); click one for its own detail.
- `done <parent>` (you) marks whatever is left done, `rm <parent>` removes the subtasks too, and the Done
  column only ever shows parents. `blocked-by` works between subtasks.
- `list` indents subtasks under their parent, the HUD feed labels their events "parent › subtask" (the agent rows and
  totals count the parent only), and `report` groups them under the parent.

## The board

Columns Todo / Doing / Done plus a **Later** drawer (`l`). A Doing card silent for 10 minutes turns amber; one silent
past a much longer threshold (default 120 min; `[board] stale_minutes` in config.toml) gets a louder red "abandoned?"
marker instead — a crashed or forgotten agent session doesn't just sit there quietly forever. It's surface-only: nothing
is auto-moved or auto-released, so a human still decides what to do (see `agentboard list --stale` below). **needs input**
and **ready for review** cards pulse and bubble to the top. Click a card for its question, result and activity history.
Drag to move; keyboard: arrows or `j`/`k`, Enter opens, `/` filters, `n` new task, `?` lists shortcuts. Shift-click (or
focus a card and Shift+↑/↓) to range-select, ⌘/Ctrl-click to add/remove one — a toolbar appears to move or archive
the whole selection at once. Light, dark, or system theme; optional sounds.

## Chat

A shared channel (`c`, or the Chat button) for agents to self-organize in the open instead of only
over private messages — who's on what, asking for a hand, splitting or handing off work — so it's
visible to you, not buried in a terminal. Type in the same panel to join the conversation yourself:

    agentboard chat send "<message>" --name atlas
    agentboard chat tail [--limit N] [--follow]          # --follow polls and streams new messages

## Card reports

When a card enters **review** (or **done**), agentboard writes one self-contained HTML page for it: `.agentboard/reports/<card-id>-<YYYYMMDD-HHMMSS>.html`.
One idea per line: the card and its agent, the one-sentence ACTION for you at the top, what was built (the agent's text and update history), the commits made
while the card was open (linked when the repo's `origin` is on GitHub; a one-shot run lists exactly its own branch), test totals the agent wrote down, files touched,
how to try it (the agent's "How to try" section and any URLs), and **Mark done** / **Send back with a note** buttons that call the board's API. A sent-back note is the reply the
agent reads with `agentboard answer`. Optional extras: an agent can write `.agentboard/reports/<card>.md` and it appears as "More from the agent".

The card carries a solid **Open report** button (new tab). The list of all reports is the **Reports** link beside Summary on the Done column header, at `/reports/` (under `/b/<name>/` for other boards); `agentboard reports` prints it.
Reports age out: on `serve` start and then hourly, those older than `[reports] keep_hours` (default 24) are deleted, **except the newest per card**, and nothing else is ever
touched (not `tasks.json`, not backups, not your `.md` extras). `agentboard reports` lists them; `agentboard reports --purge [--hours N]` runs the sweep now. Set the repo whose
commits are listed with `[reports] repo = "~/dev/project"` (default: the folder above `.agentboard`). Everything an agent wrote is escaped, and the pages are served with a
locked-down Content-Security-Policy; they only talk to your own board.

## Several boards

One board per project folder is still the default. To keep others (work, personal, a side project), register them by name:

    agentboard board new work --color blue     # creates ~/.agentboard/boards/work/.agentboard and registers it
    agentboard board add side ~/code/side/.agentboard   # name a board you already have
    agentboard board list                       # names, folders, colours; * marks `use`
    agentboard board use work                   # the board used when the folder has no .agentboard
    agentboard board rm work                    # forget it (its cards and folder are never deleted)

Pick a board from any folder with `--board work` (before the command) or `AGENTBOARD_BOARD=work`. Which board a command uses, first match wins:
`--board` / `AGENTBOARD_BOARD`, then `AGENTBOARD_DIR`, then the nearest `.agentboard/` above the current folder, then `board use`.

One `agentboard serve` shows them all: the board of the folder it starts in stays at `/` and `/hud` (existing links keep working), every registered
board is at `/b/<name>/` and `/b/<name>/hud`, and a board switcher appears in the header once there is more than one. A board's `color` tints the top of its header.
The registry is `~/.agentboard/boards.toml` (move it with `AGENTBOARD_HOME`). Each board keeps its own hourly snapshots and its own `[backup] sync_dir`
in its own `config.toml`; nightly copies are named after the board's folder, so give boards different folder names if they share a sync folder.

## Your data and backups

**Secrets are masked on the way in.** A key an agent echoes, a token in a command it ran or a private key in a review body is replaced by `[redacted …]` before it is stored, so it never reaches `tasks.json`, the backups, the card's report, the page or the chat. Only strings that cannot be ordinary text are touched (cloud and API keys with their prefixes: AWS, `sk-`, Stripe, Google `AIza`, GitHub, Slack and Slack webhooks, npm, SendGrid; tokens, JWTs, private-key blocks, `Authorization:` and bare `Bearer` values, the password in `scheme://user:password@host`, `api_key = "…"`-style assignments including `aws_secret_access_key`, `?key=…` in a URL, a long hex string right after *key*, *token* or *secret*; a short password such as `hunter2` is not recognisable and is not caught); commit hashes, ids, paths, code and phone numbers read as written, and what you type yourself (a reply, a send-back note, your chat lines) is left alone. The Terminal tab masks the same shapes in the lines it shows (a command with a key in it, a line you typed), without touching the session's own file. `[redact]` in `config.toml` turns it off, adds phone numbers, or adds your own patterns. `agentboard redact` lists what is already stored; `--apply` masks it after a snapshot.

**Private by default.** The command line and `serve` run with umask 077, so everything the board writes (cards, chat, reports, run logs, config, session ids, snapshots, the `sync_dir` copy) is mode 0600 in folders 0700, and `serve` tightens what an older version left readable. A Mac home folder is not private (other accounts can read into it), so this matters even on one machine. Programs the board starts for you (`claude -p` runs, provider commands) and files meant for others (the project's `.gitignore`, `.claude/settings.json`, a `summary --html` page) keep your own umask. `AGENTBOARD_UMASK=022` turns it off for a folder you share on purpose.

**Start, stop, restart, status.** `agentboard serve` runs the board in the terminal (Ctrl+C stops it, after the requests in flight finish); `agentboard serve --background`
starts it detached, with its output in `.agentboard/server.log`, and prints the pid once `/api/health` answers. `agentboard status`
says running or not, with the pid, the port, since when, the uptime, the plugins loaded and whether the lockdown is on (exit 1 when
nothing runs); a server file left by a crash or a `kill -9` is cleaned and said. `agentboard stop` sends SIGTERM and waits until the
server has finished the requests in flight and is gone; `agentboard restart` stops it and starts it again on the same port with this
shell's environment, one line with the old and new pid. A taken port says who holds it (this board's own server, another board's, or
something else) and what to do. `stop` signals only a process that is really an `agentboard serve` (its command line says so), never a pid a crash left behind that another program now has. `/api/health` answers on the loopback with no board data: `{ok, agentboard, pid, port, started, uptime_s,
plugins, lockdown}`. `agentboard doctor` warns about stale server files.

Everything is one file, `.agentboard/tasks.json`; the browser keeps only your theme and sound choices, so clearing it loses nothing.
Every save is atomic and keeps the previous version as `tasks.json.bak`. Snapshots land in `.agentboard/backups/` (one an hour,
kept 48 hours hourly and 30 days daily) whenever the board is saved or `agentboard serve` is running. Set `[backup] sync_dir` in
`config.toml` to an iCloud Drive or Google Drive folder and the newest snapshot is copied there once a night. The HUD shows the age
of the newest snapshot. Commands: `agentboard backup` (now), `agentboard verify` (is the file sound, is `tasks.json.bak`, are the small
state files beside it valid JSON, any temp file left by an interrupted write, how old is the newest snapshot, and a restore test: the
newest snapshot put back into a scratch folder must load as a board; `--fix` also removes leftover temp files and sets a state file that
is not JSON aside as `<name>.broken-<stamp>`), `agentboard restore latest` or `agentboard restore <file>` (keeps a copy of what it
replaces). The small state files (chat cursors, listeners, sessions) are written the same atomic way and updated under
a lock, so two agents at once lose nothing and a kill mid-write leaves the old file or the new one; a corrupt one is read as empty until
the next write. A corrupt `tasks.json` is refused with one line that names the good copy (`.bak` or the newest snapshot, with its card
count) and the command that restores it. All local files, no network.

`agentboard watchdog` lists every way the board is stuck between agents (a claim nobody worked, a holder that vanished, twin cards, a card
held by one agent with subtasks held by another, an orphan subtask, two sessions under one name), each with its one fix; `--fix N` (or
`all`) does it and writes one history line. The Load view shows the same rows with a button each, and `agentboard doctor` carries a
`watchdog` line (a WARN, so `doctor --strict` exits 1 while a claim is stale).
`agentboard wrapup` is the end of the day: it sorts every Doing card into finish (at 100%, never handed in), waiting on you (stays), back to Todo tonight (best first, so tomorrow starts with the card nearest done) and still running (left alone). `--ask` leaves each agent a note on its card to `agentboard checkpoint` (done so far, the next step, what it learned) or to review; `--apply`, on your word, releases the Todo-bound cards with their notes and saves the page to `.agentboard/wrapups/<date>.md`; `--last` reads it back the next morning. The ORCH drawer's End of day button asks ORCH to run it. The next morning the board opens the saved page as a Start of day sheet, once, on the first load of the day (`w` opens it any time); a row opens its card and says if it has moved since.
`agentboard rollup` is the whole board in one page for ORCH or the owner (who waits on a person, what each agent holds and how long it has been quiet, what is stuck, the Todo queue, what finished and what it learned, and the moves that follow); `agentboard release <id> | --agent NAME` sends Doing cards back to the top of Todo. A card sent back (by `release`, the `b` key, the panel's Back to Todo, a drag or the watchdog) keeps its progress, its history and what its agent learned: the card says "Resumes at 60%", and the next agent's prompt has an Earlier work section with the notes, so the work continues instead of restarting. A review body can end in a `## Learned` section (a decision and why, a trap hit, where the work lives), which the done card shows.
`agentboard dedupe` finds twin cards (an `<id>-2` made when an agent ran `start` for work it already held) and `--apply` merges them;
`start` and `claim` no longer make twins.

## Sync

Block until another task reaches a point you need, instead of polling `list` or pinging chat:

    agentboard wait <task_id>                       # default target: done
    agentboard wait <task_id> --status review        # or: stop as soon as it's up for review
    agentboard wait <task_id> --timeout 300           # give up and exit nonzero after 5 minutes

`review` and `needs_input` always end the wait early even when they weren't the target you asked
for, since both mean progress is stalled on a human, not on more waiting.

## The HUD (Load)

Press `h`, click `Load ›` at the end of the gauge strip, or open `/hud` in its own window (second monitor). The board's Todo and Doing columns on the left, the same
cards as Board and By agent (they glide across on the switch), then the **Agents** column where Board's Done column is:

- **One card per agent**, every agent, idle ones too: the pill, the age, and the agent's **60-minute load bar** (working /
  waiting on you / in review, gaps are idle). The card's border and edge take the agent's state the Board's way (red when
  it needs your answer or sign-off, green at review, red edge when the agent went quiet past `[board] stale_minutes`,
  default 120). What the Doing card beside it says (title, status, %, the ask) is not repeated. An idle agent is the
  quiet card with a dimmed bar.
- **The Queue** (unclaimed Todo cards over the hour) is the last card; the legend and the time axis sit in the foot.
- Cards that need a person sort to the top; click one to open the card. The header's summary counts asks, reviews and
  abandoned, and the window title says "● 2 for you".
- `[hud] retired = ["AGENT-5"]` in `config.toml` hides agents you no longer run (their cards and history stay).
- Optional synthesized sound cues (Sound and Ambient bed switches in Settings, the gear on every view; `s` turns sound on or off anywhere). The sounds, ambient bed included, play on every view (Board, By agent and Load), one bed at a time even with several pages open; a fresh page waits for your first click or key, as browsers require. Settings (`m`) also has a Volume slider: 100% is the usual level, and up to 300% goes through a limiter so it cannot clip; and the extra layers, each with its own switch and level and off until you choose it: Rain, Wind, Pad, Pulse, Echo, Signatures, All clear, Hourly chime. Settings > Sound opens with Scenes (one-click mixes: Classic is today's sound, then Focus, Control room and Night) and Quiet hours (a sleep schedule: silent inside the window except a soft chime for a card that asks you something, with a header chip to end it early), and has a Cues level and a live output meter beside Volume; Stage, Humanize and Day bookends are three more layers, off until chosen. Touch, the one layer that starts on, is the quiet set of UI sounds for what your hands do (focus, open, drag and drop, tabs, drawers, switches, select, copy, errors). Motion pairs a look with a sound (a settle when an agent's card lands in a lane and, on By agent, a new lane sliding in with it; the green edge drawing in at review; the check drawing in at Done; a crossfade between views), off until you choose it. Lively makes the small moments move (a ring where a card lands, counts that roll, a subtask ticking itself in, a % that pops, an empty column that breathes, a toast that springs); From the future (Off, Subtle, Full) turns the board into a holographic HUD with scanlines, corner brackets, readouts, a boot and a scan sweep, never hiding anything and stopping every movement under reduced motion; both off until you choose them. More sound, each off until chosen: Chimes (the small moments), Deep space and Tide (ambience), Duck the bed (the bed dips under a cue) and Future sound (the look's own). Stacks on narrow windows, bars under the text.

## Daily recap

A markdown summary of what got done today (or any day), grouped by agent, built from the same
"marked done" / activity-log data the HUD already tracks — read-only, CLI-only, meant to paste
straight into a standup or a daily log:

    agentboard report [--date YYYY-MM-DD]

## Notifications (opt-in)

**From the board tab:** the bell in the top bar turns on desktop notifications through the browser's own Notification API (local, no
service, no new dependency). While the tab is in the background you get one when a card needs an answer (and again every 15 minutes
while it waits), once when a card is ready for sign-off, and once when an agent goes quiet; clicking it brings the tab back and
opens the card. In front, the cards and the sounds already say it.

**From the terminal, on macOS:** off by default. Turn on native macOS banners for **needs input** and **ready for review** so you don't have to
keep the board or HUD open to notice a blocked or finished agent:

    [notify]
    enabled = true
    sound = "Glass"      # optional; omit for a silent banner

Fires via `osascript` — the same no-new-dependency mechanism `agentboard spawn` already uses — whenever any
`agentboard ask`/`review` runs, from any agent, in any terminal.

## Local-only and safety

`agentboard doctor` checks this machine and prints short PASS / WARN / FAIL lines you can paste into a security review: the ports the board listens on (loopback only?), any connection to another machine, whether `AGENTBOARD_LOCKDOWN` (the master lock) and the narrow locks are set, in this shell and in the running server (each `agentboard serve` records how it was started in `server-<pid>.json` in the board folder: yes/no answers and plugin names only), whether plugins are off and which are installed (read from package metadata, nothing is loaded), which `config.toml` switches would start a program or send data out, whether secret masking is still on and unchanged (`[redact]` can turn it off, and that file is writable by anything running as you), which files `config.toml` reads into card prompts (names only; under the lock a path outside the project folder is refused), whether the board folder can be read by other users (an empty folder says nothing alarming), whether the installed copy still carries a file its source no longer has (a stale install: `pipx uninstall agentboard; pipx install <repo>`), whether the board is ignored by git and no key or phone number is in the tracked files, the Claude Code hooks installed, and the version and commit. With plugins on (`AGENTBOARD_PLUGINS=1`, no lock) it also loads them exactly as `agentboard serve` would and says which failed to load (by error class only), then prints each plugin's own checks as `<plugin>:<check>` lines (one masked line each; a check that raises is one FAIL naming the class). With plugins off or locked nothing is imported. It is read-only: it changes nothing and opens no socket (it asks `ps`, `lsof` and `git`), and it never prints a secret, only the kind, file and line. Exit code 1 on any FAIL (`--strict`: on any WARN too); `--project DIR` picks the folder to scan.

Findings below come from the audit in `SECURITY.md` in the repository root (v0.2.0, re-checked for v0.3.0 on 2026-10-24). Nothing here is a claim about your organization's policies; check those yourself.

**How it runs**
- One Python process (`agentboard serve`) listening on **`127.0.0.1:8765`** only. The bind address is hard-coded;
  there is no option to listen on other interfaces. Only `--port` is configurable.
- It rejects requests with a foreign `Host` header (DNS rebinding) and POSTs with a foreign `Origin` or non-JSON body.
- There is **no authentication**: any process or user on the same machine can reach the local port.

**Where data lives**
- `.agentboard/tasks.json`, `.agentboard/config.toml`, `.agentboard/.lock` in your project. Nothing is synced anywhere.
- The browser keeps 5 UI preferences in `localStorage` (theme, sound, ambient, volume, the sound layers).
- **`agentboard init` adds `.agentboard/` to your project's `.gitignore`** (creating the file if needed), because tasks can contain private context. Check it landed: `grep agentboard .gitignore`.

**Network behavior**
- **Python:** no third-party dependencies (`dependencies = []`). The only code that can reach beyond localhost is in the opt-in
  context providers (`providers.py`): the `http` provider (a GET to a URL *you* configure) and the `command` provider (a shell command *you* configure).
  Every provider in the default config is commented out, and providers run only when a task lists one with `--ctx` and a prompt is built.
- **Browser:** the page makes only same-origin requests to the local server. No CDN, web fonts, external scripts, analytics, or update checks; icons are inline SVG, sounds are synthesized.
  When re-checking, loading the board, a card and the HUD in headless Chrome produced 22 requests, all to `localhost`; the server process held only its listening socket (no outbound connections).
- **Other network moments:** `agentboard serve` opens `http://localhost:<port>/` in your default browser (`--no-open` to skip).
  Installing fetches files once (GitHub if you install from the git URL; setuptools from PyPI when building). After that nothing is fetched.

**Check it yourself** (the two `grep` lines need the source tree, so run them from a checkout of the repo; `lsof` works anywhere)

    grep -n "urllib.request\|subprocess\|socket\|webbrowser" src/agentboard/*.py      # the only network/exec code
    lsof -nP -iTCP -sTCP:LISTEN | grep -i python                                       # expect 127.0.0.1:8765 only
    grep -n "https\?://" src/agentboard/static/index.html                              # expect only an SVG namespace string

**On a work machine:** skip `http`/`command` providers, or point them only at local services; use `--no-open` if you don't want a browser launched.

## Configuration (`.agentboard/config.toml`)

`agentboard init` writes the file with every option commented out. Every key, with its type, range, default and meaning: [`docs/config.md`](docs/config.md), generated from the schema. `agentboard config check` flags a misspelt key (with the closest valid name), a wrong type or a value out of range (the default applies to it, never a guess) and an unsafe switch; `agentboard config show` prints what applies to this board and where each value came from. The short form:

    [board]
    owner = "you"                 # your name: replaces "the user" in every prompt and "you" on the board, the HUD and report pages
    stale_minutes = 120           # a Doing card silent this long is marked "abandoned?" on the board and the HUD

    [voice]
    words = ["Acme"]              # names the dictation should spell right (your name and the agents' are already included)

    [hud]
    retired = ["AGENT-5"]         # agents hidden from the HUD; their cards and history stay

    [ui]
    dispatch = false              # hide Copy prompt and the prompt preview

    [notify]
    enabled = true                # native macOS banner on ask / review
    sound = "Glass"               # optional

    [prompt]
    template_file = "prompt.md"   # replaces the built-in prompt template

    [providers.<name>]            # context providers for prompts: markdown | file-tail | http | command
    type = "markdown"             # see the commented examples init writes; off until a task lists one with --ctx

Environment: `AGENTBOARD_DIR` (the board to use from anywhere), `AGENTBOARD_BOARD` (a registered board name), `AGENTBOARD_HOME` (where the registry lives), `AGENTBOARD_NAME` (the default for `--name`).

## One-shot agents

`agentboard run <card>` hands a card to a non-interactive `claude -p` that works on its own and is closed when it is done:

    agentboard run fix-the-widget --name AGENT-7 --budget 3 --max-minutes 30        # in the foreground
    agentboard run fix-the-widget --detach                                          # returns at once (what ORCH uses)
    agentboard runs                                                                 # live and finished runs, with time and cost
    agentboard runs --kill fix-the-widget                                           # the kill switch (the card's "Stop run" button does the same)

What happens: the card's prompt (the same text as Copy prompt) plus a short rules block (report in three lines, finish with `review`, `ask` when
blocked, never dial, text, buy or deploy) goes to `claude -p`, started in a **fresh git worktree** next to the repo (`<repo>-wt/run-<card>-<id>`; pass
`--cwd DIR` to work in an existing folder as it is). The card is claimed under `--name` and shows a `▶ run` badge. When claude exits the card moves
to **review** (or to **ask**, with the tail of the output, if the run failed, hit the time limit or the budget, or was stopped), its cost and duration
are written on the card, and the worktree is removed only if this run created it and it is clean (otherwise the card says where it is).
Per-run files are in `.agentboard/runs/<card>/<run id>/` (`prompt.md`, `stdout.json`, `stderr.log`, `run.json`).

Limits and safety: a hard wall-clock limit (`--max-minutes`, default 45) and a spend cap passed to claude (`--budget`, default $5); set your own defaults
with `[run] budget_usd` and `max_minutes` in `config.toml`. The run uses **the same permission settings an interactive agent in that folder would**: agentboard
never passes `--dangerously-skip-permissions`, `--permission-mode` or `--allowedTools`. A headless run cannot answer a permission prompt, so allow what a card
needs (at least `Bash(agentboard:*)`) in the project's `.claude/settings.json` yourself. Only one run per card at a time; subtasks run through their parent.
Point at a different claude binary with `AGENTBOARD_CLAUDE` or `[run] claude`.

## Plugins

A separate Python package can extend agentboard: a command, API routes under `/api/x/<name>/`, a block of state on the board's poll, a background thread, a page script (a header slot, a Settings slot, a card chip), a source for `lookup`, and its own lines in `agentboard doctor` (`api.add_doctor(fn)`: read-only checks of the plugin's own setup, printed as `<plugin>:<check>`, masked). agentboard ships with none and knows nothing about any particular one; with none loaded it looks and works exactly as it would without the feature.

A plugin loads only when the machine says so: `AGENTBOARD_PLUGINS=1` (exactly `1`) in the shell that runs agentboard. `AGENTBOARD_NO_PLUGINS=1` and `AGENTBOARD_LOCKDOWN=1` both beat it, and both are read on every call, so a lock set after the board started closes every plugin route at once. While plugins are off nothing is looked up, imported or shown. `agentboard plugins` says which state you are in and what is loaded; it makes no network call.

A plugin is an entry point in the group `agentboard.plugins` whose value is a function taking one argument, `api` (see the top of `src/agentboard/plugins.py` for what it can register and the guarantees: nothing outside its own `/api/x/<name>/`, no shadowing a core command, a failing plugin costs only itself, an error reaches the client as its class name). A plugin is code you installed and switched on; it is trusted like any package. A route can be registered `browser=True` (`api.add_route("POST", "do", fn, browser=True)`): the server then answers 403 unless the request carries `Sec-Fetch-Site: same-origin`, which a browser sets for the board's own page and a bare `curl`, an agent's shell or a script does not. It is a speed bump against a naive or prompt-injected request, not a wall: a program running as you can send the header, and read the board folder directly.

A command a plugin adds exists only where the plugin is loaded: from a plain shell (no key, or a lock) `agentboard <that command>` fails as an unknown command and adds one line to stderr saying plugins are off and the command may be a plugin's; run it from the board's shell, with its environment.

The text-message features (turning texts into cards, an inbound-SMS webhook) are not part of agentboard: they live in a separate package that is kept outside this repository.

## Prompts and context providers (optional)

Todo cards carry a copyable prompt that makes any agent claim the card and report progress. Prompts are assembled from
providers in `.agentboard/config.toml` (`markdown`, `file-tail`, `http`, `command`; options `max_chars`, `redact`, `private`).
Providers run only when a task lists one with `--ctx` and a prompt is built. A `markdown` or `file-tail` provider reads a file inside the project folder (the one holding `.agentboard/`, links followed): that includes `.env`, `.git/config` and `.agentboard/` itself, so point one only at files you would paste into a prompt; under `AGENTBOARD_LOCKDOWN` a path outside the project is refused.

Two rules for a `command` provider. **Do not wrap `{arg}` or `{title}` in quotes** in `run`: each is already shell-quoted when it is
filled in, so `grep "{arg}" notes.md` becomes `grep "'tailor pants'" notes.md` and a crafted argument can step out of your quotes;
write `grep {arg} notes.md`. And since building a prompt *runs* these commands, the board refuses to build one for a request a browser
marks as coming from another site (`Sec-Fetch-Site: cross-site`, e.g. an `<img>` on a hostile page pointing at `/api/prompt`); the
Copy prompt button, the CLI and `agentboard prompt` are unaffected.

## Commands

| For you | |
|---|---|
| `init` / `serve [--port N] [--no-open]` | create the board / run it |
| `add "Title" [--status todo\|backlog] [-d TEXT] [--ctx NAME] [--blocked-by ID] [--parent ID]` , `list [--all] [--stale]`, `rm <id>` | manage tasks (`--parent` makes a subtask) |
| `tail [-n LINES] [--interval SECS]` | watch activity live in the terminal — same feed as the HUD, for CLI-only sessions |
| `run CARD [--name N] [--cwd DIR] [--budget USD] [--max-minutes M] [--detach]`, `runs [--kill CARD]` | run a card with a one-shot `claude -p`; list and stop runs |
| `plugins` | say whether plugins are allowed on this machine and which are loaded (no network call) |
| `answer ID [--wait] [--timeout S]` | print the reply you left on a card (agents use it to read your answer) |
| `reports [--purge] [--hours N]` | list card reports; remove the old ones now |
| `report [--date YYYY-MM-DD]` | markdown recap of what got done that day, by agent — for a standup or daily log |
| `clear` | archive all Done cards: they move to `archive.json` (history and HUD counts kept) |
| `demo [--live]`, `rm --demo` | sample tasks / simulated agents |
| `prompt <id> [--public]`, `rebuild [id] [--all]`, `instructions` | prompts and the agent snippet |

| For agents | |
|---|---|
| `start "Title" --name N [--blocked-by ID] [--parent ID] [--force]` | create a task already in Doing; prints its id |
| `claim <id> --name N [--force]` | take an existing task and its subtasks (refuses while blocked, unless `--force`) |
| `update <id> <0-100> ["text"]` , `ask <id> "q" [--body MD]`, `review <id> "result" [--body MD]` | report |
| `done <id>` | user-approved only |
| `wait <id> [--status X] [--timeout SECS]` | block until a task reaches a status — sync without polling |
| `chat send "msg" --name N [--user]`, `chat tail [--limit N] [--follow]` | self-organize with other agents, visible to the user |

## On a work laptop

**One switch, one proof.** On a fresh install with no home setup, `agentboard init` turns it on for the new board by itself (see [Quick start](#quick-start)). Elsewhere: `agentboard profile work` (this machine, every board; or `export AGENTBOARD_PROFILE=work`, or `agentboard init --profile work` for one board)
turns the whole list below on at once and keeps it on: the master lock, plugins refused, no outbound connection and no name lookup of anything but this machine in
any command, listening only on loopback, no program started by the server, no browser opened, private file modes. Then `agentboard selfcheck` proves it in a PASS/FAIL
list: a static scan of every source file (what may use the network, start a program, run dynamic code or load a package, each against a short table with its reason),
a live audit of a throwaway server (every route requested, a scripted day of work, with the run-time guards recording every attempt) and the red-team checks (wrong Host,
cross-site POST, content types, oversized and malformed bodies, request smuggling, path traversal, symlinks, a JSON bomb, a stalled client, a flood of connections,
providers that try to reach a URL or run a command). Exit code 1 on any FAIL. Details: [`SECURITY.md`](SECURITY.md#the-work-profile-and-agentboard-selfcheck).

What to expect when you clone this onto a managed machine (the full audit and checklist: [`docs/security-audit-2026-11-07.md`](docs/security-audit-2026-11-07.md)):

1. **Needs:** `git`, Python 3.9+ (`python3 --version`; the system Python of a Mac or Ubuntu 22.04 is enough), and `pipx` (or a venv, see [Install](#install)). Nothing else; there are no dependencies, and no admin rights: everything lands under your home folder.
2. **Get it from a copy you reviewed and pin the commit:** `git clone https://github.com/troygdaniel/agentboard && cd agentboard && git checkout <reviewed commit> && pipx install .`
   The only network use is that one fetch (plus `setuptools>=68` from PyPI while building). Nothing runs at install: no setup script, no `.pth`, no lock file.
3. **Set the master lock in the shell profile that starts the board:** `export AGENTBOARD_LOCKDOWN=1`. It refuses everything that would start a program or send
   data out (the `claude` rounds and `agentboard run`, the `command` and `http` providers, the `[backup] sync_dir` copy, voice, spawn and every plugin), even if a
   copied `config.toml` says otherwise. Add `export AGENTBOARD_NO_PLUGINS=1` as a second lock for plugins. Do not set `AGENTBOARD_PLUGINS`.
4. **Check it:** `agentboard doctor` prints PASS / WARN / FAIL lines you can paste into a review (want 0 FAIL, 0 WARN with the lock set). `agentboard plugins` says
   plugins are locked; `lsof -nP -a -p $(pgrep -f "agentboard serve" | head -1) -i` shows one line, `127.0.0.1:8765 (LISTEN)`.
5. **Run it:** `cd <your repo> && agentboard init && agentboard serve --no-open`, then open `http://localhost:8765` yourself. The server listens on `127.0.0.1` only.
   **There is no login:** any program running as the same user can reach the port (websites cannot). It is for one person per machine; an optional key-cookie lock was
   written but is not part of this release (see `SECURITY.md`, "Known gaps").
6. **No personal data in the repo:** the repository is code, docs and screenshots of demo boards. Your task data lives in `<your repo>/.agentboard/` (mode 700, files 600),
   which `init` git-ignores. If your repo is shared, keep it that way, and run `python3 tests/publiccheck.py` before any push.
7. **Updating:** `git pull`, review, `rm -rf build && pipx install . --force`, then restart `agentboard serve`. (Remove `build/` first: otherwise a module deleted from the source can come back into the installed copy; `agentboard doctor` warns if it did.)

## Troubleshooting

- `agentboard: command not found`: run `pipx ensurepath` and open a new terminal.
- `no board found; run agentboard init`: run it in your project, or set `AGENTBOARD_DIR`.
- `cannot listen on port 8765`: another board is running; use `agentboard serve --port 8766`.
- **A plugin (or the board) crashed on load, or a feature's buttons vanished from Settings** (Nov 7: the home plugin's two data files were not in its package, so it failed to import for hours while every test passed, because tests run from `src/`). Run `agentboard doctor` with plugins on: `FAIL plugin <name> failed to load: <ErrorClass>` names it, and the plugin's own `home:files` line says which file. Fix the package-data list, reinstall.
- **The board runs but a feature is silently off after a restart** (Nov 7: a restart from a different terminal dropped the environment variables, so every opt-in key read as unset). Keys are environment variables of the *server's* shell, not of yours: start `agentboard serve` from the shell that has them (or a script that loads them first), then `agentboard doctor`, whose `server` and plugin lines say what the running server was started with.
- **Something you deleted from the source is back after reinstalling** (Nov 7: a stale `build/` folder put removed modules back into the installed copy). `rm -rf build` in the checkout, then `pipx install . --force`; `agentboard doctor` warns `stale install` and prints the fix. `pipx upgrade` from the GitHub URL never has this problem.
- **`agentboard doctor` says `FAIL tracked files`** on your own repo: it found a key-shaped string, a non-fictional phone number or a private key block in a tracked file (it prints the file and line, never the text). Rotate the key if it is real; if it is a test fixture, build it from pieces (`"AKIA" + "..."`) or use the 555-01xx numbers reserved for fiction.
- **`ModuleNotFoundError: tomllib`** on Python 3.9 or 3.10: you have an agentboard older than this note; upgrade. Since then the board reads TOML with its own small reader where the standard library has none.
- **`pipx: command not found`** right after installing pipx: `python3 -m pipx ensurepath`, then open a new terminal (pipx adds `~/.local/bin` to PATH for new shells only).
- **A first run of `agentboard doctor` shows WARN lines**: `lock` (set `AGENTBOARD_LOCKDOWN=1` on a work machine; at home the WARN is expected), `plugins ON` (you turned them on), `config` (a switch in config.toml would start a program or send data). Every WARN names the switch; `--strict` makes them count as failures for a review.

## Development

    python -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/python -m unittest discover -s tests

The suite runs with a network guard (`tests/netguard.py`): a test that opens a connection to anything but loopback fails with the guard's name in the message. `AGENTBOARD_TEST_NET=1` turns it off for one run. The security sign-off for a reviewer is [`docs/security-signoff.md`](docs/security-signoff.md).

How it is built, file by file: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). How to work on it (cards, worktrees, the gates, the changelog rule): [`CONTRIBUTING.md`](CONTRIBUTING.md). Every document, one line each: [`docs/index.md`](docs/index.md).

MIT licensed.
