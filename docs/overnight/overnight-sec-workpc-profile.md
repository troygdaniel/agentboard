# overnight-sec-workpc-profile: the work-PC profile and `agentboard selfcheck`

Branch `overnight/overnight-sec-workpc-profile` (public repo, nothing pushed), rebased onto public main 5e7a929 (Merge chat-f7) on Nov 8. The three server bug fixes it found were split out at ORCH's request as branch `security-server-hardening` (d02208c, off main 8b07a0d) and are **already merged to main**; after the rebase this branch no longer carries them (its `server.py` differs from main only by the profile: no browser, no chat rounds, no git line, `nosniff` on every response). Card `overnight-sec-workpc-profile`, AGENT-3.

## What changed

| File | What |
|---|---|
| `src/agentboard/guards.py` (new) | The two run-time guards. **Network:** `connect`, `connect_ex`, `sendto`, `bind`, `create_connection`, `getaddrinfo`, `gethostbyname*`, `gethostbyaddr`, `getnameinfo` refuse anything that is not this machine (127.0.0.0/8, `::1`, a Unix socket, `localhost`), before anything is sent. **Process:** `subprocess.Popen`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `os.posix_spawn`, `os.fork` refuse. Both record every attempt. |
| `src/agentboard/profile.py` (new) | The one switch. Three sources, any one turns it on, none turns another off: `AGENTBOARD_PROFILE=work`, the machine file `~/.config/agentboard/profile` (mode 600), `[board] profile = "work"`. Anything but a plain off word means work (a typo is a lock). `apply()` sets the master lock and the plugin lock for the process and what it starts and installs the network guard; `apply_server()` adds the process guard. |
| `src/agentboard/selfcheck.py` (new) | `agentboard selfcheck [--json]`: static scan + live audit + red-team, a PASS/FAIL/WARN list, exit 1 on a FAIL (54 checks). |
| `src/agentboard/cli.py` | `agentboard profile [status\|work\|off]`, `agentboard selfcheck`, `agentboard init --profile work`; `main()` applies the profile before plugins can load. |
| `src/agentboard/server.py` | **Three fixes the red-team found** (below), the profile in `serve` (no browser, no chat rounds, no git line), `BoundedHTTPServer`/`new_server`. |
| `src/agentboard/reports.py` | `_git` starts nothing in the work profile (the report just has no "commits made" line). |
| `src/agentboard/doctor.py` | The code scan names the two audit modules instead of warning about them. |
| `tests/test_workprofile.py` (new) | 33 tests: the guards, the switch, the bugs, the selfcheck passing on this tree, **and the selfcheck failing for each planted violation** (network import, program start, `shell=True`, `eval`, `pickle`, third-party package, an address, a page loading from outside, a dropped CSP, a server that stops checking Host/Origin/content type, a route that reaches out or starts a program, a listener on all interfaces, a lock that does not lock). |
| `README.md`, `SECURITY.md` | "On a work laptop" opens with the switch and the proof; SECURITY.md has a section on both. |

## The bugs the red-team found, before and after

Same probes against unmodified `main` and this branch (a throwaway board; `scratchpad/workpc_before.py` style script, reproduced by `agentboard selfcheck`):

| Probe | Before (main) | After |
|---|---|---|
| A 800 KB JSON body of nested `[` (the body limit is 1 MB) | `RecursionError` in the handler thread: **no response, connection dropped**, traceback in the log | `400 {"error": "the JSON is nested too deeply"}`, server keeps serving |
| `GET /reports/<name>` where `<name>` is a symlink inside the reports folder to a file outside it | **`200` with the file's content** | `404` (the report must be a file in the folder itself, not a link, resolving into it) |
| 300 idle connections | **302 threads** (one per connection, held up to 15 s each) | **130 threads**; the 129th and later get `503` at once (`BoundedHTTPServer`, 128 at a time) |
| Response headers | `X-Content-Type-Options` only on pages | `nosniff` on every response |
| Any other surprise in a `POST` handler | connection dropped | `500 {"error": "server error (ClassName)"}` (class name only), as a `GET` already did |
| Work profile: finishing a card | server ran `git rev-parse` (a program start) | nothing started; the report has no commits line |

Everything else the red-team tried was already right on `main` and is now a permanent check: 8 wrong `Host` forms (DNS rebinding), 5 cross-site `POST` forms and cross-site `GET`s with side effects, exact `application/json` only (6 look-alike types), oversized/negative/non-numeric lengths, two requests in one connection, `Content-Length` with `Transfer-Encoding`, duplicate lengths, CR/LF injection, over-long lines (414) and headers (431), a stalled client (cut at the handler timeout), every other verb (501), no CORS header, frame/CSP headers, 88 path-traversal URLs across every route that takes a name, a transcript path that is any file, unknown board names, and providers aimed at a metadata address (no connection is even attempted), a shell command (not run) and a file outside the project (not read).

## How to try it

    agentboard profile work                 # this machine, every board (or: export AGENTBOARD_PROFILE=work, or agentboard init --profile work)
    agentboard profile                      # what is on and why
    agentboard selfcheck                    # the proof (about 8 s); agentboard selfcheck --json for a machine-readable list
    PYTHONPATH=src python3 -m unittest tests.test_workprofile      # the tests, 35 s

Real output with the profile on (this branch, `AGENTBOARD_PROFILE=work`):

```
agentboard selfcheck   (the work profile, proved: static scan of the code, then a live audit of a throwaway server)
PASS  static: network-capable imports                                     only where the table allows (4 files): guards.py: socket, providers.py: urllib.request, selfcheck.py: http.client, selfcheck.py: socket,
PASS  static: program-starting code                                       only in 9 files, each locked or a command: agentchat.py, cli.py, doctor.py, guards.py, providers.py, reports.py, runs.py, selfcheck.py, 
PASS  static: shell=True                                                  only in providers.py (the command provider, locked)
PASS  static: eval, exec, pickle                                          none
PASS  static: computed imports                                            none (every import is written out)
PASS  static: third-party packages                                        none: standard library only
PASS  static: declared dependencies                                       an empty list
PASS  static: addresses in the code                                       no URL, IPv4 address or host name with a common suffix (.com .net .org .io .dev ...) in any code string except this machine, the documen
PASS  static: the page loads nothing from outside                         2 page files scanned, no script, style, image, font, frame or request to another host; Content-Security-Policy default-src 'none', conne
PASS  profile: on in this shell                                           environment: $AGENTBOARD_PROFILE=work
PASS  profile: master lock                                                AGENTBOARD_LOCKDOWN is on while the audit runs
PASS  profile: plugins refused                                            plugins: locked: $AGENTBOARD_LOCKDOWN is set
PASS  profile: claude rounds refused                                      the lock raises 'locked off' for it (each feature's own code calls the lock first: that call is covered by the lock's tests, not exercis
PASS  profile: agentboard run refused                                     the lock raises 'locked off' for it (each feature's own code calls the lock first: that call is covered by the lock's tests, not exercis
PASS  profile: spawn refused                                              the lock raises 'locked off' for it (each feature's own code calls the lock first: that call is covered by the lock's tests, not exercis
PASS  profile: voice refused                                              the lock raises 'locked off' for it (each feature's own code calls the lock first: that call is covered by the lock's tests, not exercis
PASS  guards: the canaries are refused                                    8 of 8 tries refused before anything was sent
PASS  guards: they record what was tried                                  6 network and 2 program attempts logged
PASS  runtime: every named route answers without a 5xx                    19 GET routes and 2 GET prefixes requested; 17 POST routes requested with an empty body (their validation path; see the next line for th
PASS  runtime: real payloads through the handlers                         15 of 17 POST routes took a real payload the board accepted; the others answered only their validation path: /api/run-kill (a card with 
PASS  red-team: a command provider                                        the command was not run (the lock refused it)
PASS  red-team: an http provider (SSRF)                                   no connection and no lookup was even attempted for the metadata address
PASS  red-team: a file provider outside the folder                        the file outside the project was not read into the prompt
PASS  red-team: the prompt still builds                                   the prompt came back with the refusals as warnings
PASS  http: wrong Host refused (DNS rebinding)                            8 wrong Host headers, all 403
PASS  http: the two own names work                                        localhost:PORT and 127.0.0.1:PORT answer
PASS  http: cross-site POST refused (CSRF)                                5 cross-site POSTs, all 403
PASS  http: only exact application/json is accepted                       form, text, multipart and look-alike types all 415
PASS  http: GETs with side effects refuse cross-site                      /api/prompt and /api/orch-prompt: 403 for a cross-site browser
PASS  http: oversized and malformed bodies refused                        4 cases answered 400 and nothing was written
PASS  http: a JSON bomb gets a clean 400 and the server lives             deeply nested JSON: 400, still serving
PASS  http: a very long title                                             400, still serving
PASS  http: one request per connection (no pipelining)                    two requests in one write: exactly one response, then the connection closes
PASS  http: no request smuggling                                          Content-Length with Transfer-Encoding, chunked bodies and duplicate lengths never yield a second response
PASS  http: no header injection                                           an encoded or bare CR in a request never reaches a response header
PASS  http: over-long request line and headers refused                    70 KB line 414, 300 headers 431, one 70 KB header refused
PASS  http: a stalled client is dropped                                   a body that never finishes was cut after 2.0 s (the handler timeout; 15 s in the real server)
PASS  http: a flood of connections is capped                              158 connections opened: 128 are held idle (the cap, 128), 30 more were refused with 503 at once, one more request got 503, and the serve
PASS  http: a request with no version and no Host                         nothing of the board comes back (no Host to check, so it is refused)
PASS  http: an absolute-form target with another Host is refused          403: the Host header decides, not the target
PASS  http: nosniff on every kind of response                             JSON, report index and error pages all say nosniff
PASS  http: other verbs are not implemented                               PUT, DELETE, PATCH, OPTIONS, TRACE, CONNECT and WebDAV verbs: 501 (no CORS preflight can succeed)
PASS  http: HEAD                                                          501
PASS  http: no CORS headers                                               no response grants any other origin access
PASS  http: the page cannot be framed, sniffed or made to load elsewhere  Content-Security-Policy default-src 'none', frame-ancestors 'none', X-Frame-Options DENY, nosniff
PASS  red-team: path traversal                                            88 traversal URLs (11 spellings under 8 route prefixes): nothing outside the board served, no 5xx
PASS  red-team: a report that is a symlink out of its folder              not served
PASS  red-team: a transcript path that is any file                        an arbitrary registered file is not read back
PASS  red-team: unknown board names                                       not found, and nothing loaded from a path built from the name
PASS  http: the server is still serving after all of it                   yes
PASS  files: private modes                                                the board folder is 0700 and what the server wrote is 0600
PASS  runtime: nothing tried to leave this machine                        1164 connections and lookups were all loopback or this machine's own; no outside address was ever tried
PASS  runtime: no program was started                                     the server and every route started nothing (1164 loopback sockets used)
PASS  runtime: listening only on loopback                                 the server's socket is bound to 127.0.0.1
0 FAIL, 0 WARN, 54 PASS, 0 INFO
RESULT: PASS
```

## Tests

Full suite on the branch tip: **1335 tests, OK** (run in the foreground; 346 s on a loaded machine). `agentboard selfcheck` with the profile on: 54 PASS, 0 FAIL, three runs in a row. `tests/publiccheck.py`: 0 findings. One existing test was updated because it pinned something this branch changed on purpose: `test_server_state` (the state file now also records `profile`); the `test_file_modes` change went to main with the hardening branch. Note for whoever reruns it: start the suite in the foreground; a shell `&` makes the child processes ignore SIGINT and the two real-server tests in `test_server_state` then time out waiting for a server that cannot be interrupted.

## The cross-review's three findings, fixed on this branch (AGENT-8, Nov 8)

| Card | What was wrong | What it does now |
|---|---|---|
| `xr-workpc-selfcheck-overclaims` (MEDIUM) | "every route" and "25 POST routes" were counts of regex hits (the pattern also matched 8 GET routes) and most POSTs got an empty `{}` body; "no address in any string" only looked for `scheme://`; "158 idle connections held" counted 30 that got 503; `import os as o; o.system()` and `from os import system` passed the program scan | Routes are read from the handlers' own comparisons (`_route_get` for GET, `do_POST` for POST): **19 GET, 17 POST**. The sweep line says the 17 got an empty body (validation path only); a second line says **15 of 17 POST routes took a real payload the board accepted** and names the two that cannot here (`/api/run-kill`: no running one-shot, `run` is locked; `/api/transcribe`: voice is locked). The address scan reads bare IPv4 literals and host names with a common suffix as well as URLs, and says what it did not read (docstrings, addresses built at run time). Aliases of `os` (`import os as o`, `from os import system`, `getattr(os, "system")`) are resolved. The flood line says **158 opened: 128 held idle (the cap), 30 more refused with 503**. The lock lines say they check the lock, not the features' own call sites. The traversal count is computed. |
| `xr-workpc-selfcheck-live-canaries` (MEDIUM) | The canaries dialled 93.184.216.34, a public resolver (8.8.8.8) and `example.com`: a guard that stopped working would have made the self-check contact them from the PC | Every canary target is a documentation address (192.0.2.x, 198.51.100.x) or a `.invalid` name; the metadata-address provider probe uses 198.51.100.45; even the non-loopback bind probe uses a documentation address. The static address scan now allows only this machine, the documentation ranges and reserved names, and a test fails if `selfcheck.py` or the profile tests name any other address. |
| `xr-workpc-profile-off-message` (MEDIUM) | `apply()` writes `AGENTBOARD_PROFILE=work` into the environment for what it starts, so `agentboard profile off` and `selfcheck` called the machine file "the environment" and said the environment still said work in a shell that never set it | The shell's own word is noted before `apply()` overwrites it (only when it overwrites it), so sources are named truthfully: machine / environment / board. `profile off` lists exactly what still keeps it on. Tests run real subprocesses with only the machine file, only the environment, both, and only the board's config. |

Also found while fixing: a flood check that failed when the audit server's short stalled-client timeout freed idle sockets early (now measured, not assumed), and the audit's chat probes used a literal owner name (now the board's own).

## The rebase

On Nov 8, after `chat-f7`, `hooks-known-only` and `hooks-settings-orig` merged. One conflict (an import line in `doctor.py`: main added `redact` and `untrusted`, this branch adds `profile`; both kept). The selfcheck's connection-flood check failed once on the rebased tree because the audit server's 2-second stalled-client timeout freed the early idle connections before the last one was open on a loaded machine; the audit now holds the timeout at 30 s for that one check. `agentboard selfcheck --live 8765` against the home board is unchanged in outcome: every probe passes except `nosniff` (the installed server predates it) and it reports the lock off / plugins open as a WARN.

## Decisions and risks

- **Not the default for a fresh install.** A home user's board uses `claude -p` rounds, `run`, voice and plugins; turning the profile on by default would break them silently. The profile is one command (`agentboard profile work`), one environment variable or one line in a new board's config, and `agentboard selfcheck` says WARN when it is not on. Troy's call whether `pipx install` should ship it on.
- **The guards are not a sandbox.** They refuse what Python code does through `socket`, `subprocess` and `os`. A C extension, `ctypes`, or a program the board did not start can still reach out; the static scan fails the build on `ctypes`, `cffi` and any third-party import (the package has no dependencies) but a firewall is still the answer to a hostile process on the machine.
- **The network guard is installed in every command under the profile**, not only the server, so a plugin-less `agentboard` run cannot make an outside request either. Loopback traffic (the CLI talking to a running board) is untouched.
- **`serve` in the profile starts no program**, which also means `agentboard serve` never opens the browser (it already prints the address) and the "commits made" line on a finished card is empty. `agentboard doctor`, `hooks` and other commands (not the server) can still start `git`; they are the person's own command line.
- **Still no login** (accepted risk of the board's owner, unchanged): any program running as the same user can reach the port. The Host/Origin/Sec-Fetch checks keep websites out.
- **Platform:** written and run on macOS with Python 3.14; the guards use only portable calls (`os.fork` and friends are patched only where they exist). Windows was not run.
- **Timing tests:** `test_redact_dos`, `test_redact_fullwidth` and `test_redact_dashes` have thresholds that fail when the machine is loaded (they fail the same way on unmodified `main` at load average 16); they are unrelated to this branch.

## Next-best improvements (filed as cards)

- `work-pc-run-agentboard-profile-work-and`: Troy runs `profile work`, `selfcheck` and `doctor` on the real work PC and pastes the output (the one proof this Mac cannot give: that PC's Python, OS and security software).
- `selfcheck-live-audit-the-running-server`: **done on this branch** (commit 6d23126): `agentboard selfcheck --live [PORT]`, read-only probes of the server that is actually running (never a card, chat line, report or transcript; empty-body POSTs only), its recorded start state and doctor's listener check. First real run against the home board: all probes pass except `nosniff` (the installed server predates the fix) and it reports the lock OFF and plugins OPEN, as a WARN because this shell was not under the profile.
- `decision-for-troy-should-a-fresh-install`: should a fresh install on a managed PC ship with the profile on (recommended: a separate `agentboard-work` entry point).
