# Documents

One line each. The first three are the ones most people need.

| Document | What it is for |
|---|---|
| [README.md](../README.md) | Using the board: install, quick start, the agent lifecycle, chat, boards, backups, safety, configuration, commands, the work-laptop checklist, troubleshooting. |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | Changing the board: module map, data files and who writes them, a request's path through the server, the agent protocol in code, the plugin hook, the security model on one page, running the tests. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Working on it: cards and worktrees, the gates before "ready", the changelog rule, commits, where things belong. |
| [SECURITY.md](../SECURITY.md) | What the board does and does not do with your data and your network, what was audited, the known gaps, how to check a machine. |
| [CHANGELOG.md](../CHANGELOG.md) | Every change a user could notice, newest first, with the cards it closes. |
| [CLAUDE.md](../CLAUDE.md) | The prompt an AI agent working in this repository reads: the card protocol, subtasks, chat, the public-repo rules, how to verify UI changes. |
| [docs/security-audit-2026-11-07.md](security-audit-2026-11-07.md) | The Nov 7, 2026 security audit for a managed work laptop: verdict, findings ranked, what was decided, the install and lock checklist. |
| [docs/conversation-reliability-analysis.md](conversation-reliability-analysis.md) | Why a line typed to an agent on the board used to go unanswered: the loss paths, ranked, and the fixes in order (listeners, receipts, the Stop hook, the nudge). |
| [docs/chat-words-design.md](chat-words-design.md) | The words and layout of the chat: who reads a line, receipts, refusals, two sessions under one name. |
| [docs/texts-reply-plan.md](texts-reply-plan.md) | The plan for texting the owner back (built in the home plugin, outside this repo): the rules, keys, spend and loop guards. |
| [docs/texts-reply-design.md](texts-reply-design.md) | The wording and the Settings control for texting back, with mockups. |
| [docs/ux-review-2026-11-04.md](ux-review-2026-11-04.md) | The Nov 4, 2026 UX review: what was wrong on the board and the HUD, with screenshots. |
| [docs/ux-overnight-2026-11-04.md](ux-overnight-2026-11-04.md) | The morning summary of the Nov 4 overnight UX overhaul: what changed, before and after. |
| `docs/overnight/` | One evidence file per card of an overnight push (what changed, before/after, how to try it, risks), named after the card. |

Pictures and mockups, from throwaway boards: `docs/board-light.png`, `docs/board-dark.png`, `docs/hud.png` (the README's); `docs/agent-chat/`,
`docs/by-agent/`, `docs/copied-badge/`, `docs/copied-button/`, `docs/gorgeous-2026-11-04/`, `docs/hud-bughunt/`, `docs/panel-header-action/`,
`docs/ux-five/`, `docs/ux-six/` (screenshots of the UX cards they are named after); `docs/card-colour-mockup.html`, `docs/subtasks-mockup.html`,
`docs/ux-mockups.html`, `docs/ux-mockups-2.html`, `docs/chat-words-design-mockup.html`, `docs/texts-reply-design-mockup.html` (clickable mockups,
with their `.png` captures beside them).
| [docs/security-signoff.md](security-signoff.md) | The two-page security sign-off: what was checked on the night of Nov 7-8, how, and what a reviewer can rerun. |

The folder `docs/by-agent-lane-cue/` holds further documents; see its own README.
