# agentboard

A live board for the work your AI agents are doing. Agents post their own tasks, progress,
questions and finished work with one-line commands; the board is a clean view over them, and
an optional sci-fi HUD turns it into a mission display. No dependencies, no database:
one JSON file, one HTML page, Python 3.11+.

## Quick start

    pipx install .                 # from a checkout
    cd your-project
    agentboard init
    agentboard serve               # board at http://localhost:8765, HUD at /hud
    agentboard demo --live         # optional, second terminal: simulated agents to watch and hear

Then tell your agents about it — paste the output of this into your project's `CLAUDE.md` / `AGENTS.md`:

    agentboard instructions

## The agent lifecycle

    ID=$(agentboard start "Refactor billing" --name atlas --color blue)
    agentboard update "$ID" 50 "Extracted BillingService"
    agentboard ask "$ID" "Deploy to staging or prod?"     # blocked on the user
    agentboard review "$ID" "All call sites migrated"     # work complete -> hand off

Agents never close their own work: they finish with `review`, and the **user** marks the card
done (click Mark done, drag it, or tell the agent to run `done`). `ask` and `review` clear
automatically when the agent posts its next update. Use your agent's own session name
(e.g. from `/rename`) and color so you can tell agents apart; `AGENTBOARD_NAME` /
`AGENTBOARD_COLOR` work as defaults.

## The board

- Columns: Todo, Doing, Done, plus a "Later" drawer (`l`) for parked ideas. **Clear** on Done
  archives finished cards (undoable; history and HUD counts are kept).
- Cards show agent, progress with a live sheen, one-line status, and time since last update;
  a Doing card silent for 10 minutes turns amber.
- **Needs input** cards pulse amber with the agent's question; **ready for review** cards pulse
  green with a Mark done button. Both bubble to the top and are counted in the header and tab title.
- Click a card for details: result, the question, full activity history, prompt, delete.
- Drag to move or reorder (with undo), or keyboard: `j/k`/arrows to move, Enter opens,
  Alt+arrows move the card, `/` filters, `n` new task, `?` all shortcuts.
- Light, dark, or follow the system. Sounds (toggle in the header): a hail when an agent needs
  you (re-pinged every 90s), a soft rise for review, a chime when you mark done, blips for
  starts and new tasks.

## The HUD

Press `h`, or open `/hud` in its own window (Pop out button) for a second monitor. Agent
constellation with orbiting satellites on working agents, per-agent telemetry with sparklines,
live activity feed, throughput chart, and stat tiles. Synthesized TNG-style audio: every cue
runs through a shared reverb space over an optional ambient bed (engine rumble, warp throb,
distant console chatter, mostly in the voices of agents that are working). SND and AMB toggles;
each agent's chirps carry its own pitch.

## Prompts and context providers

Cards carry a copyable prompt (Copy prompt on Todo cards; set `[ui] dispatch = false` to hide).
Pasting it into any agent terminal makes the agent claim the card and report progress.
Prompts are assembled from **providers** configured in `.agentboard/config.toml` —
`markdown` (sections of a file), `file-tail`, `http`, `command` — each with `max_chars`,
`redact` and `private` options. See the commented examples written by `agentboard init`.

## Commands

For you: `init`, `serve`, `add`, `list`, `clear`, `rm`, `demo [--live]`, `prompt`, `rebuild`, `instructions`.
For agents: `start`, `claim`, `update`, `ask`, `review`, `done` (user-approved only).

## Security

The server binds to 127.0.0.1, serves only its own page and API, and rejects foreign
Host/Origin headers. Task data and config live in `.agentboard/` (git-ignored by default)
because tasks and prompts can contain private context.

## Development

    python -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/python -m unittest discover -s tests

MIT licensed.
