# agentboard: security sign-off (for a reviewer on a managed machine)

**What it is.** A kanban board for the Claude Code sessions a developer runs in parallel. A command line (`agentboard …`) and a
small web server, both from one Python package with **no dependencies** (`pyproject.toml`: `dependencies = []`, stdlib only). The
server listens on **127.0.0.1 only**, serves one HTML page, and stores everything in one folder, `.agentboard/`, inside your project.
This page states what the code does and cites the file and the test that proves each line. It was written on 2026-11-07 against
`main` 3cec02a (v0.3.1). Where a claim could not be proved by a test or a grep it is listed under **Known limits**, not asserted.

## Data flow

```
 Claude Code session ──(agentboard CLI: add / start / update / chat …)──▶  <project>/.agentboard/tasks.json  ◀──(reads, writes)── agentboard serve
        │                                                                          ▲                                               127.0.0.1:8765
        └─ two Claude Code hooks (PostToolUse SendMessage, Stop) ──▶ agentboard hook … ─┘                                               ▲
                                                                                                                                       │ same-origin fetch only
                                                                                                                              your browser: http://localhost:8765
```

Text moves one way into the board file and out to the page. Nothing in the picture crosses the machine boundary.

## Network: what can connect, and what does

| Claim | Where in the code | Proof |
|---|---|---|
| The server binds `127.0.0.1`; there is no flag for another interface | `server.py:435` `ThreadingHTTPServer(("127.0.0.1", port), …)` | `agentboard doctor` "listeners … all loopback only"; `lsof -nP -i -a -p <pid>` shows one LISTEN line |
| The whole test suite (1,200+ tests) makes **no connection off the machine** | every module | run of 2026-11-07 under a socket guard that refuses any non-loopback `connect`/`getaddrinfo` (see `docs/overnight/overnight-sec-signoff-pack.md`): 0 refusals |
| Only one module can open an outbound socket: the opt-in `http` provider | `providers.py:11` (`urllib.request`), nowhere else: `grep -n "urllib.request\|socket\|http.client" src/agentboard/*.py` | `agentboard doctor` line "code: modules that can make an outbound connection: providers; modules that can listen: server" (`doctor.py:497`) |
| Programs the board can start are all opt-in: `claude` (chat rounds, `agentboard run`), the `command` provider, `osascript` banners, voice tools, `git` for read-only log/status | `agentchat.py:296`, `runs.py:274`, `providers.py:150`, `cli.py:736`, `voice.py:103`, `reports.py:131` | `tests/test_lockdown_wiring.py` |
| **The master lock `AGENTBOARD_LOCKDOWN=1` refuses every one of those at once**, plus the `[backup] sync_dir` copy, `spawn`, and all plugins, even when a copied `config.toml` asks for them | `lockdown.py:26` (any value but `""`, `0`, `false`, `no` locks; read on every call, never cached) | `tests/test_lockdown.py`, `tests/test_lockdown_wiring.py` (9 tests), `tests/test_plugins.py::test_the_master_lock_beats_everything` |
| Under the lock, `config.toml` cannot pull a file from outside the project into a prompt (markdown, file-tail, template) | `providers.py:51` `inside_project` (resolves symlinks; refuses absolute, `..`, `~`) | `tests/test_file_reads_lockdown.py` |
| Plugins are off unless `AGENTBOARD_PLUGINS` is exactly `1`; `AGENTBOARD_NO_PLUGINS` is a second lock; agentboard ships none | `plugins.py:62` | `tests/test_plugins.py` (off by default, key exactly 1, either lock closes every door while running) |
| The page loads nothing from the internet: no CDN, font, script or image | `static/index.html`: the only `http` string is the SVG namespace | `tests/test_page_csp.py`: CSP `default-src 'none'; connect-src 'self'; script-src 'nonce-…' 'self'`, no framing, nosniff |
| Install fetches once (`pipx install git+…` and `setuptools>=68`); nothing runs at install, no update check, no telemetry | `pyproject.toml`; no such code exists | `grep -rn "telemetry\|analytics\|update" src/agentboard/*.py` finds no network call |

## Every file the board writes, and its mode

Made with `umask 077` in the CLI and the server (`private.py:21,34`), so each is yours alone whatever your shell's umask; `serve`
tightens an older folder at start. Proof: `tests/test_file_modes.py` (14 tests, run under umask 022 in a subprocess), and the
listing below taken from a throwaway project on 2026-11-07.

| File | Holds | Mode |
|---|---|---|
| `<project>/.agentboard/` | the board folder | 700 |
| `tasks.json`, `tasks.json.bak` | cards, chat, the agent-chat switch; the previous version | 600 |
| `backups/tasks-<stamp>.json.gz` | hourly snapshots (`backup.py:97`) | 600 (folder 700) |
| `config.toml` | providers, switches, phone numbers if you add them | 600 |
| `.lock` | the write lock | 600 |
| `sessions.json`, `chat-cursors.json`, `chat-listeners.json`, `server-<pid>.json` | session name per Claude Code id and transcript path; where each agent read to; which wait is running (pid); how the server was started (yes/no flags) | 600 (`serverstate.py:72` uses `O_EXCL\|O_NOFOLLOW`) |
| `reports/<card>.html`, `runs/<card>/<id>/{run.json,prompt.md,stdout.json,stderr.log}` | a card's finished report; one-shot run records (runs are opt-in) | 600 |
| `chat-casual.json`, `chat-autopilot.json` | only when the opt-in chat rounds are on | 600 |
| `<project>/.gitignore` | `init` adds the line `.agentboard/` | your umask (a project file, `private.py:56`) |
| `<project>/.claude/settings.json` | `hooks install` adds two hook entries (below) | your umask |
| `~/.agentboard/boards.toml` | only if you register named boards (`boards.py:21`); nothing else is written under HOME | 600 |
| browser `localStorage` | 7 UI preferences (theme, sounds, bell, volume, open tab) | browser |

Nothing is written anywhere else; nothing is synced unless you set `[backup] sync_dir`, and the lock refuses that too.

## Secrets in card text

Text that agents write is masked where it enters the store (`redact.py`; `store.py` `_scrub` on add/start/claim/edit/ask/review/update/chat):
cloud and API key prefixes, tokens, JWTs, private-key blocks, `Authorization:` values, URL passwords, `api_key = …`; invisible and
look-alike characters are folded first. Proof: `tests/test_redact*.py` (8 files). It is a shape filter, not a classifier: see Known limits.

## What the two hooks do

`agentboard hooks install` writes, into **this project's** `.claude/settings.json` only (never `~/.claude`), two entries whose command is the
absolute path of the installed `agentboard`, shell-quoted (`hooks.py:173-230`; `tests/test_hook_install.py`). No board text ever reaches a shell.

- `PostToolUse` on `SendMessage`: `agentboard hook send-message` reads Claude Code's JSON payload from stdin and, only while agent chat is on,
  posts the message to the board file, masked (`hooks.py:99-125`). Exit 0 always; prints nothing.
- `Stop`: `agentboard hook stop` reads the payload and answers `{"decision":"block","reason":…}` once when the owner's unread line is waiting
  or no wait is running (`hooks.py:128-158`); the quoted line is passed as data (`untrusted.one_line`). It reads the board, writes nothing.

`agentboard hooks uninstall` (`hooks.py:261`) removes exactly those entries and deletes the file only if it held nothing else (`tests/test_hook_install.py:72-99`).

## What an agent can and cannot do through the board

Can: add, claim, update, review cards; read and post chat; read prompts; register its transcript path. Cannot: run anything (the board never
executes card text; a prompt is text the human copies), reach another machine, read a file outside the project into a prompt under the lock,
serve a transcript that is not a `.jsonl` under `~/.claude/projects` (`transcript.py:45-59`), or send more than 1 MB in a request
(`server.py:25,133`; `tests/test_http_limits.py`). POSTs need exactly `application/json`, a same-site `Sec-Fetch-Site`/`Origin` and a
`localhost`/`127.0.0.1` Host (`server.py:106,127,156,161`; `tests/test_post_guards.py`, `test_prompt_get_guard.py`, `test_plugin_get_csrf.py`).

## Checking it yourself, and removing it

```
export AGENTBOARD_LOCKDOWN=1            # in the shell profile that starts the board
agentboard doctor                       # PASS / WARN / FAIL lines; want 0 FAIL (doctor.py: 12 checks, read-only, no socket opened)
lsof -nP -a -p $(pgrep -f "agentboard serve" | head -1) -i        # one line: TCP 127.0.0.1:8765 (LISTEN)
python3 tests/publiccheck.py            # nothing key-shaped or private in the tracked files
```
A separate `agentboard selfcheck` (static scan plus a runtime socket audit) is being built on branch `overnight/overnight-sec-workpc-profile`
and is not part of this sign-off.

Uninstall completely: `agentboard hooks uninstall` in each project, `pipx uninstall agentboard`, `rm -rf <project>/.agentboard`,
`rm -rf ~/.agentboard` (only exists for named boards), and clear `localhost:8765` site data in the browser. Nothing else was written.

## Known limits (true today, not fixed by this document)

1. **No login.** Any program running as your user, or a browser extension, can read and change the board on the local port. Websites cannot
   (Host, Origin and CSP checks). A key-cookie lock exists on a parked branch (`sec-web`) and is not merged (`SECURITY.md`, Known gaps).
2. **The masker is a shape filter.** A short password (`hunter2`), a `Basic` header with a short value, or `redis://:password@host` (empty user) are
   stored as written; `[redact] enabled = false` in the board's `config.toml`, which any local process can edit, turns it off (`redact.py:156-170`).
   Cards `rev1107-redact-url-empty-user` and `rev1107-redact-short-basic` are filed.
3. **A plugin is trusted code.** Install none on a managed machine; both locks refuse them.
4. **Hard links** out of the project are not detectable by the lockdown path check (symlinks are); writing one needs write access to the project.
5. **Reliability, not security:** `chat-listeners.json` is written without a lock and loses entries under concurrent waits (card `rev1107-listeners-race`).
6. The Stop hook's `.claude/settings.json` entry carries the install path (for example `~/.local/bin/agentboard`) and is often committed with a project.
7. **Not audited:** the `claude` program's own traffic, other apps, Linux and Windows (verification used macOS `lsof`, `ps`), and the voice tools.
