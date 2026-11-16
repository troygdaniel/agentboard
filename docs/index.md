# Documents

One line each. The first three are the ones most people need.

| Document | What it is for |
|---|---|
| [README.md](../README.md) | Using the board: install, quick start, the agent lifecycle, chat, boards, backups, safety, configuration, commands, the work-laptop checklist, troubleshooting. |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | Changing the board: module map, data files and who writes them, a request's path through the server, the agent protocol in code, the plugin hook, the security model on one page, running the tests. |
| [docs/FLAKES.md](FLAKES.md) | The tests that failed once and passed on a rerun: how often, why (load, a Mac asleep, a guessed delay), and what was fixed. Read it before calling a failure a flake. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Working on it: cards and worktrees, the gates before "ready", the changelog rule, commits, where things belong. |
| [docs/config.md](config.md) | Every `config.toml` key with its type, range, default and meaning, generated from the schema (`agentboard config docs`); a test pins it. |
| [SECURITY.md](../SECURITY.md) | What the board does and does not do with your data and your network, what was audited, the known gaps, how to check a machine. |
| [CHANGELOG.md](../CHANGELOG.md) | Every change a user could notice, newest first, with the cards it closes. |
| [CLAUDE.md](../CLAUDE.md) | The prompt an AI agent working in this repository reads: the card protocol, subtasks, chat, the public-repo rules, how to verify UI changes. |
| [docs/security-audit-2026-11-07.md](security-audit-2026-11-07.md) | The Nov 7, 2026 security audit for a managed work laptop: verdict, findings ranked, what was decided, the install and lock checklist. |
| [docs/conversation-reliability-analysis.md](conversation-reliability-analysis.md) | Why a line typed to an agent on the board used to go unanswered: the loss paths, ranked, and the fixes in order (listeners, receipts, the Stop hook, the nudge). |
| [docs/plugins-at-work-design.md](plugins-at-work-design.md) | Design only: how a work machine could run a plugin the owner named and a reviewer checked, off by default; the rules, the install steps, the changes and the choices to approve. |
| [docs/insights-design.md](insights-design.md) | Design only: can the board recommend how to use its agents? What it records now against what the Long Haul retrospective had to reconstruct, ten capture points ranked by cost, the first rules and what they would have said, privacy, the smallest first build. |
| [docs/agent-configurations-design.md](agent-configurations-design.md) | Design only: agent configurations (names plus roles), renaming an agent without losing history, role chips and prompts, the day-to-day approval rules, the smallest build and the choices to approve; a clickable mock-up and its captures sit beside it. |
| [docs/status-visibility-design.md](status-visibility-design.md) | Design only: one page that answers "is anyone waiting on me, what is stuck, who waits on whom": five counters, a row per agent with eight state words and a six-step track, the shared queues, a rule that the board's own sleep never counts as silence, four build slices and six choices to approve; a mock-up and its captures sit beside it. |
| [docs/retro-2026-11-15.html](retro-2026-11-15.html) | The 27-day retro (20 Oct to 15 Nov 2026), one page with charts, light and dark: how the board was used and where it slipped, how the work ran (ORCH's load, merge conflicts by file, what became of the earlier retro's ten changes), the agent configurations for development work, and twelve ranked improvements written as proposed cards. |
| [docs/night-queue-design.md](night-queue-design.md) | Design and how it was built: the Night switch, the queue ORCH lines up and the one command an agent uses to take the next card (retro rec 13); a mock-up sits beside it. |
| [docs/chat-words-design.md](chat-words-design.md) | The words and layout of the chat: who reads a line, receipts, refusals, two sessions under one name. |
| [docs/settings-tabs-design.md](settings-tabs-design.md) | Settings in tabs: what each tab holds, the plugin tab API, search, the deep link, keyboard and the phone layout; the before and after screenshots and measurements are in `docs/settings-tabs/`. |
| [docs/ux-review-2026-11-04.md](ux-review-2026-11-04.md) | The Nov 4, 2026 UX review: what was wrong on the board and the HUD, with screenshots. |
| [docs/ux-overnight-2026-11-04.md](ux-overnight-2026-11-04.md) | The morning summary of the Nov 4 overnight UX overhaul: what changed, before and after. |
| `docs/overnight/` | One evidence file per card of an overnight push (what changed, before/after, how to try it, risks), named after the card. |

Pictures and mockups, from throwaway boards: `docs/board-light.png`, `docs/board-dark.png`, `docs/hud.png` (the README's); `docs/agent-chat/`,
`docs/agent-configurations/` (role chips and the approval card), `docs/by-agent/`, `docs/copied-badge/`, `docs/copied-button/`, `docs/gorgeous-2026-11-04/`, `docs/hud-bughunt/`, `docs/load-strip/`, `docs/panel-header-action/`,
`docs/ux-five/`, `docs/ux-six/` (screenshots of the UX cards they are named after), `docs/status-slice-1/` (Watch's tiles with a state word, light, dark and narrow); `docs/card-colour-mockup.html`, `docs/subtasks-mockup.html`,
`docs/ux-mockups.html`, `docs/ux-mockups-2.html`, `docs/chat-words-design-mockup.html`, `docs/agent-configurations-mockup.html`, `docs/status-visibility-mockup.html`, `docs/night-queue-mockup.html` (clickable mockups,
with their `.png` captures beside them).
| [docs/security-signoff.md](security-signoff.md) | The two-page security sign-off: what was checked on the night of Nov 7-8, how, and what a reviewer can rerun. |

The folder `docs/by-agent-lane-cue/` holds further documents; see its own README.
| [docs/chat-qa.md](chat-qa.md) | Added on an overnight branch; see the first lines of the document. |
