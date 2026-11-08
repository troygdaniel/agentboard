# agentboard: security sign-off (for a reviewer on a managed machine)

**What it is.** A kanban board for the Claude Code sessions a developer runs in parallel: a command line (`agentboard …`) and a small web
server, one Python package, **no dependencies** (`pyproject.toml`: `dependencies = []`). The server listens on **127.0.0.1 only**, serves one
page, and keeps everything in `.agentboard/` inside your project. Each line below cites the file and the test that proves it; what could not
be proved is under **Known limits**. Written 2026-11-07, re-verified line by line against `main` 2b1adae (v0.3.1) on 2026-11-08.

## Data flow

```
 Claude Code session ──(agentboard CLI: add / start / update / chat …)──▶  <project>/.agentboard/tasks.json  ◀──(reads, writes)── agentboard serve
        │                                                                          ▲                                               127.0.0.1:8765
        └─ two Claude Code hooks (PostToolUse SendMessage, Stop) ──▶ agentboard hook … ─┘                                               ▲
                                                                                                                                       │ same-origin fetch only
                                                                                                                              your browser: http://localhost:8765
```

## Network: what can connect, and what does

| Claim | Code | Proof |
|---|---|---|
| The server binds `127.0.0.1`; no flag binds anything else | `server.py:435` | `agentboard doctor` "listeners … all loopback only"; `lsof -nP -i -a -p <pid>`: one LISTEN line |
| The suite (1,200+ tests) makes **no connection off the machine**, and a change that adds one fails it | every module | `tests/netguard.py`, loaded by both runners, refuses any non-loopback `connect`/`connect_ex`/`getaddrinfo` naming the test; `tests/test_net_guard.py`; run of 2026-11-07: 0 refusals |
| One module can open an outbound socket: the opt-in `http` provider | `providers.py:11`; `grep -n "urllib.request\|socket\|http.client" src/agentboard/*.py` | `doctor` line "code: … outbound connection: providers; … listen: server" (`doctor.py:570`) |
| Programs the board can start are opt-in: `claude` (chat rounds, `run`), the `command` provider, `osascript` banners, voice tools, read-only `git` | `agentchat.py:296`, `runs.py:274`, `providers.py:150`, `cli.py:723`, `voice.py:103`, `reports.py:131` | `tests/test_lockdown_wiring.py` |
| **`AGENTBOARD_LOCKDOWN=1` refuses all of those**, the `[backup] sync_dir` copy, `spawn` and every plugin, whatever a copied `config.toml` says; under it `config.toml` cannot read a file outside the project into a prompt | `lockdown.py:26` (any value but `""`, `0`, `false`, `no`; read on every call); `providers.py:51` `inside_project` (resolves symlinks; refuses absolute, `..`, `~`) | `tests/test_lockdown.py`, `test_lockdown_wiring.py`, `test_file_reads_lockdown.py`, `test_plugins.py::test_the_master_lock_beats_everything` |
| Plugins are off unless `AGENTBOARD_PLUGINS` is exactly `1`; `AGENTBOARD_NO_PLUGINS` is a second lock; none ship | `plugins.py:64` | `tests/test_plugins.py` |
| The page loads nothing from the internet; install fetches once (`pipx`, `setuptools>=68`); no update check, no telemetry | `static/index.html` (only `http` string: the SVG namespace); no such code exists | `tests/test_page_csp.py`: `default-src 'none'; connect-src 'self'`, no framing, nosniff |

## Every file the board writes, and its mode

Made under `umask 077` in the CLI and the server (`private.py:21,34`), so each is yours alone whatever your shell's umask; `serve` tightens
an older folder. Proof: `tests/test_file_modes.py` (14 tests under umask 022) and `tests/test_signoff_files.py`, which fails if a day's work
writes a file this table does not name, or with another mode.

| File | Holds | Mode |
|---|---|---|
| `<project>/.agentboard/` | the board folder | 700 |
| `tasks.json`, `tasks.json.bak` | cards, chat, the agent-chat switch; the previous version | 600 |
| `backups/tasks-<stamp>.json.gz` | hourly snapshots (`backup.py:97`) | 600 (folder 700) |
| `config.toml`, `.lock` | providers and switches; the write lock | 600 |
| `sessions.json`, `chat-cursors.json`, `chat-delivered.json`, `chat-listeners.json`, `chat-wake.json`, `server-<pid>.json` | session name per Claude Code id and transcript path; where each agent read to; which wait runs (pid); how the server was started (flags) | 600 (`serverstate.py:72`: `O_EXCL\|O_NOFOLLOW`) |
| `.listeners.lock`, `.cursors.lock` | empty lock files (`listeners.py:48-56`) | 600 |
| `reports/<card>.html`, `runs/<card>/<id>/{run.json,prompt.md,stdout.json,stderr.log}` | a card's report; one-shot run records (opt-in) | 600 (folders 700) |
| `chat-casual.json`, `chat-autopilot.json` | only with the opt-in chat rounds on | 600 |
| `<project>/.gitignore`, `<project>/.claude/settings.json` | `init` adds `.agentboard/`; `hooks install` adds two entries (below) | your umask (project files, `private.py:56`) |
| `~/.agentboard/boards.toml` | only if you register named boards (`boards.py:21`); nothing else under HOME | 600 |
| browser `localStorage` | 7 UI preferences | browser |

Nothing is synced unless you set `[backup] sync_dir`, and the lock refuses that too.

## Secrets, hooks, and what an agent can do

**Secrets.** Text agents write is masked where it enters the store (`redact.py`; `store.py` `_scrub` on every write path): key prefixes, tokens,
JWTs, private-key blocks, `Authorization:` values, URL passwords, `api_key = …`; invisible and look-alike characters are folded first.
`tests/test_redact*.py` (9 files). It is a shape filter: see Known limits.

**Hooks.** `agentboard hooks install` writes two entries into **this project's** `.claude/settings.json` only, never `~/.claude`, each the
absolute, shell-quoted path of the installed `agentboard` (`hooks.py:179-236`; `tests/test_hook_install.py`). No board text reaches a shell.
`hook send-message` (PostToolUse on SendMessage) reads Claude Code's JSON payload from stdin and, only while agent chat is on, posts it to the
board, masked (`hooks.py:99-125`). `hook stop` answers `{"decision":"block","reason":…}` once when the owner's unread line waits or no wait
runs (`hooks.py:128-158`); the quoted line is data (`untrusted.one_line`); it writes nothing. Both exit 0 always. `hooks uninstall`
(`hooks.py:267`) removes exactly those entries (`tests/test_hook_install.py:72-99`).

**An agent can** add, claim, update and review cards, read and post chat, read prompts, register its transcript path. **It cannot** run anything
(card text is never executed; a prompt is text the human copies), reach another machine, read a file outside the project into a prompt
under the lock, serve a transcript that is not a `.jsonl` under `~/.claude/projects` (`transcript.py:45-59`), or send over 1 MB
(`server.py:25,133`; `tests/test_http_limits.py`). POSTs need exactly `application/json`, a same-site `Sec-Fetch-Site`/`Origin` and a
`localhost`/`127.0.0.1` Host (`server.py:106,127,156,161`; `tests/test_post_guards.py`, `test_prompt_get_guard.py`, `test_plugin_get_csrf.py`).

## Checking it yourself, and removing it

```
export AGENTBOARD_LOCKDOWN=1            # in the shell profile that starts the board
agentboard doctor                       # PASS / WARN / FAIL lines; want 0 FAIL (read-only, opens no socket)
lsof -nP -a -p $(pgrep -f "agentboard serve" | head -1) -i        # one line: TCP 127.0.0.1:8765 (LISTEN)
python3 tests/publiccheck.py            # nothing key-shaped or private in the tracked files
```
`agentboard selfcheck` (a static scan plus a runtime socket audit) is being built on branch `overnight/overnight-sec-workpc-profile` and is not
part of this sign-off. Uninstall completely: `agentboard hooks uninstall` in each project, `pipx uninstall agentboard`,
`rm -rf <project>/.agentboard`, `rm -rf ~/.agentboard` (exists only for named boards), and clear `localhost:8765` site data in the browser.

## Known limits (true today, not fixed by this document)

1. **No login.** Any program running as your user, or a browser extension, can read and change the board on the local port; websites cannot
   (Host, Origin and CSP checks). A key-cookie lock exists on a parked branch (`sec-web`), not merged (`SECURITY.md`, Known gaps).
2. **The masker is a shape filter.** A short password (`hunter2`) or a token with no recognisable shape is stored as written (the `Basic` and
   `redis://:password@host` gaps found on Nov 7 were fixed the same night, 88712d4). `[redact] enabled = false` in the board's `config.toml`,
   which any local process can edit, turns it off (`redact.py:181-195`); `agentboard doctor` prints `FAIL masking` then, and `WARN masking` when
   the default was changed (`doctor.py` `check_redact`, `tests/test_doctor.py`).
3. **A plugin is trusted code.** Install none on a managed machine; both locks refuse them.
4. **Hard links** out of the project are not detectable by the lockdown path check (symlinks are); making one needs write access to the project.
5. **Reliability, not security:** the listener and cursor files are written under a lock since Nov 7 (7381e9e, 16a273c); a receipt still says
   "answered" for any later agent line to the owner, not only a reply to that line (card `rev1107-answered-means-any-line`).
6. The hook entries in `.claude/settings.json` carry the install path (for example `~/.local/bin/agentboard`) and are often committed with a project.
7. **Not audited:** the `claude` program's own traffic, other apps, Linux and Windows (verification used macOS `lsof`, `ps`), and the voice tools.
