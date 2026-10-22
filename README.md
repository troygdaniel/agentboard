# agentboard

**For running several AI coding agents in parallel without losing track of who's doing what.**
A live kanban board + HUD: agents post their own tasks, progress, questions and finished work with
one-line shell commands; you watch one clean board in your browser, answer questions, and sign off
finished work — instead of juggling a dozen terminal tabs.

- **Local only.** A tiny Python server on `127.0.0.1`; data is one JSON file in your project. See [Local-only and safety](#local-only-and-safety).
- **No dependencies, no database.** Python standard library only. Python 3.11+.
- **Agents never close their own work.** They finish with `review`; *you* mark the card done.

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

To upgrade a checkout: `pipx install . --force`.

## Quick start

    cd your-project
    agentboard init            # creates .agentboard/ (tasks.json, config.toml)
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

Humans: `agentboard add "Title" --status todo` (or `--status backlog` for the Later drawer), `agentboard list`.

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

## Sync

Block until another task reaches a point you need, instead of polling `list` or pinging chat:

    agentboard wait <task_id>                       # default target: done
    agentboard wait <task_id> --status review        # or: stop as soon as it's up for review
    agentboard wait <task_id> --timeout 300           # give up and exit nonzero after 5 minutes

`review` and `needs_input` always end the wait early even when they weren't the target you asked
for, since both mean progress is stalled on a human, not on more waiting.

## The HUD

Press `h`, or open `/hud` in its own window (second monitor). From the top: **throughput** over the last hour,
**telemetry** per agent (state, task, progress, activity sparkline), and **agent load**: one swimlane per agent over the
same hour, showing working time, time waiting on you, time in review and idle gaps, plus tasks done today and a queue-depth
lane. An agent idle past the stale threshold shows as **ABANDONED** (red) in telemetry and on its lane, same threshold
and marker as the board. Optional synthesized sound cues (SND / AMB toggles).

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

Findings below come from the audit in `SECURITY.md` in the repository root (v0.2.0 plus later commits), re-checked against the code
when this README was written. Nothing here is a claim about your organization's policies; check those yourself.

**How it runs**
- One Python process (`agentboard serve`) listening on **`127.0.0.1:8765`** only. The bind address is hard-coded;
  there is no option to listen on other interfaces. Only `--port` is configurable.
- It rejects requests with a foreign `Host` header (DNS rebinding) and POSTs with a foreign `Origin` or non-JSON body.
- There is **no authentication**: any process or user on the same machine can reach the local port.

**Where data lives**
- `.agentboard/tasks.json`, `.agentboard/config.toml`, `.agentboard/.lock` in your project. Nothing is synced anywhere.
- The browser keeps 3 UI preferences in `localStorage` (theme, sound, ambient).
- **`agentboard init` does not create a `.gitignore`.** Tasks can contain private context, so add `.agentboard/` to your project's `.gitignore` yourself.

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

## Prompts and context providers (optional)

Todo cards carry a copyable prompt that makes any agent claim the card and report progress. Prompts are assembled from
providers in `.agentboard/config.toml` (`markdown`, `file-tail`, `http`, `command`; options `max_chars`, `redact`, `private`).
`agentboard init` writes commented examples. Set `[ui] dispatch = false` to hide Copy prompt.
Set `[board] stale_minutes = N` to change the stale/abandoned threshold (default 120; see [The board](#the-board)).
Set `[notify] enabled = true` for native desktop banners on ask/review (see [Notifications](#notifications-opt-in)).

## Commands

| For you | |
|---|---|
| `init` / `serve [--port N] [--no-open]` | create the board / run it |
| `add "Title" [--status todo\|backlog] [-d TEXT] [--ctx NAME] [--project ID] [--blocked-by ID]` , `list [--all] [--stale]`, `rm <id>` | manage tasks |
| `tail [-n LINES] [--interval SECS]` | watch activity live in the terminal — same feed as the HUD, for CLI-only sessions |
| `report [--date YYYY-MM-DD]` | markdown recap of what got done that day, by agent — for a standup or daily log |
| `project add "Name" [--color C] [-d TEXT]`, `project list`, `project edit <id> [...]`, `project rm <id>` | manage projects |
| `project assign <task_id> <project_id>`, `project unassign <task_id>` | tie/untie a task |
| `clear` | archive all Done cards (history and HUD counts kept) |
| `demo [--live]`, `rm --demo` | sample tasks / simulated agents |
| `prompt <id> [--public]`, `rebuild [id] [--all]`, `instructions` | prompts and the agent snippet |

| For agents | |
|---|---|
| `start "Title" --name N [--color C] [--project ID] [--blocked-by ID] [--force]` | create a task already in Doing; prints its id |
| `claim <id> --name N [--force]` | take an existing task (refuses while blocked, unless `--force`) |
| `update <id> <0-100> ["text"]` , `ask <id> "q" [--body MD]`, `review <id> "result" [--body MD]` | report |
| `done <id>` | user-approved only |
| `wait <id> [--status X] [--timeout SECS]` | block until a task reaches a status — sync without polling |
| `chat send "msg" --name N [--user]`, `chat tail [--limit N] [--follow]` | self-organize with other agents, visible to the user |

## Troubleshooting

- `agentboard: command not found`: run `pipx ensurepath` and open a new terminal.
- `no board found; run agentboard init`: run it in your project, or set `AGENTBOARD_DIR`.
- `cannot listen on port 8765`: another board is running; use `agentboard serve --port 8766`.

## Development

    python -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/python -m unittest discover -s tests

MIT licensed.
