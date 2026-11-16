# Agent configurations: design

Design only. Nothing here is built and nothing will be until the owner approves it (card `agent-configurations`). The mock-up is
[agent-configurations-mockup.html](agent-configurations-mockup.html) (captures: [light](agent-configurations-light.png), [dark](agent-configurations-dark.png),
[narrow](agent-configurations-narrow.png)); every name and number in it is made up.

## In one paragraph

A **configuration** is a small file that says which agent names and roles exist and how the board shows them. The owner picks one, the board
shows the roles beside the names, adds the role to each agent's card prompt, and prints the exact terminals to start. **The board starts nothing**:
the owner types the names into terminals as today, and the board reflects them. Renaming an agent is a separate, smaller piece and comes first,
because a configuration is only useful if a name can change without losing history.

## What the owner decided

1. The owner chooses the configuration. ORCH may *propose* one (a suggestion with an Accept and an Ignore button, from the insights counts); a proposal is never applied by itself.
2. The board reflects terminals the owner starts. Starting agents from a configuration is a possible later feature, not part of this.
3. The first jobs are day to day: booking appointments, paying bills, research, planning an evening. The safety rules are built for these first, and no real call, payment or form submission happens without the owner's explicit word each time.

## The file

JSON, because the board has no dependency that reads anything richer and a test can validate it. Shipped examples hold names, roles and rules, never a
person, a number or an address, and the build adds a test that scans them (`tests/publiccheck.py` guards the rest of the repo).

```json
{
  "configuration": 1,
  "name": "Day to day",
  "roles": [
    {"role": "caller", "names": ["Caller-1"], "purpose": "drafts what to say and the questions to ask; never dials",
     "model": "sonnet", "size": "M", "may": ["research", "draft", "write a plan"],
     "may_not": ["place a call", "send a message", "pay", "submit a form", "enter a password"],
     "tools": ["read-only web", "board"], "count": 1},
    {"role": "bills", "names": ["Bills-1"], "purpose": "reads a bill and prepares the payment for approval", "...": "..."}
  ]
}
```

Fields: role, default names (one per `count`), purpose, preferred model and size (advice only: the board cannot choose a model), may, may not,
tools allowed, how many. The applied configuration is a copy at `.agentboard/configuration.json`; `config.toml` stays hand-edited and is not rewritten.
`hud.roster` and `prompt._peer_roster` read the applied file and merge it with `[orch] agents`, so an agent outside the configuration still shows (dimmed).
Setting: `[agents] configurations = false` by default, the same switch pattern as `[insights]`.

## Rename

`agentboard rename OLD NEW [--dry-run]`, and a **Rename…** button on an agent's row and in the HUD (the mock-up's second frame). It keeps history, colour, claims and chat.

| Where the name lives | On rename |
|---|---|
| `tasks.json`: each card's `agent`, each log line's `by`, each chat line's `sender` and `to` | rewritten in one `Store.transaction()` |
| `chat-cursors.json`, `chat-delivered.json` (keyed by lowercase name), `chat-listeners.json`, `chat-autopilot.json`, `sessions.json` | key moved; the read position goes with it |
| `config.toml`: `[orch] agents`, `[agent_colors]` | the colour entry is carried over so the agent keeps its colour; the roster entry is renamed |
| Free text (a log line or chat line that says the old name) and the hourly `backups/` | **not** rewritten: history stays as written |

**The old name keeps working.** A terminal that was started as OLD still has `AGENTBOARD_NAME=OLD` until the owner retypes it. Without help its next
`update` would be refused as "not your card" and its listener would register as a new agent. So the board writes an alias (`.agentboard/aliases.json`,
`{"old": "new"}`) *first*, then rewrites; the alias is what makes a half-finished rename safe to re-run, and it is dropped when the owner presses
Undo or when the old name has not been used for a day (the board says so in the row). The name enters the CLI in about fifteen places in `cli.py`
(`AGENTBOARD_NAME`, `--name`, `by=`); the build routes them through one resolver, which is a refactor with its own tests.

Refused: a NEW that another agent holds or is listening under (case-insensitive), an empty or over-long name, and the reserved names (ORCH and the owner).
`--dry-run` prints the counts in the mock-up and changes nothing.

## Roles on the board and in prompts

- A role chip sits beside the name on **Load**, **Watch** and **Now**, and the configuration name sits in the header (mock-up, third frame).
- The card prompt ("Copy prompt") and the ORCH prompt get a block built from the role: "Your role: caller. You may: research, draft. You may not: place a call, pay…". An agent with no role gets today's prompt, unchanged.
- Switching a configuration changes the roster and the role labels only. Cards, claims and chat stay with the names.

## Safety for the day-to-day configuration

The honest limit first: **the board cannot stop an agent from doing something in its own terminal.** It can say the rule, make the approval visible and
recorded, and tell the owner which tools to leave out. The hard stop is that the agent has nothing to do the thing with.

1. **No credentials.** The configuration's `tools` list is the list the owner leaves enabled in that terminal; the apply screen prints it beside the start command. No payment method, no password, no phone or dialing access is in any shipped list.
2. **An action is a card, not a command.** Anything that reaches outside (a call, a message, a payment, a form submission) is written as a card in Needs you, built on `ask`: the action, the number or address, the exact words, the money and what is shared (mock-up, fourth frame). The owner's yes covers that one action, expires in 30 minutes, and is never reused for the next.
3. **The role prompt says it** in the "You may not" block, and a report that names an outside action with no approval on file is flagged on the card. That is a tripwire, not a lock: it relies on the agent naming the action.
4. **Personal data stays local.** A configuration file holds no personal data by construction; approval cards live in `tasks.json` on this machine like every card; export writes the file only, never cards or chat.

## The smallest build, after approval

1. **Rename (CLI + alias + dry-run + Undo)**, with tests and the one resolver. No configuration, no board button.
2. **One configuration (Day to day), the file, `agentboard configuration show|apply`**, role chips, the prompt block and the approval card, behind `[agents] configurations`. Render-check wide and narrow.
3. **The board's picker and Rename dialog, export and import, the other built-ins, ORCH's proposal from the insights counts.**

Each is its own card with its own tests; none installs or restarts the live board, and each is gated by the public-repo check.

## Decisions for the owner

1. **Alias on rename** (the old name keeps working for a day, with Undo) or a hard cut? *Recommended: alias.*
2. **History lines keep the old name** as written, while structured fields are rewritten? *Recommended: yes.*
3. **File format**: JSON? *Recommended: JSON.* (Markdown is nicer to read, but the board would have to parse prose.)
4. **Which configuration ships first**: Day to day (your first jobs, safety first) or Build (what the roster already is)? *Recommended: Day to day.*
5. **Approval card**: one action per yes, expires in 30 minutes. Right length? *Recommended: 30 minutes.*
6. **Start with rename alone** (slice 1, a card of its own), so it can be used before any configuration exists? *Recommended: yes.*

## As built (slice 2, Nov 14)

Built as designed, except: the approval card is the chat's existing proposal (`chat send --propose`, one decision, Approve and Decline) extended with `--outside --target --say --money --shares` and the 30-minute lapse, because it already had the one-decision record and the agent's `chat approvals` read; the card also `ask`s so it waits in Needs you (the role block tells the agent to). `count` in the file is optional and must equal the number of names. The compact Load strip carries the role in its tooltip, not as a chip. Pictures: `docs/agent-configurations/`.

## As built (Dev crew, Nov 15)

Retro rec 5: a fourth shipped configuration, `dev-crew` (builder, designer, gate, tester), matching the crew as it ran, and one new optional top-level field, `shared_rules`: up to 12 one-line rules (200 characters each) that every role's prompt carries once, after that role's own lines (`configurations.shared_block`, the same text for every role, so a rule is changed in one place). An agent with no role, and a configuration without the field, get today's prompt unchanged; ORCH's prompt lists them too. ORCH is not a role in the file: the board keeps that name, and ORCH already gets the roster and the rules in its own prompt. It is not on until the owner sets `[agents] configurations = true` and applies `dev-crew`; nothing in the build changed the live board.

## Not decided here

- Plugin files that hold agent names (the texts plugin keeps its own): rename would call a hook for them; the hook's shape is a build question.
- Spawning agents from a configuration. Not built, not designed; the file already holds enough to do it later.
