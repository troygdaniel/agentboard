# agentboard: security sign-off (for a reviewer on a managed machine)

**What it is.** A kanban board for the Claude Code sessions a developer runs in parallel: a command line (`agentboard …`) and a small web
server, one Python package, **no dependencies** (`pyproject.toml`: `dependencies = []`). The server listens on **127.0.0.1 only**, serves one
page, and keeps everything in `.agentboard/` inside your project. Each line below cites the file and the test that proves it; what could not
be proved is under **Known limits**. Written 2026-11-07, re-verified claim by claim (every file:line and test below opened and read) against `main` 9dbff54 (v0.3.1) on 2026-11-09.

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
| The server binds `127.0.0.1`; no flag binds anything else | `server.py:574` (`new_server`, `host="127.0.0.1"`; `serve` has no host option) | `agentboard doctor` "listeners … all loopback only"; `lsof -nP -i -a -p <pid>`: one LISTEN line |
| The suite (1,797 tests) makes **no connection off the machine**, and a change that adds one fails it | every module | `tests/netguard.py`, loaded by both runners, refuses any non-loopback `connect`/`connect_ex`/`getaddrinfo` naming the test; `tests/test_net_guard.py`; run of 2026-11-09 on Python 3.9.6 and 3.14: 0 refusals |
| Two core modules can open a socket from the board's own code: the opt-in `http` provider, the only one that can reach a URL you write in `config.toml` (`providers.py:11`), and `lifecycle.py:117`, which asks the board's own server for `/api/health` at a fixed `127.0.0.1` (the port is cast to an int, no proxy). `guards.py` and `selfcheck.py` import the same libraries only to refuse or audit non-loopback traffic | `grep -ln "urllib.request\|socket\|http.client" src/agentboard/*.py` lists exactly those four | `doctor` line "code: … outbound connection: lifecycle, providers; … listen: server" (`doctor.py:625`); `selfcheck` runtime audit (`tests/test_workprofile.py`) |
| Programs the board can start are opt-in: `claude` (chat rounds, `run`), the `command` provider, `osascript` banners, voice tools, read-only `git` | `agentchat.py:297`, `runs.py:268`, `providers.py:150`, `cli.py:873,921`, `voice.py:103`, `reports.py:134` | `tests/test_lockdown_wiring.py` |
| **`AGENTBOARD_LOCKDOWN=1` refuses all of those**, the `[backup] sync_dir` copy, `spawn` and every plugin, whatever a copied `config.toml` says; under it `config.toml` cannot read a file outside the project into a prompt | `lockdown.py:22-27` (any value but `""`, `0`, `false`, `no`; read on every call); `providers.py:51` `inside_project` (resolves symlinks; refuses absolute, `..`, `~`) | `tests/test_lockdown.py`, `test_lockdown_wiring.py`, `test_file_reads_lockdown.py`, `test_plugins.py::test_the_master_lock_beats_everything` |
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
| `.listeners.lock`, `.cursors.lock` | empty lock files (`listeners.py:48-61`) | 600 |
| `reports/<card>.html`, `runs/<card>/<id>/{run.json,prompt.md,stdout.json,stderr.log}` | a card's report; one-shot run records (opt-in) | 600 (folders 700) |
| `chat-casual.json`, `chat-autopilot.json` | only with the opt-in chat rounds on | 600 |
| `<project>/.gitignore` | `init` adds the line `.agentboard/` | your umask (a project file, `private.py:56`) |
| `<project>/.claude/{settings.json,settings.json.orig,settings.json.bak}` | `hooks install` adds two entries (below), through a temp file renamed over the target; the pristine file is kept once as `.orig` and the previous version as `.bak` | an existing file keeps its mode; a file agentboard creates is 0600 (`hooks.py:351-379`) |
| `~/.agentboard/boards.toml` | only if you register named boards (`boards.py:21`) | 600 |
| `~/.config/agentboard/profile` | only if you run `agentboard profile work`: the one word `work` (`profile.py:3,34`); a machine file, so every board and shell on this computer is under the work profile | 600 (folder 700) |
| Python's own bytecode cache | not the board's: the Mac's built-in Python 3.9 writes `~/Library/Caches/com.apple.python/…` for any program it runs | Python's |
| browser `localStorage` | 9 UI preferences: theme, sound, volume, ambient, mix, notifications, settings tab, panel tab, last conversation seen (`static/index.html`, `grep -o "localStorage[^;]*"`) | browser |

Nothing is synced unless you set `[backup] sync_dir`, and the lock refuses that too.

## Secrets, hooks, and what an agent can do

**Secrets.** Text agents write is masked where it enters the store (`redact.py`; `store.py` `_scrub` on every write path): key prefixes, tokens,
JWTs, private-key blocks, `Authorization:` values, URL passwords, `api_key = …`; invisible and look-alike characters are folded first.
`tests/test_redact*.py` (9 files). It is a shape filter: see Known limits.

**Hooks.** `agentboard hooks install` writes two entries into **this project's** `.claude/settings.json` (or `~/.claude/settings.json` only with `--user`), each the
absolute, shell-quoted path of the installed `agentboard` (`hooks.py:190-222,283-319`; `tests/test_hook_install.py`). No board text reaches a shell.
`hook send-message` (PostToolUse on SendMessage) reads Claude Code's JSON payload from stdin and, only while agent chat is on, posts it to the
board, masked (`hooks.py:99-132`). `hook stop` answers `{"decision":"block","reason":…}` once when the owner's unread line waits or no wait
runs (`hooks.py:139-185`); the quoted line is data (`untrusted.one_line`); it writes nothing. Both exit 0 always. `hooks uninstall`
(`hooks.py:320`) removes exactly those entries (`tests/test_hook_install.py:72-99`).

**An agent can** add, claim, update and review cards, read and post chat, read prompts, register its transcript path. **It cannot** run anything
(card text is never executed; a prompt is text the human copies), reach another machine, read a file outside the project into a prompt
under the lock, serve a transcript that is not a `.jsonl` under `~/.claude/projects` (`transcript.py:45-59`), or send over 1 MB
(`server.py:28,200`; `tests/test_http_limits.py`). POSTs need exactly `application/json`, a same-site `Sec-Fetch-Site`/`Origin` and a
`localhost`/`127.0.0.1` Host (`server.py:127,196,210-230`; `tests/test_post_guards.py`, `test_prompt_get_guard.py`, `test_plugin_get_csrf.py`).

## Checking it yourself, and removing it

```
export AGENTBOARD_LOCKDOWN=1            # in the shell profile that starts the board
agentboard doctor                       # PASS / WARN / FAIL lines; want 0 FAIL (read-only, opens no socket)
lsof -nP -a -p $(pgrep -f "agentboard serve" | head -1) -i        # one line: TCP 127.0.0.1:8765 (LISTEN)
python3 tests/publiccheck.py            # nothing key-shaped or private in the tracked files
```
`agentboard profile work` locks a whole machine to the above (master lock, no plugins, loopback only; `profile.py`), and `agentboard selfcheck` proves it: a static scan of the code
(`selfcheck.py`) plus a runtime audit of a throwaway server (`tests/test_workprofile.py`). On `main` 9dbff54 it prints 54 PASS, 0 WARN, 0 FAIL and `RESULT: PASS` (Python 3.9.6, fresh HOME):
1,182 loopback connections and lookups, none to an outside address, no program started. Send its output with this page.
Uninstall completely: `agentboard hooks uninstall` in each project, `pipx uninstall agentboard`,
`rm -rf <project>/.agentboard`, `rm -rf ~/.agentboard` (exists only for named boards), `rm -rf ~/.config/agentboard` (the profile file), and clear `localhost:8765` site data in the browser.

## Known limits (true today, not fixed by this document)

1. **No login.** Any program running as your user, or a browser extension, can read and change the board on the local port; websites cannot
   (Host, Origin and CSP checks). A key-cookie lock exists on a parked branch (`sec-web`), not merged (`SECURITY.md`, Known gaps).
2. **The masker is a shape filter.** A short password (`hunter2`) or a token with no recognisable shape is stored as written (the `Basic` and
   `redis://:password@host` gaps found on Nov 7 were fixed the same night, 88712d4). `[redact] enabled = false` in the board's `config.toml`,
   which any local process can edit, turns it off (`redact.py:111,267,334`); `agentboard doctor` prints `FAIL masking` then, and `WARN masking` when
   the default was changed (`doctor.py` `check_redact`, `tests/test_doctor.py`).
3. **A plugin is trusted code.** Install none on a managed machine; both locks refuse them.
4. **Hard links** out of the project are not detectable by the lockdown path check (symlinks are); making one needs write access to the project.
5. **Reliability, not security:** the listener and cursor files are written under a lock since Nov 7 (7381e9e, 16a273c); a receipt still says
   "answered" for any later agent line to the owner, not only a reply to that line (card `rev1107-answered-means-any-line`).
6. The hook entries in `.claude/settings.json` carry the install path (for example `~/.local/bin/agentboard`) and are often committed with a project.
7. **Not audited:** the `claude` program's own traffic, other apps, Linux and Windows (verification used macOS `lsof`, `ps`), and the voice tools.
