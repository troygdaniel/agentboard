# Security and network behaviour

agentboard runs entirely on your machine. This audit (Oct 20, 2026, v0.2.0 plus later commits through
`4730b73`) checked it literally rather than by assumption.

## Verdict

**Local-only.** With its default configuration, agentboard makes no network connections beyond
`127.0.0.1`. Two opt-in exceptions exist, both off by default. A third happens only at install time.

## What was checked, and how

| Area | Finding | How verified |
|---|---|---|
| Python dependencies | **None.** `dependencies = []`; stdlib only | `pyproject.toml` |
| Outbound calls in Python | Only in the opt-in `http` and `command` context providers (below) | Every `import` in `src/` listed and reviewed |
| Server binding | `127.0.0.1` only, hard-coded; there is no option to bind other interfaces. Default port 8765 (`--port` to change) | `server.py`; at runtime, `lsof` showed one socket, `TCP 127.0.0.1:<port> (LISTEN)`, and no outbound connections |
| Browser-side requests | Only same-origin `/api/...` calls to the local server | Every `fetch` / `api()` call reviewed; at runtime, headless Chrome recorded every request while loading the board, a card's detail panel (with prompt preview) and the HUD: **0 non-local requests** |
| CDNs, web fonts, external scripts or images | **None.** System fonts; icons are inline SVG; favicon is a `data:` URI; sounds are synthesized with Web Audio (no audio files) | Scan of `index.html` for absolute URLs, `<script src>`, `<link href>`, `@import`, `url(` |
| Telemetry, analytics, update checks, crash reporting | **None** | No such code or dependency exists |
| Data storage | Local files only: `.agentboard/tasks.json`, `.agentboard/config.toml`, `.agentboard/.lock` in your project. The browser also keeps 3 UI preferences in `localStorage` (`agentboard-theme`, `agentboard-snd`, `agentboard-amb`). Nothing is synced anywhere | `store.py`, `prompt.py`, `index.html` |
| Cross-site access to the local server | Requests with a foreign `Host` header are rejected (blocks DNS rebinding), as are POSTs with a foreign `Origin` header or a non-JSON content type | `server.py` |
| Opening the browser | `agentboard serve` opens `http://localhost:<port>/` in your default browser (skip with `--no-open`) | `server.py` |

## Opt-in exceptions (off by default)

1. **`http` context provider.** If you define one in `.agentboard/config.toml`, building a prompt that
   uses it sends an HTTP GET to the URL you configured. The default config has every provider commented out.
2. **`command` context provider.** Runs a shell command you configure; that command can do anything,
   including network calls.

Providers run only when a task explicitly lists them (`--ctx`) and a prompt is built (Copy prompt,
`agentboard prompt`, `agentboard rebuild`). On a work machine, point `http` providers only at local
services, or don't configure any.

## Install-time network (not runtime)

Installing fetches files once: from GitHub if you install with `pipx install git+https://...`, and
setuptools from PyPI (the build backend) when building from source. After install, nothing is fetched again.

## Public repository

The public GitHub repo contains only the code, README and license. Task data (`.agentboard/`) is
git-ignored, has never been committed, and no personal data appears anywhere in the commit history.
Commit metadata does show the author's name and email.
