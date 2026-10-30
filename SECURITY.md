# Security and network behaviour

agentboard runs entirely on your machine. This audit (Oct 20, 2026, v0.2.0) was re-checked on
Oct 24, 2026 for v0.3.0 against the code and at runtime; it checks literally rather than by assumption.

## Verdict

**Local-only.** With its default configuration, agentboard makes no network connections beyond
`127.0.0.1`. Four opt-in exceptions exist, all off by default (the `http` and `command` providers, one-shot runs, and the text-message endpoint). Another happens only at install time.

## What was checked, and how

| Area | Finding | How verified |
|---|---|---|
| Python dependencies | **None.** `dependencies = []`; stdlib only | `pyproject.toml` |
| Outbound calls in Python | Only in the opt-in `http` and `command` context providers (below) | Every `import` in `src/` listed and reviewed |
| Server binding | `127.0.0.1` only, hard-coded; there is no option to bind other interfaces. Default port 8765 (`--port` to change) | `server.py`; at runtime, `lsof` showed one socket, `TCP 127.0.0.1:<port> (LISTEN)`, and no outbound connections |
| Browser-side requests | Only same-origin `/api/...` calls to the local server | Every `fetch` / `api()` call reviewed; at runtime, headless Chrome recorded every request while loading the board, a card's detail panel (with prompt preview) and the HUD: **0 non-local requests** |
| CDNs, web fonts, external scripts or images | **None.** System fonts; icons are inline SVG; favicon is a `data:` URI; sounds are synthesized with Web Audio (no audio files) | Scan of `index.html` for absolute URLs, `<script src>`, `<link href>`, `@import`, `url(` |
| Telemetry, analytics, update checks, crash reporting | **None** | No such code or dependency exists |
| Data storage | Local files only: `.agentboard/tasks.json` (cards, chat and the agent-chat switch), `.agentboard/config.toml`, `.agentboard/.lock`, `.agentboard/chat-cursors.json` (where each agent got to in the chat) in your project. The browser also keeps 4 UI preferences in `localStorage` (`agentboard-theme`, `agentboard-snd`, `agentboard-amb`, `agentboard-notify`). Desktop notifications, when the bell is switched on, use the browser's own Notification API for this page only; nothing leaves the machine. Nothing is synced anywhere | `store.py`, `prompt.py`, `index.html` |
| Cross-site access to the local server | Requests with a foreign `Host` header are rejected (blocks DNS rebinding), as are POSTs with a foreign `Origin` header or a non-JSON content type | `server.py` |
| Card reports | `.agentboard/reports/*.html` are served only under `/reports/`, only names of the form `<card>-<timestamp>.html`; agent text is escaped; pages carry a Content-Security-Policy (`default-src 'none'`, connect to this server only). The sweep deletes only files of that exact name shape | `reports.py`, `server.py` |
| Opening the browser | `agentboard serve` opens `http://localhost:<port>/` in your default browser (skip with `--no-open`) | `server.py` |

## Opt-in exceptions (off by default)

1. **`http` context provider.** If you define one in `.agentboard/config.toml`, building a prompt that
   uses it sends an HTTP GET to the URL you configured. The default config has every provider commented out.
2. **`command` context provider.** Runs a shell command you configure; that command can do anything,
   including network calls.

3. **One-shot agents (`agentboard run`) and the chat drafter (`agentboard chat idle`).** Both start the `claude` binary you already have, which talks to Anthropic the way it always does. The drafter runs it once per `chat idle` call, with `-p`, a model and a budget cap, the prompt on stdin; with `[chat] autopilot = true` (off by default) `agentboard serve` runs the same drafter on a timer for idle agents with unread chat, at most `autopilot_per_hour` times an hour.
   agentboard adds no connection of its own, never passes a flag that widens the run's permissions (no `--dangerously-skip-permissions`,
   `--permission-mode` or `--allowedTools`), and enforces a wall-clock limit and a spend cap. Only runs when you start one.
4. **Text the board (`agentboard sms serve`).** An inbound Twilio webhook on its **own** listener, `127.0.0.1:8766`, separate from the board
   server (so a tunnel pointed at it exposes `/sms` and `/health` and nothing else). It will not start if `AGENTBOARD_NO_SMS=1` is set (a hard lock for work machines), and otherwise not unless `[sms] enabled = true`, an allowlist,
   an `https` `public_url` and the Twilio auth token (read from an environment variable, never from a file in the board) are all set. Each request
   needs a valid `X-Twilio-Signature` (HMAC-SHA1 over the URL and the form, constant-time compare), a sender on the allowlist, and a `MessageSid`
   not seen in the last 7 days (replay protection, kept in `.agentboard/sms-state.json`); there is also an hourly cap. Anything refused gets a bare
   403 and no text back. It never calls the Twilio API: replies travel in the HTTP response, so the only cost is the texts themselves. The grammar can
   add and move cards and read a one-line status; it cannot delete, run commands or read card text. Commands are applied through the normal store (atomic
   write, `.bak`, hourly snapshots). Turning it on means a public tunnel to your Mac: that switch is yours.

Providers run only when a task explicitly lists them (`--ctx`) and a prompt is built (Copy prompt,
`agentboard prompt`, `agentboard rebuild`). On a work machine, point `http` providers only at local
services, or don't configure any.

## Install-time network (not runtime)

Installing fetches files once: from GitHub if you install with `pipx install git+https://...`, and
setuptools from PyPI (the build backend) when building from source. After install, nothing is fetched again.

## What changed in v0.3.0 (re-check, Oct 24, 2026)

- Still no dependencies (`dependencies = []`), still `127.0.0.1` only, still no outbound code
  outside the two opt-in providers. New code since v0.2.0 (HUD grid and actions, detail panel
  formatting, subtasks, projects, chat, wait, tail, report, notifications) adds no network path:
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
