# overnight-sec-workpc-profile: the work-PC profile and `agentboard selfcheck`

Branch `overnight/overnight-sec-workpc-profile` (public repo, nothing merged, nothing pushed). Card `overnight-sec-workpc-profile`, AGENT-3.

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
PASS  static: network-capable imports                                     only where the table allows (4 files): guards.py: socket, providers.py: urllib.request, selfcheck.py: http.client, selfcheck.p
PASS  static: program-starting code                                       only in 9 files, each locked or a command: agentchat.py, cli.py, doctor.py, guards.py, providers.py, reports.py, runs.py, self
PASS  static: shell=True                                                  only in providers.py (the command provider, locked)
PASS  static: eval, exec, pickle                                          none
PASS  static: computed imports                                            none (every import is written out)
PASS  static: third-party packages                                        none: standard library only
PASS  static: declared dependencies                                       an empty list
PASS  static: addresses in the code                                       no address but this machine's (and reserved example names) in any string
PASS  static: the page loads nothing from outside                         2 page files scanned, no script, style, image, font, frame or request to another host; Content-Security-Policy default-src 'no
PASS  profile: on in this shell                                           environment: $AGENTBOARD_PROFILE=work
PASS  profile: master lock                                                AGENTBOARD_LOCKDOWN is on while the audit runs
PASS  profile: plugins refused                                            plugins: locked: $AGENTBOARD_LOCKDOWN is set
PASS  profile: claude rounds refused                                      BoardError: locked off
PASS  profile: agentboard run refused                                     BoardError: locked off
PASS  profile: spawn refused                                              BoardError: locked off
PASS  profile: voice refused                                              BoardError: locked off
PASS  guards: the canaries are refused                                    8 of 8 tries refused before anything was sent
PASS  guards: they record what was tried                                  6 network and 2 program attempts logged
PASS  runtime: every route answers                                        19 GET and 25 POST routes and 2 prefixes requested, none a 5xx or a dropped connection
PASS  runtime: a day of work through the handlers                         add, edit, move, finish (report and git line), chat, reply, delete, summary, hud, page: all answered
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
PASS  http: a flood of connections is capped                              158 idle connections held: the next is refused with 503 at once, and the server answers normally after they close
PASS  http: a request with no version and no Host                         nothing of the board comes back (no Host to check, so it is refused)
PASS  http: an absolute-form target with another Host is refused          403: the Host header decides, not the target
PASS  http: nosniff on every kind of response                             JSON, report index and error pages all say nosniff
PASS  http: other verbs are not implemented                               PUT, DELETE, PATCH, OPTIONS, TRACE, CONNECT and WebDAV verbs: 501 (no CORS preflight can succeed)
PASS  http: HEAD                                                          501
PASS  http: no CORS headers                                               no response grants any other origin access
PASS  http: the page cannot be framed, sniffed or made to load elsewhere  Content-Security-Policy default-src 'none', frame-ancestors 'none', X-Frame-Options DENY, nosniff
PASS  red-team: path traversal                                            88 traversal URLs over every route that takes a name: nothing outside served, no 5xx
PASS  red-team: a report that is a symlink out of its folder              not served
PASS  red-team: a transcript path that is any file                        an arbitrary registered file is not read back
PASS  red-team: unknown board names                                       not found, and nothing loaded from a path built from the name
PASS  http: the server is still serving after all of it                   yes
PASS  files: private modes                                                the board folder is 0700 and what the server wrote is 0600
PASS  runtime: nothing tried to leave this machine                        1140 connections and lookups were all loopback or this machine's own; no outside address was ever tried
PASS  runtime: no program was started                                     the server and every route started nothing (1140 loopback sockets used)
PASS  runtime: listening only on loopback                                 the server's socket is bound to 127.0.0.1
0 FAIL, 0 WARN, 54 PASS, 0 INFO
RESULT: PASS
```

## Decisions and risks

- **Not the default for a fresh install.** A home user's board uses `claude -p` rounds, `run`, voice and plugins; turning the profile on by default would break them silently. The profile is one command (`agentboard profile work`), one environment variable or one line in a new board's config, and `agentboard selfcheck` says WARN when it is not on. Troy's call whether `pipx install` should ship it on.
- **The guards are not a sandbox.** They refuse what Python code does through `socket`, `subprocess` and `os`. A C extension, `ctypes`, or a program the board did not start can still reach out; the static scan fails the build on `ctypes`, `cffi` and any third-party import (the package has no dependencies) but a firewall is still the answer to a hostile process on the machine.
- **The network guard is installed in every command under the profile**, not only the server, so a plugin-less `agentboard` run cannot make an outside request either. Loopback traffic (the CLI talking to a running board) is untouched.
- **`serve` in the profile starts no program**, which also means `agentboard serve` never opens the browser (it already prints the address) and the "commits made" line on a finished card is empty. `agentboard doctor`, `hooks` and other commands (not the server) can still start `git`; they are the person's own command line.
- **Still no login** (accepted risk of the board's owner, unchanged): any program running as the same user can reach the port. The Host/Origin/Sec-Fetch checks keep websites out.
- **Platform:** written and run on macOS with Python 3.14; the guards use only portable calls (`os.fork` and friends are patched only where they exist). Windows was not run.
- **Timing tests:** `test_redact_dos`, `test_redact_fullwidth` and `test_redact_dashes` have thresholds that fail when the machine is loaded (they fail the same way on unmodified `main` at load average 16); they are unrelated to this branch.

## Next-best improvements (filed as cards)

See the cards `workpc-*` on the board.
