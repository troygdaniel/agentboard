# Security and network behaviour

agentboard runs entirely on your machine. This audit (Oct 20, 2026, v0.2.0) was re-checked on
Oct 24, 2026 for v0.3.0 and again on Nov 7, 2026 against `main` at 0d92375 (v0.3.1), by five separate
read-only audits (network, install, the page and API, data and secrets, and a red-team re-check of the fixes); it checks literally
rather than by assumption. The plain-language verdict, what is still open and a work-laptop checklist are in
[`docs/security-audit-2026-11-07.md`](docs/security-audit-2026-11-07.md); `agentboard doctor` repeats the machine checks.

## Verdict

**Local-only, safe to run on a managed work machine with the settings below.** With its default configuration, agentboard makes no
network connections beyond `127.0.0.1`, has no dependencies, runs nothing at install and has no telemetry. Everything that could reach
outside is **opt-in and off by default**: the `http` and `command` providers, one-shot runs (`agentboard run`) and the chat rounds (both
start the `claude` program), the `[backup] sync_dir` copy, voice, and plugins (code you installed and switched on; agentboard ships
with none). **`AGENTBOARD_LOCKDOWN=1` refuses all of them at once** (see "The master lock"). Another network moment happens only at
install time.

**Not covered:** the board has no login. Any program running as the same user, or a browser extension, can reach the local port;
websites cannot. A fix was written and the owner decided not to merge it (see "Known gaps"). Texting features are not in this tree at all.

## What was checked, and how

| Area | Finding | How verified |
|---|---|---|
| Python dependencies | **None.** `dependencies = []`; stdlib only | `pyproject.toml` |
| Outbound calls in Python | Only `providers.py` opens a socket of its own (the opt-in `http` provider). Programs the board starts (`claude`, `git`, `ffmpeg`/`whisper`, `osascript`) may reach out themselves; all of those are opt-in or run by you, and the master lock refuses the ones the board would start | Every `import` in `src/` listed and reviewed; `agentboard doctor` lists the modules that can connect or listen; the network audit ran the whole test suite (854 tests then) under a socket guard: 0 non-loopback attempts |
| Server binding | `127.0.0.1` only, hard-coded; there is no option to bind other interfaces. Default port 8765 (`--port` to change). Each request handler has a 15 s socket timeout and a 1 MB body cap; card fields have their own caps (title 200, description 20,000, body 60,000), so a local process cannot pin threads with half-sent bodies or bloat every client's poll with one card | `server.py`; at runtime, `lsof` showed one socket, `TCP 127.0.0.1:<port> (LISTEN)`, and no outbound connections |
| Browser-side requests | Only same-origin `/api/...` calls to the local server | Every `fetch` / `api()` call reviewed; at runtime, headless Chrome recorded every request while loading the board, a card's detail panel (with prompt preview) and the HUD: **0 non-local requests** |
| CDNs, web fonts, external scripts or images | **None.** System fonts; icons are inline SVG; favicon is a `data:` URI; sounds are synthesized with Web Audio (no audio files) | Scan of `index.html` for absolute URLs, `<script src>`, `<link href>`, `@import`, `url(` |
| Telemetry, analytics, update checks, crash reporting | **None** | No such code or dependency exists |
| Data storage | Local files only: `.agentboard/tasks.json` (cards, chat and the agent-chat switch), `.agentboard/config.toml`, `.agentboard/.lock`, `.agentboard/chat-cursors.json` (where each agent got to in the chat), `.agentboard/sessions.json` (which session name belongs to which Claude Code session id, for the chat mirror) in your project. `agentboard hooks install` writes one hook entry into the project's `.claude/settings.json`; it runs `agentboard hook send-message`, which reads the hook payload from stdin and writes to the board file only. The browser also keeps 4 UI preferences in `localStorage` (`agentboard-theme`, `agentboard-snd`, `agentboard-amb`, `agentboard-notify`). Desktop notifications, when the bell is switched on, use the browser's own Notification API for this page only; nothing leaves the machine. Nothing is synced anywhere | `store.py`, `prompt.py`, `index.html` |
| Secrets in card text | Text agents write (title, description, status lines, questions, results, review bodies, their chat lines) is masked where it enters the store (`redact.py`): keys with well-known prefixes, tokens, JWTs, private-key blocks, `Authorization:` values, `api_key = "…"` and long hex after key/token/secret become `[redacted …]`, so they never reach tasks.json, its .bak, the snapshots, the sync copy, reports, the page or the chat; reports mask older cards again. Nothing else is touched by default. What the owner types is left as written. The Terminal tab and `/api/transcript` mask the same shapes in every line they show (commands, URLs, typed lines, assistant text, errors, question options); the session's own file is never changed. A secret split by an invisible character (a zero-width space, a bidi override, a soft hyphen) is still found and masked whole; ordinary text that uses those characters is not rewritten. Also masked: Stripe, Google `AIza`, Slack webhook, npm and SendGrid keys, the password in `scheme://user:pass@host`, `aws_secret_access_key = …`, `?key=…` and a bare `Bearer …`. Not caught, by design: a short or oddly shaped secret (`password: hunter2`) cannot be told from ordinary text. `agentboard redact` finds what is already stored | `redact.py`, `store.py`, `transcript.py` |
| Who can read the board's files | Everything under `.agentboard/` is mode 0600 (folders 0700): the command line and `serve` run with umask 077, `serve` tightens older files at start, programs the board starts (`claude -p`, provider commands) get your own umask back so your project's files are unchanged. Other accounts on the machine, including those that can walk through a Mac home folder, cannot read cards, reports, config (phone numbers) or session ids. `AGENTBOARD_UMASK=022` turns it off | `private.py` |
| Nothing private is committed | `tests/publiccheck.py` (also a test, so the suite fails) reads every tracked text file for secret shapes, non-fictional phone numbers, emails outside an allow-list, a real account's home path and your own private words (a file outside the repo); it prints locations, never values. All commits on all branches were also searched once and the screenshots read with on-device OCR: clean | `tests/publiccheck.py` |
| Cross-site access to the local server | Requests with a foreign `Host` header are rejected (blocks DNS rebinding), as are POSTs with a foreign `Origin` header, a `Sec-Fetch-Site` other than `same-origin`/`none`, or a media type that is not exactly `application/json` (parameters allowed; a CORS-simple type such as `text/plain;charset=application/json` gets 415, so any cross-site POST needs a preflight, which the server never answers) | `server.py`, `tests/test_post_guards.py` |
| The board page's own defences | The page is sent with a Content-Security-Policy: its one inline script runs only with a per-response nonce (the page has no inline event handlers), `connect-src 'self'` (script cannot send anything to another host), no frames, images or workers; and `X-Frame-Options: DENY` / `frame-ancestors 'none'` (no other site can frame it), `nosniff`, no Referer. Card text is escaped for text and for quoted attributes | `server.py`, `static/index.html` (`esc`) |
| Card reports | `.agentboard/reports/*.html` are served only under `/reports/`, only names of the form `<card>-<timestamp>.html`; agent text is escaped; pages carry a Content-Security-Policy (`default-src 'none'`, connect to this server only). The sweep deletes only files of that exact name shape | `reports.py`, `server.py` |
| Opening the browser | `agentboard serve` opens `http://localhost:<port>/` in your default browser (skip with `--no-open`) | `server.py` |

## Opt-in exceptions (off by default)

1. **`http` context provider.** If you define one in `.agentboard/config.toml`, building a prompt that
   uses it sends an HTTP GET to the URL you configured. The default config has every provider commented out.
2. **`command` context provider.** Runs a shell command you configure; that command can do anything,
   including network calls.

3. **One-shot agents (`agentboard run`) and the chat drafter (`agentboard chat idle`).** Both start the `claude` binary you already have, which talks to Anthropic the way it always does. The drafter runs it once per `chat idle` call, with `-p`, a model and a budget cap, the prompt on stdin; with `[chat] autopilot = true` (off by default) `agentboard serve` runs the same drafter on a timer for idle agents with unread chat, at most `autopilot_per_hour` times an hour; with `[chat] casual = true` it also runs it once per agent chat line to produce the spoken version, at most `casual_per_hour` times an hour.
   agentboard adds no connection of its own, never passes a flag that widens the run's permissions (no `--dangerously-skip-permissions`,
   `--permission-mode` or `--allowedTools`), and enforces a wall-clock limit and a spend cap. Only runs when you start one.
4. **Plugins (`AGENTBOARD_PLUGINS=1`).** A plugin is a separate package, installed next to agentboard and switched on by the machine; agentboard ships with none and
   names none. Nothing is looked up, imported or shown unless `AGENTBOARD_PLUGINS` is exactly `1`; `AGENTBOARD_NO_PLUGINS=1` and `AGENTBOARD_LOCKDOWN=1` both stop it, are read on every
   call (a lock set after the board started closes every plugin route at once), and win over the key. A plugin can add a command, routes under its own `/api/x/<name>/` (same Host, Origin and
   JSON checks as the core routes), a block of state on the poll, a thread and a page script (served same-origin, covered by the page's `script-src 'self'`); it cannot register outside
   its namespace or shadow a core command, one plugin failing costs only itself, and an error reaches the client as its class name. **A plugin is trusted like any package you install: it
   can do whatever its code does, including network calls.** On a work machine, install none and do not set `AGENTBOARD_PLUGINS`. To check a machine, run `agentboard plugins`: with the
   key unset it prints `plugins: off: $AGENTBOARD_PLUGINS is not 1 (nothing is looked up, loaded or imported)` and makes no network call.

   **The text-message features are not in this tree.** Pulling texts into cards (including its once-a-minute timer) and the inbound-SMS webhook were removed from agentboard on Nov 7, 2026 and now
   live in a separate home-only package that is kept outside this repository. A test (`tests/test_no_text_code.py`) fails if `src/agentboard` ever contains "twilio", "sms" or "pull-texts", and
   another fails if any tracked file holds a phone-number-shaped string (other than a fictional 555-01xx one) or an account SID. **History:** the earlier commits on GitHub still contain that
   code (history was not rewritten), so a reviewer can read it there; the shipped tree (the tip of `main`, what a new install gets) does not, and cards made from texts keep their guard: their
   words reach an agent as quoted data, never as instructions.

Providers run only when a task explicitly lists them (`--ctx`) and a prompt is built (Copy prompt,
`agentboard prompt`, `agentboard rebuild`). Building one over HTTP (`GET /api/prompt`, `/api/orch-prompt`) is refused with 403 when the browser's
`Sec-Fetch-Site` says the request came from another site, so a hostile page cannot make the board run a configured command blind; `{arg}` and `{title}`
are shell-quoted, and the README says not to wrap them in quotes of your own. On a work machine, point `http` providers only at local
services, or don't configure any.

## The master lock: `AGENTBOARD_LOCKDOWN`

Set `AGENTBOARD_LOCKDOWN=1` in the shell profile of a work machine (`src/agentboard/lockdown.py`). It fails closed (locked unless the variable is
unset or one of `""`, `0`, `false`, `no`), is read on every call and never cached, and refuses **before any process starts or any socket opens**:
the board's own `claude -p` rounds (chat casual, autopilot, idle drafts), `agentboard run` (and `run --detach`), the `command` and `http` context
providers (the prompt still builds and says why the provider was skipped), the `[backup] sync_dir` copy (local snapshots stay), voice, dictate and
paste, `spawn`, and every plugin (`plugins.py` checks it first, so no entry point is looked up or imported). The tests make `subprocess` and `urllib` fail
if a locked path reaches them. `AGENTBOARD_NO_PLUGINS=1` is the narrow lock for plugins alone. A copied `config.toml` or `tasks.json` therefore cannot
switch any of these on while the lock is set.

The board's own `claude -p` rounds (when you allow them) run with `--tools "" --strict-mcp-config --disable-slash-commands --no-session-persistence`
from an empty temporary folder: one message in, one short reply out, nothing to act with. `agentboard run` is the exception on purpose: it works in
a repo with the permissions an interactive agent there has, and never passes a flag that widens them.

`agentboard lookup "words"` is read-only: it searches done and archived cards and reports in the board's own folder, writes nothing (not to a card, report,
log, backup or the page), opens no socket, starts no program, and prints each snippet cleaned of control characters, secret-masked and quoted as data. A plugin may
add a source; with plugins off or locked there are none. Core code never opens a file named in `config.toml`.

## Checking a machine

`agentboard doctor` is read-only and prints PASS / WARN / FAIL lines you can paste into a review: whether `AGENTBOARD_LOCKDOWN` is set (WARN if not) and which
`config.toml` switches it would stop, the ports the board listens on (loopback only?), any open connection to another machine, whether the board folder is private
(mode 700/600), the tracked files of the project (secrets, numbers, home paths), the Claude hooks installed, and which modules can connect or listen. By hand:

    agentboard plugins                                              # plugins: locked / off, and what is loaded; no network call
    lsof -nP -a -p $(pgrep -f "agentboard serve" | head -1) -i     # one line: 127.0.0.1:8765 (LISTEN), nothing else
    ls -ld .agentboard; ls -l .agentboard                           # drwx------ and -rw-------
    grep -rniE "twilio|sms" src/agentboard                          # no output (from a checkout)
    python3 tests/publiccheck.py                                    # 0 finding(s); run before any push

## Known gaps

- **No login on the local port.** Any program running as the same user, or a browser extension, can read and change every card through `127.0.0.1:8765`;
  websites cannot (Host, Origin, `Sec-Fetch-Site` and content-type checks, and a Content-Security-Policy). A key-cookie lock was written (`sec-local-token`, branch
  `sec-web`) and the owner decided not to merge it, because it changes how the board is opened (`agentboard open` once per browser; `serve --no-token` turns it off).
  The branch is parked, not deleted. Treat the board as readable by everything that runs as you.
- **A plugin is trusted code.** It can do whatever its code does. Install none on a work machine; the master lock refuses them.
- **Text you do not control becomes card text** when an agent copies web or email content into the board. It is escaped in the page, masked for secrets and framed as
  quoted data in prompts, but it is untrusted: do not point agents that read email or web pages at a board on a work machine.
- **Not audited:** the `claude` program's own traffic, other apps and browsers, Linux and Windows, and running the voice tools (`whisper`, `ffmpeg`).

## Install-time network (not runtime)

Installing fetches files once: from GitHub if you install with `pipx install git+https://...`, and
setuptools from PyPI (the build backend) when building from source. After install, nothing is fetched again.

**Upgrading a checkout: remove `build/` first** (`git pull && rm -rf build && pipx install . --force`). pip builds inside the checkout and setuptools keeps in `build/` any file that was
deleted from `src/`, so the installed copy can carry code that was removed from the repository (reproduced: a wheel built after two modules were deleted still contained both). `agentboard doctor` compares the
installed copy with the folder it was installed from and warns ("stale install", naming the files and the fix); a fresh clone has no `build/` and needs nothing.

## What changed since the Oct 24 re-check (Nov 7, 2026)

Fixed and merged after the five audits: card text could break out of an HTML attribute and run script in the board page (HIGH; escaping fixed); the page now carries a
Content-Security-Policy and cannot be framed; POSTs need exactly `application/json` and a same-site origin; a stalled client is dropped after 15 s and fields have size
caps; building a prompt over GET no longer runs a provider for a cross-site request; the transcript route opens the path it checked and refuses NULs and pipes; secrets are
masked where text enters the board and in the Terminal tab; board files are mode 0600/0700; `reports.git_info` validates run records from `tasks.json` (a base such as `--output=path`
once made `git` write a file); `hooks install` writes agentboard's full path (and `hooks uninstall` exists); `claude -p` rounds run with no tools; and the master lock above.
The text-message features left the repository. One finding is open by design: the no-login item under "Known gaps".

## What changed in v0.3.0 (re-check, Oct 24, 2026)

- Still no dependencies (`dependencies = []`), still `127.0.0.1` only, still no outbound code
  outside the two opt-in providers. New code since v0.2.0 (HUD grid and actions, detail panel
  formatting, subtasks, chat, wait, tail, report, notifications) adds no network path:
  `grep -n "urllib.request\|subprocess\|socket\|webbrowser" src/agentboard/*.py` still lists only
  `providers.py` (opt-in `http` / `command`), `server.py` (the local listener and the browser open)
  and `cli.py` (`osascript` for the opt-in `[notify]` banners, `agentboard spawn`).
- The browser page still makes only same-origin requests. `index.html` contains no absolute URL
  but the SVG namespace; the HUD and the detail panel render agent text through the server-side
  markdown renderer or escaped, never as raw HTML.
- `agentboard init` now adds `.agentboard/` to the project's `.gitignore` (creating the file if
  needed), so task data, which can hold private context, stays out of version control by default.
- `[hud] retired = [...]` only filters which agent names the HUD shows; no data is deleted.

## Public repository

The public GitHub repo contains the code, README, CHANGELOG, SECURITY.md, the license and a few screenshots under `docs/` taken from demo / throwaway boards.
Task data (`.agentboard/`) is git-ignored and has never been committed. The Nov 7 data audit searched every commit on every branch (272 commits, 60 branches at the
time) for key and token shapes, assigned secrets and phone numbers (none; every number in the repo is a fictional 555 one) and read every screenshot with
on-device OCR (synthetic demo cards only). A few project names from the author's other work appear in old commits of docs mockups and tests. The earlier text-message
code (removed on Nov 7, see above) is still in old commits because history was not rewritten. Commit metadata shows the author's name and email.
`tests/publiccheck.py` guards what is committed from now on.

## Backups

Snapshots are plain files under `.agentboard/backups/` (and, only if you set `[backup] sync_dir`, copies in a folder you chose). Nothing is sent anywhere by the backup code; treat the snapshots like the board file itself.
