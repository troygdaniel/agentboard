# Overnight reliability: boring start, stop, restart and status

Branch `overnight/overnight-rel-server-lifecycle` (public repo, not merged; Troy reviews). AGENT-1, night of Nov 7 to 8.

## What changed

- **`agentboard status`**: running or not, with the pid, the port, since when, the uptime, the plugins loaded and whether the lockdown is on, one line per server; exit 1 when nothing runs. A server file left by a crash or a `kill -9` (its pid gone) is cleaned and said.
- **`agentboard stop`**: SIGTERM to every server of this board, then a wait (10 s by default) until each has finished what it was doing and is gone; the result in one line. A server that will not end is named with the `kill -9` to run.
- **`agentboard restart`**: stop, then start again on the same port with this shell's environment, detached; one line with the old and new pid and the URL.
- **`agentboard serve --background`**: start detached (its own session, output appended to `.agentboard/server.log`, mode 0600) and print the pid once `/api/health` answers from it; a server that exits at once is reported with the log's last line.
- **Graceful SIGTERM** (`server.serve`): the signal leaves the serve loop; `server_close` then waits for the request threads, so a save under way is written whole; the state file is removed; "agentboard: stopped" is printed. No orphan threads: the backup, autopilot and plugin threads are daemon threads and the request threads are joined.
- **A taken port says who holds it**: this board's own server (pid and since when, with `status`, `restart` and `stop` as the next step), another board's agentboard (pid, with `--port N+1`), or something else (the errno and `--port N+1`).
- **`/api/health`** (loopback, the same Host guard as every route, no board data): `{ok, agentboard: version, pid, port, started, uptime_s, plugins, lockdown}`.
- **`agentboard doctor`** gains a server-files line: a stale file is a WARN with the command that cleans it; nothing running is INFO with the command that starts it. Doctor still opens no socket.
- `lifecycle.py` (new) holds all of it; `serverstate.py` (the per-pid state file) is unchanged.

## Before and after

| | before | after |
|---|---|---|
| is the board running? | look for a terminal, or `lsof` | `agentboard status` |
| stop it | Ctrl+C in its terminal, or `kill` by hand | `agentboard stop` (waits for in-flight saves) |
| restart after an install | find the terminal, Ctrl+C, run serve again | `agentboard restart` |
| port taken | "cannot listen on port 8765 (Address already in use); is another board running?" | "this board is already served on port 8765 by pid 4242 (since 09:30). `agentboard status` shows it; `agentboard restart` replaces it" |
| server killed with -9 | a `server-<pid>.json` stays until the next start | `status` and `doctor` name it; `status` cleans it |
| SIGTERM | the process died mid-request | the request finishes, the file is removed, "agentboard: stopped" |

## How to try it

```
agentboard serve --background        # starts detached, prints the pid and the URL
agentboard status                    # running: pid N on port 8765 since ... (up 12s; plugins: none; lockdown off)
agentboard serve                     # a second start: the message names the first and what to do
agentboard restart                   # restarted on port 8765: pid M (was N)
agentboard stop                      # stopped pid M (port 8765) in 0.3 s
curl -s -H 'Host: localhost:8765' http://127.0.0.1:8765/api/health
PYTHONPATH=src:tests python3 -m unittest tests.test_lifecycle      # the subprocess tests (about 15 s)
```

## Risks

- `restart` starts the new server from the shell that runs `restart`, with that shell's environment; started from a different shell than the original (one without the keys or the lock), the new server differs. `status` shows the lockdown flag and the plugins loaded, so the difference is visible.
- `stop` waits up to 10 s and then names the pid for a `kill -9`; it never kills by itself.
- `server_close` now joins request threads: a client that holds a request open for a long time delays the stop by at most the handler's 15 s timeout.
- The health route reveals the version, the pid, the port, the start time and the plugin names to any process on the machine that can reach the loopback and passes the Host guard; no board data.

## Test runs

- `tests/test_lifecycle.py`: 6 tests with a real `agentboard serve` subprocess (health, status and stop, double start on the same port and from another board, kill -9 and the stale file, restart and `--background`, a request in flight across SIGTERM).
- Full public suite on this branch (main 33ecb3e): **1291 tests OK**; `python3 tests/publiccheck.py`: 0 findings.

## Not done (candidates for a next card)

- A LaunchAgent template (`agentboard serve --background` at login) with `status` as its health check.
- `restart` could record the original start command's port and flags in the state file and reuse them without the shell's say.
