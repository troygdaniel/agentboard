# Security and network behaviour

agentboard runs entirely on your machine. This audit (Oct 20, 2026, v0.2.0) was re-checked on
Oct 24, 2026 for v0.3.0 against the code and at runtime; it checks literally rather than by assumption.

## Verdict

**Local-only.** With its default configuration, agentboard makes no network connections beyond
`127.0.0.1`. Opt-in exceptions exist, all off by default: the `http` and `command` providers, one-shot runs and the chat drafter, and plugins (code you installed and switched on with `AGENTBOARD_PLUGINS=1`; agentboard ships with none). Another happens only at install time.

## What was checked, and how

| Area | Finding | How verified |
|---|---|---|
| Python dependencies | **None.** `dependencies = []`; stdlib only | `pyproject.toml` |
| Outbound calls in Python | Only in the opt-in `http` and `command` context providers (below) | Every `import` in `src/` listed and reviewed |
| Server binding | `127.0.0.1` only, hard-coded; there is no option to bind other interfaces. Default port 8765 (`--port` to change). Each request handler has a 15 s socket timeout and a 1 MB body cap; card fields have their own caps (title 200, description 20,000, body 60,000), so a local process cannot pin threads with half-sent bodies or bloat every client's poll with one card | `server.py`; at runtime, `lsof` showed one socket, `TCP 127.0.0.1:<port> (LISTEN)`, and no outbound connections |
| Browser-side requests | Only same-origin `/api/...` calls to the local server | Every `fetch` / `api()` call reviewed; at runtime, headless Chrome recorded every request while loading the board, a card's detail panel (with prompt preview) and the HUD: **0 non-local requests** |
| CDNs, web fonts, external scripts or images | **None.** System fonts; icons are inline SVG; favicon is a `data:` URI; sounds are synthesized with Web Audio (no audio files) | Scan of `index.html` for absolute URLs, `<script src>`, `<link href>`, `@import`, `url(` |
| Telemetry, analytics, update checks, crash reporting | **None** | No such code or dependency exists |
| Data storage | Local files only: `.agentboard/tasks.json` (cards, chat and the agent-chat switch), `.agentboard/config.toml`, `.agentboard/.lock`, `.agentboard/chat-cursors.json` (where each agent got to in the chat), `.agentboard/sessions.json` (which session name belongs to which Claude Code session id, for the chat mirror) in your project. `agentboard hooks install` writes one hook entry into the project's `.claude/settings.json`; it runs `agentboard hook send-message`, which reads the hook payload from stdin and writes to the board file only. The browser also keeps 4 UI preferences in `localStorage` (`agentboard-theme`, `agentboard-snd`, `agentboard-amb`, `agentboard-notify`). Desktop notifications, when the bell is switched on, use the browser's own Notification API for this page only; nothing leaves the machine. Nothing is synced anywhere | `store.py`, `prompt.py`, `index.html` |
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

## Install-time network (not runtime)

Installing fetches files once: from GitHub if you install with `pipx install git+https://...`, and
setuptools from PyPI (the build backend) when building from source. After install, nothing is fetched again.

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

The public GitHub repo contains the code, README, CHANGELOG, SECURITY.md, the license and a few
screenshots under `docs/` taken from demo / throwaway boards. Task data (`.agentboard/`) is
git-ignored and has never been committed; no personal data appears anywhere in the commit history.
Commit metadata does show the author's name and email.

## Backups

Snapshots are plain files under `.agentboard/backups/` (and, only if you set `[backup] sync_dir`, copies in a folder you chose). Nothing is sent anywhere by the backup code; treat the snapshots like the board file itself.
