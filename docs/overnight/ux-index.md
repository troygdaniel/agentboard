# Overnight UX branches (AGENT-4), in the order to merge them

All four are stacked: each branch contains the ones above it, so merging the last one brings everything, and merging them one by one in this order never conflicts
with itself. Nothing is merged or pushed. Each has its own evidence file in this folder.

| # | Branch | What it does | Evidence |
|---|---|---|---|
| 1 | `overnight/overnight-ux-firstrun` (4f3bcba) | welcome for a bare `agentboard`, guided `init`, nearest-command hint, plain errors, **New task** and **?** buttons, sample cards button, 60-second tour, plain empty states | `overnight-ux-firstrun.md` (and `ux-firstrun/` screenshots) |
| 2 | `overnight/overnight-ux-init-agent-instructions` (ffc8fa3) | `init` offers to add agentboard's instructions to CLAUDE.md or AGENTS.md (append-only, marked, idempotent) | `overnight-ux-init-agent-instructions.md` |
| 3 | `overnight/overnight-ux-nav-and-panel-words` (f8cf575) | plain tooltips on the header tabs, Later, Copy prompt and the ORCH pill | `overnight-ux-nav-and-panel-words.md` |
| 4 | `overnight/overnight-ux-doctor-agents-line` (tip of the stack) | `doctor` says which agents have reported and whether CLAUDE.md has the lines; shared helpers in `agentfiles.py` | `overnight-ux-doctor-agents-line.md` |

## The 30-second review

    cd ~/dev/agentboard && git checkout overnight/overnight-ux-doctor-agents-line      # everything above
    rm -rf build && pipx install . --force
    mkdir /tmp/try && cd /tmp/try && agentboard            # the welcome; then: agentboard init, agentboard serve --port 8799

## Decisions waiting for Troy

- Sound on by default on a first run (card `decision-should-sound-be-off-on-a-board`).
- Whether `init` should ever touch a project file (branch 2): drop the question and keep only `--instructions` if not.
- A bare `agentboard` now exits 0 with a welcome (it was exit 2 with a usage error), and `list --status` rejects a word that is not a column.

## Cards filed from the walkthrough (not done overnight)

`ux-subtask-ids-collide-across-agents-ste`, `ux-by-agent-hides-lanes-past-the-fifth-w`, `decision-should-sound-be-off-on-a-board`.

## Merge-conflict watch

`src/agentboard/static/index.html` is also edited by the visual-polish branch: my hunks are the header (two buttons and five tooltips), the `#welcome` block and its CSS, the `EMPTY` strings, one JS
block after `toggleKeys`, and two Esc guards. `README.md` is untouched.
