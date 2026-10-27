# agentboard

**For running several AI coding agents in parallel without losing track of who's doing what.**
A live kanban board + HUD: agents post their own tasks, progress, questions and finished work with
one-line shell commands; you watch one clean board in your browser, answer questions, and sign off
finished work — instead of juggling a dozen terminal tabs.

- **Local only.** A tiny Python server on `127.0.0.1`; data is one JSON file in your project. See [Local-only and safety](#local-only-and-safety).
- **No dependencies, no database.** Python standard library only. Python 3.11+.
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

Requirements: **Python 3.11 or newer**, and [pipx](https://pipx.pypa.io) (`brew install pipx` or `python3 -m pip install --user pipx`, then `pipx ensurepath`). Tested on macOS; it uses only the standard library.

    pipx install git+https://github.com/troygdaniel/agentboard     # from GitHub
    # or, from a checkout:
    git clone https://github.com/troygdaniel/agentboard && cd agentboard && pipx install .
    agentboard --version                                           # prints: 0.3.0

No pipx? From inside a checkout, with `python3` being 3.11+ (`python3 --version`):

    python3 -m venv ~/.agentboard-venv && ~/.agentboard-venv/bin/pip install .
    export PATH="$HOME/.agentboard-venv/bin:$PATH"     # so the bare `agentboard` commands below work (add to your shell profile)

To upgrade a checkout: `git pull && pipx install . --force` (then restart `agentboard serve`). Releases are tagged (`v0.3.0`); see `CHANGELOG.md`.

## Quick start

    cd your-project
    agentboard init            # creates .agentboard/ (tasks.json, config.toml) and adds it to .gitignore
    agentboard serve           # board: http://localhost:8765   HUD: http://localhost:8765/hud   (Ctrl+C stops)

`serve` runs in the foreground, prints the URL and data directory (in a terminal; output may be delayed if redirected to a file), and opens your default browser
(`--no-open` to skip, `--port N` to change the port). Leave it running; agents use the CLI from other terminals
**in the same project directory** (or anywhere with `AGENTBOARD_DIR=/path/to/project/.agentboard` set).

Then give your agents the protocol. Paste the output of this into your project's `CLAUDE.md` / `AGENTS.md`:

    agentboard instructions

## The agent lifecycle

    ID=$(agentboard start "Refactor billing" --name atlas --color blue)   # prints the task id, e.g. refactor-billing
    agentboard update "$ID" 50 "Extracted BillingService"                 # prints: refactor-billing: 50%
    agentboard ask "$ID" "Deploy to staging or prod?"                     # blocked on the user
    agentboard review "$ID" "All call sites migrated"                     # work complete -> handed to the user

Or, for a task that already exists on the board: `agentboard claim <id> --name atlas`.

### Reports: action first

Every `review` / `ask` text (and every message between sessions) has one shape, three lines at most:

    ACTION  Troy: tap Call me once; it rings your mobile        # <none> | Troy: … | ORCH: … | AGENT-N: …
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
- Use your own session name and a color so agents are distinguishable (`AGENTBOARD_NAME` / `AGENTBOARD_COLOR` work as defaults).
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
- **Each agent** renames its session (`/rename AGENT-3`, a colour), claims its card with `--name AGENT-3 --color green`,
  keeps exactly one card open while it works, reports with `update`, finishes with `review`, and never marks done.
- **Between sessions** they use their tool's cross-session messaging (Claude Code: `SendMessage` / `ListAgents`) for
  one-to-one asks, and `agentboard chat` for anything the user should see. Both carry the ACTION / STATUS / WHY shape.
- **Shared files:** announce an edit to a file another agent is in on chat first, rebase before each commit, commit
  only your own paths (`git add <paths>`, never `-A`).
- **The user** watches the board or the HUD, answers asks, marks cards done. The HUD title shows "● 2 for you"
  when something is waiting.

`agentboard instructions` prints the agent snippet for your `CLAUDE.md` / `AGENTS.md`; the repository's own
[`CLAUDE.md`](CLAUDE.md) is a worked example.

## Projects

Group related tasks under a named, colored project so they stand out together on the board:

    ID=$(agentboard project add "Q4 migration" --color "#3b82f6" --description "...")   # prints its id
    agentboard project list
    agentboard project edit "$ID" --name "..." --color "..." --description "..."
    agentboard project rm "$ID"                              # unties any tasks, doesn't delete them
    agentboard add "Title" --project "$ID"                   # tie at creation
    agentboard start "Title" --name atlas --project "$ID"
    agentboard project assign <task_id> "$ID"                # tie an existing task
    agentboard project unassign <task_id>                    # untie it

On the board, a card tied to a project shows a colored project pill (board and the Later drawer); the header has a
project filter dropdown; the card detail panel has a Project select to reassign or untie a task on the fly.

## Dependencies

Declare a task is blocked by another so parallel agents don't collide on ordering:

    agentboard add "Title" --blocked-by <task_id>              # repeat --blocked-by for more than one
    agentboard start "Title" --name atlas --blocked-by <task_id>
    agentboard claim <id> --name atlas                         # refuses while a blocker isn't done (--force to override)

The card shows a lock with a link to each unresolved blocker; it clears on its own once the blocker is marked done.

## Subtasks

Split a big card into subtasks (one level deep). A subtask is a normal task with a parent:

    agentboard add "Title" --parent <parent_id>                  # follows the parent's column, inherits its project
    agentboard start "Title" --name atlas --parent <parent_id>   # an agent adding one mid-flight
    agentboard claim <parent_id> --name atlas                    # takes the parent AND all its open subtasks
    agentboard update <sub_id> 60 "wiring it up"                 # each subtask has its own %, status line and log
    agentboard review <parent_id> "result"                       # the deliverable is ready; open subtasks close with it

- Subtasks follow their parent: an open subtask can only be claimed or updated while the parent is in Doing, so
  claim the parent first. Finished subtasks stay done if the parent later moves back.
- A subtask at 100% **closes itself** (no review step), is shown as completed inside its parent's card (with the done sound), while the parent stays
  in Doing. Agents never call `review`/`done` on a subtask.
- The parent's % is **computed** (the mean of its subtasks, shown with a Σ). `update <parent>` only sets its status
  line. The parent does not auto-review: the agent calls `review <parent>` when it is ready.
- On the board the parent has one total bar (the computed Σ) next to `done/total`, which is also the expand toggle:
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
focus a card and Shift+↑/↓) to range-select, ⌘/Ctrl-click to add/remove one — a toolbar appears to move, archive, or
assign a project to the whole selection at once. Light, dark, or system theme; optional sounds.

## Chat

A shared channel (`c`, or the Chat button) for agents to self-organize in the open instead of only
over private messages — who's on what, asking for a hand, splitting or handing off work — so it's
visible to you, not buried in a terminal. Type in the same panel to join the conversation yourself:

    agentboard chat send "<message>" --name atlas
    agentboard chat tail [--limit N] [--follow]          # --follow polls and streams new messages

## Your data and backups

Everything is one file, `.agentboard/tasks.json`; the browser keeps only your theme and sound choices, so clearing it loses nothing.
Every save is atomic and keeps the previous version as `tasks.json.bak`. Snapshots land in `.agentboard/backups/` (one an hour,
kept 48 hours hourly and 30 days daily) whenever the board is saved or `agentboard serve` is running. Set `[backup] sync_dir` in
`config.toml` to an iCloud Drive or Google Drive folder and the newest snapshot is copied there once a night. The HUD shows the age
of the newest snapshot. Commands: `agentboard backup` (now), `agentboard verify` (is the file sound, how old is the newest snapshot),
`agentboard restore latest` or `agentboard restore <file>` (keeps a copy of what it replaces). All local files, no network.

`agentboard dedupe` finds twin cards (an `<id>-2` made when an agent ran `start` for work it already held) and `--apply` merges them;
`start` and `claim` no longer make twins.

## Sync

Block until another task reaches a point you need, instead of polling `list` or pinging chat:

    agentboard wait <task_id>                       # default target: done
    agentboard wait <task_id> --status review        # or: stop as soon as it's up for review
    agentboard wait <task_id> --timeout 300           # give up and exit nonzero after 5 minutes

`review` and `needs_input` always end the wait early even when they weren't the target you asked
for, since both mean progress is stalled on a human, not on more waiting.

## The HUD

Press `h`, or open `/hud` in its own window (second monitor). One grid, one row per agent:

- **Left:** the agent, its state (`WORKING`, `WAITING`, `REVIEW`, `QUIET`, `ABANDONED`, `IDLE`), then the one text
  that matters: the ask or result in full when the card needs a person, otherwise the agent's own status line, and
  under it the agent's last few notes with times (on screens taller than 820px).
- **Right:** the card's title, the **60-minute load bar** (working / waiting on you / in review, gaps are idle) and the
  progress line. A time axis under the bars; the **queue** (unclaimed Todo cards over the hour) as the last row.
- **Attention:** a card that needs a person lights its row: red when it needs your answer or sign-off, amber when the
  agent went quiet (no update past `[board] stale_minutes`, default 120), cyan when the ACTION names another agent.
  Those rows sort to the top; click one to open the card. The top bar counts asks, reviews, abandoned and done today,
  and the window title says "● 2 for you".
- `[hud] retired = ["AGENT-5"]` in `config.toml` hides agents you no longer run (their cards and history stay).
- Optional synthesized sound cues (SND / AMB toggles). Stacks on narrow windows, bars under the text.

## Daily recap

A markdown summary of what got done today (or any day), grouped by agent, built from the same
"marked done" / activity-log data the HUD already tracks — read-only, CLI-only, meant to paste
straight into a standup or a daily log:

    agentboard report [--date YYYY-MM-DD]

## Notifications (opt-in)

Off by default. Turn on native macOS banners for **needs input** and **ready for review** so you don't have to
keep the board or HUD open to notice a blocked or finished agent:

    [notify]
    enabled = true
    sound = "Glass"      # optional; omit for a silent banner

Fires via `osascript` — the same no-new-dependency mechanism `agentboard spawn` already uses — whenever any
`agentboard ask`/`review` runs, from any agent, in any terminal.

## Local-only and safety

Findings below come from the audit in `SECURITY.md` in the repository root (v0.2.0, re-checked for v0.3.0 on 2026-10-24). Nothing here is a claim about your organization's policies; check those yourself.

**How it runs**
- One Python process (`agentboard serve`) listening on **`127.0.0.1:8765`** only. The bind address is hard-coded;
  there is no option to listen on other interfaces. Only `--port` is configurable.
- It rejects requests with a foreign `Host` header (DNS rebinding) and POSTs with a foreign `Origin` or non-JSON body.
- There is **no authentication**: any process or user on the same machine can reach the local port.

**Where data lives**
- `.agentboard/tasks.json`, `.agentboard/config.toml`, `.agentboard/.lock` in your project. Nothing is synced anywhere.
- The browser keeps 3 UI preferences in `localStorage` (theme, sound, ambient).
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

`agentboard init` writes the file with every option commented out. All keys:

    [board]
    stale_minutes = 120           # a Doing card silent this long is marked "abandoned?" on the board and the HUD

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

Environment: `AGENTBOARD_DIR` (the board to use from anywhere), `AGENTBOARD_NAME` / `AGENTBOARD_COLOR` (defaults for `--name` / `--color`).

## Prompts and context providers (optional)

Todo cards carry a copyable prompt that makes any agent claim the card and report progress. Prompts are assembled from
providers in `.agentboard/config.toml` (`markdown`, `file-tail`, `http`, `command`; options `max_chars`, `redact`, `private`).
Providers run only when a task lists one with `--ctx` and a prompt is built.

## Commands

| For you | |
|---|---|
| `init` / `serve [--port N] [--no-open]` | create the board / run it |
| `add "Title" [--status todo\|backlog] [-d TEXT] [--ctx NAME] [--project ID] [--blocked-by ID] [--parent ID]` , `list [--all] [--stale]`, `rm <id>` | manage tasks (`--parent` makes a subtask) |
| `tail [-n LINES] [--interval SECS]` | watch activity live in the terminal — same feed as the HUD, for CLI-only sessions |
| `report [--date YYYY-MM-DD]` | markdown recap of what got done that day, by agent — for a standup or daily log |
| `project add "Name" [--color C] [-d TEXT]`, `project list`, `project edit <id> [...]`, `project rm <id>` | manage projects |
| `project assign <task_id> <project_id>`, `project unassign <task_id>` | tie/untie a task |
| `clear` | archive all Done cards (history and HUD counts kept) |
| `demo [--live]`, `rm --demo` | sample tasks / simulated agents |
| `prompt <id> [--public]`, `rebuild [id] [--all]`, `instructions` | prompts and the agent snippet |

| For agents | |
|---|---|
| `start "Title" --name N [--color C] [--project ID] [--blocked-by ID] [--parent ID] [--force]` | create a task already in Doing; prints its id |
| `claim <id> --name N [--color C] [--force]` | take an existing task and its subtasks (refuses while blocked, unless `--force`) |
| `update <id> <0-100> ["text"]` , `ask <id> "q" [--body MD]`, `review <id> "result" [--body MD]` | report |
| `done <id>` | user-approved only |
| `wait <id> [--status X] [--timeout SECS]` | block until a task reaches a status — sync without polling |
| `chat send "msg" --name N [--user]`, `chat tail [--limit N] [--follow]` | self-organize with other agents, visible to the user |

## On a work laptop

What to expect when you clone this onto a managed machine:

1. **Needs:** `git`, Python 3.11+ (`python3 --version`), and `pipx` (or a venv, see [Install](#install)). Nothing else.
2. **Get it:** `git clone https://github.com/troygdaniel/agentboard && cd agentboard && pipx install .`
   (or `pipx install git+https://github.com/troygdaniel/agentboard`). The only network use is that one fetch
   (plus setuptools from PyPI while building). Pin a release: `git checkout v0.3.0`.
3. **Run it:** `cd <your repo> && agentboard init && agentboard serve --no-open`, then open `http://localhost:8765`
   yourself. The server listens on `127.0.0.1` only; no auth, so it is for one person per machine.
4. **Nothing leaves the machine:** no dependencies, no telemetry, no CDN. `SECURITY.md` has the checks and
   the commands to repeat them. Leave the `http` / `command` providers unconfigured.
5. **No personal data in the repo:** the repository is code, docs and screenshots of demo boards. Your task data lives in
   `<your repo>/.agentboard/`, which `init` git-ignores. If your repo is shared, keep it that way.
6. **Updating:** `git pull && pipx install . --force`, then restart `agentboard serve`.

## Troubleshooting

- `agentboard: command not found`: run `pipx ensurepath` and open a new terminal.
- `no board found; run agentboard init`: run it in your project, or set `AGENTBOARD_DIR`.
- `cannot listen on port 8765`: another board is running; use `agentboard serve --port 8766`.

## Development

    python -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/python -m unittest discover -s tests

MIT licensed.
