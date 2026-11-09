# config.toml: every key

Generated from `src/agentboard/configschema.py` by `agentboard config docs`; `tests/test_configschema.py` fails when this page and the schema differ, so edit the schema, not this file.

`agentboard init` writes the file with every option commented out. `agentboard config show` prints what applies to a board (and where each value came from),
`agentboard config check` lists unknown keys (with the closest valid name), wrong types and out-of-range values; `agentboard doctor` runs the same check.
An invalid value is never guessed at: the default applies and the check says so. An unknown key is kept (a plugin may read it) and reported.

## `[board]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `owner` | str | "you" | your name: what the board, the HUD and every prompt call the human. |
| `stale_minutes` | int 1..100000 | 120 | a Doing card silent this long is marked abandoned on the board and the HUD. |
| `profile` | str | unset | work: the work profile for this board (lock, no plugins, loopback only; `agentboard init` writes it on a machine with no home setup); any value but off, home, no, false, 0 or empty also means work (a mistyped word is a lock, not a hole), and a copied config can add it, never remove it. |

## `[ui]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `dispatch` | bool | true | show Copy prompt and the prompt preview. |

## `[hud]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `retired` | list[str] | none | agents hidden from the HUD; their cards and history stay. |

## `[voice]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `words` | list[str] | none | names the dictation should spell right (yours and the agents' are already included). |
| `model` | str | unset | a whisper ggml-*.bin file; else $AGENTBOARD_WHISPER_MODEL or a model another app installed. |

## `[notify]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | false | native macOS banner when a card needs input or is ready for review (osascript). |
| `sound` | str | unset | a macOS notification sound name; omit for silent. |

## `[prompt]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `template_file` | str | unset | a file (inside the board folder, or absolute) that replaces the built-in prompt template. |
| `template` | str | unset | the template itself, inline: {title}, {task_id}, {description} and the other fields. |

## `[providers]`

context providers for prompts, one table each: [providers.<name>].

| Key | Type | Default | Meaning |
|---|---|---|---|
| `type` | str (markdown | file-tail | http | command) | unset | what the provider does |
| `path` | str | unset | markdown, file-tail: the file, relative to the project root or absolute (inside the project under the lock) |
| `max_chars` | int 1..1000000 | unset | markdown: cut the block here |
| `entry_pattern` | str | unset | file-tail: a regex for the line that starts an entry (omit for the last N lines) |
| `entries` | int 1..10000 | 3 | file-tail: how many entries |
| `url` | str | unset | http: the address; {query} is the card's argument or title, URL-quoted |
| `json_path` | str | unset | http: dotted path to the list inside the JSON answer |
| `fields` | list[str] | unset | http: which fields of each result to show |
| `timeout` | int 1..600 | 10 | http, command: seconds before giving up |
| `run` | str | unset | command: the shell command; {arg} and {title} are substituted, already quoted (do not quote them again) |
| `label` | str | unset | the heading of this provider's block in the prompt (default: the provider's name) |
| `private` | bool | false | skipped by `agentboard prompt --public` |
| `redact` | list[str] | unset | regexes whose matches are masked in this provider's block before it is cut |

## `[chat]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `idle_model` | str | "haiku" | the cheaper model for `agentboard chat idle` and the autopilot. |
| `idle_budget_usd` | float 0.0..100.0 | 0.05 | spend cap per draft, passed to claude as --max-budget-usd. |
| `casual` | bool | false | the server gives agents' lines a spoken version (runs claude on a timer). **Unsafe:** starts a program. |
| `casual_per_hour` | int 1..10000 | 60 | lines rephrased an hour, at most. |
| `autopilot` | bool | false | the server drafts replies for idle [orch] agents with unread chat (runs claude on a timer). **Unsafe:** starts a program. |
| `autopilot_every` | int 30..86400 | 180 | seconds between autopilot rounds. |
| `autopilot_per_hour` | int 1..10000 | 12 | drafts an hour over every agent: the spend ceiling is this times idle_budget_usd. |
| `share_every_min` | int 0..100000 | 60 | an idle agent with nothing to answer offers one thing from its own work this often (0 = never). |
| `live_min` | int 1..100000 | 20 | an agent that spoke or touched a card this recently is awake: the board does not speak for it. |

## `[run]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `claude` | str | unset | the claude binary for one-shot runs (default: the one on PATH). **Unsafe:** starts a program. |
| `budget_usd` | float 0.0..1000.0 | 5.0 | hard spend cap per one-shot run. |
| `max_minutes` | int 1..1440 | 45 | hard wall-clock limit per one-shot run. |

## `[reports]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `keep_hours` | int 1..100000 | 24 | older card reports are deleted hourly; the newest per card always stays. |
| `repo` | str | unset | the git repo whose commits the reports list (default: the folder above .agentboard). |

## `[agent_colors]`

one CSS colour per agent name, on every card it holds: "AGENT-1" = "#2563eb".

| Key | Type | Default | Meaning |
|---|---|---|---|
| `<any name>` | str | unset | a CSS colour |

## `[backup]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `sync_dir` | str | unset | a folder (iCloud, Google Drive) that gets the newest snapshot nightly. **Unsafe:** sends data out. |

## `[redact]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | true | mask secrets on their way into the board. **Unsafe:** turns masking off. |
| `phones` | bool | false | also mask phone numbers. |
| `extra` | list[str] | none | your own regexes; each match becomes [redacted match]. |

## `[orch]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents` | list[table] | none | the roster the ORCH prompt and the autopilot use: [{name = "AGENT-1", color = "#2563eb"}]. |

## `[knowledge]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `files` | list[str] | none | notes files a plugin's lookup source may search (absolute paths; the core only lists them). |

## Environment

| Variable | Meaning |
|---|---|
| `AGENTBOARD_DIR` | the board folder to use from anywhere |
| `AGENTBOARD_BOARD` | a registered board name (what --board sets) |
| `AGENTBOARD_HOME` | where the boards registry lives (default ~/.agentboard) |
| `AGENTBOARD_NAME` | the default for --name |
| `AGENTBOARD_LOCKDOWN` | the master lock: refuses everything that starts a program or sends data out |
| `AGENTBOARD_NO_PLUGINS` | the narrow lock for plugins |
| `AGENTBOARD_PLUGINS` | exactly 1: plugins may load |
| `AGENTBOARD_UMASK` | an octal umask for the board's files (default 077: private) |
| `AGENTBOARD_CLAUDE` | the claude binary for one-shot runs and chat rounds |
| `AGENTBOARD_WHISPER_MODEL` | a whisper model file for dictation |

Plugins add their own sections to the schema while they are loaded (`api.add_config`); `agentboard config docs` from the board's shell lists them too.
