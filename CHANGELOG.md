# Changelog

## Unreleased

### Card reports
- A card entering review or done gets an HTML report in `.agentboard/reports/` (action first, what was built, commits with links, tests, files, how to try it, Mark done / Send back). A Report link on the card, a Reports list in the header, `agentboard reports [--purge]`, and an ageing sweep (`[reports] keep_hours`, default 24; the newest per card always stays). `POST /api/send-back` sends a card back with a note the agent reads with `agentboard answer`.

### One sentence to Troy
- Every prompt (Copy prompt, run prompt, instructions snippet, ORCH prompt) ends with the reporting rule: one sentence, the ACTION first then one fact; no action needed = one line of status; more = one sentence then offer the detail. The ORCH prompt now says agents report to Troy directly, when ORCH may speak to him, daytime vs sleep assigning, and what is never done without his own words.
- Ask and review cards show that sentence as the first line, large, with a reply box on the card. The reply is stored on the card and read with `agentboard answer <id> [--wait]`; it clears when the agent moves on.

### Text the board
- `agentboard sms serve`: an opt-in Twilio inbound-SMS webhook on its own port (`127.0.0.1:8766`) that adds and moves cards and replies with one line. Needs `[sms] enabled`, an allowlist, an https `public_url` and the auth token in the environment. Signature check, sender allowlist, MessageSid replay protection and an hourly cap; refused requests get nothing back. `agentboard sms try TEXT` runs a command locally. SECURITY.md updated.

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
