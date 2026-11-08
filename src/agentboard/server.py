"""Local HTTP server: serves the board UI and a small JSON API. Localhost only."""
import atexit
import json
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import boards, hud, private
from . import hooks as hookslib
from . import listeners, watchdog
from . import transcript as transcriptlib
from . import plugins, reports, runs, serverstate, summary, voice
from . import markdown as mdlib
from . import prompt as promptlib
from .store import BoardError, Store, subtask_counts, subtask_list

STATIC = Path(__file__).parent / "static"
BOARD_PATH = re.compile(r"^/b/([a-z0-9][a-z0-9_-]{0,39})(/.*)?$")
PLUGIN_PATH = re.compile(r"^/api/x/([a-z][a-z0-9_-]{0,30})/([a-z0-9][a-z0-9_/.-]{0,63})$")   # page.js / page.css have a dot; plugins.route matches the exact registered path
MAX_BODY = 1_000_000


_GIT_CACHE = {}


def _group_files(files):
    """Files counted by folder, at the shallowest depth that tells two groups apart (src 4 · tests 2), six groups at most."""
    for depth in (1, 2, 3):
        groups = {}
        for f in files:
            parts = f.split("/")
            key = "/".join(parts[:depth]) if len(parts) > depth else parts[-1]
            groups[key] = groups.get(key, 0) + 1
        if len(groups) >= 2 or depth == 3:
            return sorted(groups.items(), key=lambda kv: -kv[1])[:6]
    return []


def _git_summary(store, t):
    """{commits, files, groups} for a finished card, from the project's git (reports.git_info: the commits made while the card was
    open). Cached on the card's updated stamp, since git is slow and the panel polls; {} without a repo or on any error."""
    key = (str(store.dir), t["id"], t.get("updated"))
    if key not in _GIT_CACHE:
        try:
            g = reports.git_info(store.dir, t, t.get("run")) or {}
        except Exception:   # a broken repo must never break the panel
            g = {}
        if len(_GIT_CACHE) > 200:
            _GIT_CACHE.clear()
        files = [f for f in g.get("files", []) if not f.startswith(".agentboard")]   # board data is not the work
        _GIT_CACHE[key] = {"commits": len(g.get("commits", [])), "files": len(files), "groups": _group_files(files)} if g else {}
    return _GIT_CACHE[key]


def _ids(body):
    ids = body["ids"]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise BoardError("ids must be a list of task ids")
    return ids


# Every HTML page forbids being framed (clickjacking: the Host check lets a page frame localhost itself), is never sniffed into another
# type, and sends no Referer.
FRAME_HEADERS = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}

# report pages carry their own inline script and style, talk only to this server, and load nothing else
REPORT_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
                  **FRAME_HEADERS}

# The board page: its one inline script runs only with this response's nonce, so a stray attribute or tag injected into the page cannot run
# script (it has no inline event handlers), and nothing the page runs can reach another host (connect-src 'self'). It loads no images
# except its own data: icon, no frames, no workers; its styles are inline.
PAGE_CSP = ("default-src 'none'; script-src 'nonce-{nonce}' 'self'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "media-src 'self' blob:; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
_INLINE_SCRIPT = re.compile(r"<script>")


def board_list(store, base=""):
    """What the header's board switcher shows: this folder's board first, then every other registered board."""
    try:
        reg = boards.load()["boards"]
    except BoardError:
        reg = {}
    here = boards.name_for(store.dir)
    out = [{"name": here or store.dir.parent.name or "board", "url": "/", "color": (reg.get(here) or {}).get("color") if here else None, "default": True}]
    mine = store.dir.resolve()
    for name, b in sorted(reg.items()):
        if Path(b["path"]).expanduser().resolve() != mine:
            out.append({"name": name, "url": f"/b/{name}/", "color": b.get("color"), "default": False})
    return {"boards": out, "current": f"{base}/"}


def make_handler(default_store, port):
    def _config(store):
        """config.toml, or {} if it is unreadable: a typo there must not blank the HUD or the board."""
        try:
            return promptlib.load_config(store.dir)
        except BoardError:
            return {}

    allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "agentboard"
        timeout = 15   # a client that declares a body and never sends it, or stalls mid-request, is dropped: it cannot pin a thread for good

        def log_message(self, *args):
            pass

        # -- plumbing ------------------------------------------------------
        def _send(self, code, body, ctype="application/json", extra=None):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _host_ok(self):
            # blocks DNS-rebinding: only our own localhost origin may talk to us
            return self.headers.get("Host") in allowed_hosts

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > MAX_BODY:   # a negative length would make read() wait for the client to hang up
                raise BoardError("bad body length")
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise BoardError("expected a JSON object")
            return body

        def _guard(self, post=False):
            if not self._host_ok():
                self._send(403, {"error": "bad host"})
                return False
            if post:
                origin = self.headers.get("Origin")
                if origin and origin.split("://", 1)[-1] not in allowed_hosts:
                    self._send(403, {"error": "bad origin"})
                    return False
                site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                if site and site not in ("same-origin", "none"):   # a browser says where a request came from; another site's page is refused outright
                    self._send(403, {"error": "bad origin"})
                    return False
                # the media type itself, not a substring: "text/plain;charset=application/json" is a CORS-simple type a hostile page can
                # send without a preflight, so only an exact application/json (parameters allowed) counts
                media = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if media != "application/json":
                    self._send(415, {"error": "json required"})
                    return False
            return True

        def _same_site(self):
            """A browser's Sec-Fetch-Site, when present, must be same-origin (the page itself) or none (a typed address). A client that
            sends none (curl, the CLI, the tests) passes: the header is a browser's word about where a request came from, not a secret."""
            site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
            if site not in ("", "same-origin", "none"):
                return False
            origin = self.headers.get("Origin")   # an older browser says only this much; a foreign one is refused all the same
            return not origin or origin.split("://", 1)[-1] in allowed_hosts

        def _bind(self, url):
            """Pick the board for this request. `/b/<name>/...` is a registered board; everything else is the default board
            (so every existing link keeps working). Returns the url with the prefix removed, or None after answering."""
            self.store, self.base = default_store, ""
            m = BOARD_PATH.match(url.path)
            if not m:
                return url
            name, rest = m.group(1), m.group(2)
            try:
                board = boards.load()["boards"].get(name)
            except BoardError:
                board = None
            if not board:
                self._send(404, {"error": f"no board named {name}"})
                return None
            if rest is None:   # /b/name -> /b/name/
                self.send_response(301)
                self.send_header("Location", f"/b/{name}/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            self.store = Store(Path(board["path"]).expanduser())
            self.base = f"/b/{name}"
            return url._replace(path=rest)

        # -- routes --------------------------------------------------------
        def do_GET(self):
            if not self._guard():
                return
            url = urlparse(self.path)
            q = parse_qs(url.query)
            url = self._bind(url)
            if url is None:
                return
            try:
                self._route_get(url, q)
            except BoardError as e:
                self._send(500, {"error": str(e)})
            except Exception as e:   # noqa: BLE001  (a bug must answer, not drop the connection and leave the page's poll hanging; the class name only)
                self._send(500, {"error": f"server error ({e.__class__.__name__})"})

        def _route_get(self, url, q):
            if url.path in ("/", "/index.html", "/hud", "/agents"):
                html = (STATIC / "index.html").read_text()
                inject = f"<script>window.AB_BASE = {json.dumps(self.base)};</script><script src=\"{self.base}/voice.js\" defer></script>" + plugins.page_tags(self.base)   # the page prefixes its /api calls with this; plugin tags only while plugins are allowed
                nonce = secrets.token_urlsafe(18)   # new for every response; only the page's own inline scripts get it
                page = _INLINE_SCRIPT.sub(f'<script nonce="{nonce}">', html.replace("</head>", inject + "</head>", 1))
                self._send(200, page.encode(), "text/html; charset=utf-8", {**FRAME_HEADERS, "Content-Security-Policy": PAGE_CSP.format(nonce=nonce)})
            elif url.path.startswith("/api/x/"):
                self._plugin("GET", url.path, {k: v[0] for k, v in q.items()})   # a plugin's own routes and page files; 404 unless plugins are allowed
            elif url.path == "/voice.js":
                self._send(200, (STATIC / "voice.js").read_bytes(), "text/javascript; charset=utf-8", {"X-Content-Type-Options": "nosniff"})
            elif url.path == "/api/voice":
                self._send(200, voice.status(self.store.dir))
            elif url.path in ("/summary", "/summary/"):
                try:
                    data = summary.build(self.store, (q.get("since") or [summary.DEFAULT_SINCE])[0], (q.get("agent") or [None])[0])
                except BoardError as e:
                    self._send(400, {"error": str(e)})
                    return
                self._send(200, summary.build_html(data, self.base).encode(), "text/html; charset=utf-8", REPORT_HEADERS)
            elif url.path in ("/reports", "/reports/"):
                self._send(200, reports.index_html(self.store.dir, self.base).encode(), "text/html; charset=utf-8", REPORT_HEADERS)
            elif url.path.startswith("/reports/"):
                name = url.path[len("/reports/"):]
                path = reports.reports_dir(self.store.dir) / name
                if reports.NAME_RE.match(name) and path.is_file():
                    self._send(200, path.read_bytes(), "text/html; charset=utf-8", REPORT_HEADERS)
                else:
                    self._send(404, {"error": "no such report"})
            elif url.path == "/api/boards":
                self._send(200, board_list(default_store, self.base))
            elif url.path == "/api/tasks":
                # list view stays light; history, prompt and the rich body come from /api/task
                everything = self.store.load()
                counts = subtask_counts(everything)   # archived subtasks still count toward a parent's segments
                lists = subtask_list(everything)      # ...and keep their slot, in creation order
                slim = []
                for t in everything:
                    if t.get("archived"):
                        continue
                    d = {k: v for k, v in t.items() if k not in ("log", "prompt", "body_md")}
                    if t.get("body_md") and (t.get("needs_input") or t.get("review") or t.get("status") == "doing"):
                        d["details"] = t["body_md"][:4000]   # plain text behind the card's Details fold; the panel renders the full markdown
                    if isinstance(d.get("run"), dict) and d["run"].get("status") == "running":
                        d["run"] = {**d["run"], "alive": runs.pid_alive(d["run"].get("supervisor_pid"))}   # a crashed supervisor must not leave a badge up
                    if t["id"] in counts:
                        d["subs_total"], d["subs_done"] = counts[t["id"]]
                        d["subs"] = lists[t["id"]]
                    slim.append(d)
                out = {"tasks": slim}
                ps = plugins.state(self.store)   # what each allowed plugin reports for the page; no "plugins" key at all with none
                if ps:
                    out["plugins"] = ps
                self._send(200, out)
            elif url.path == "/api/hud":
                conf = _config(self.store)
                data = hud.build(self.store.load(), abandoned_min=hud.stale_minutes(conf), retired=hud.retired(conf), roster=hud.roster(conf), owner=self.store.owner)
                data["backup"] = self.store.backups.status()   # {last_backup_min, snapshots, last_sync, sync_dir}: the HUD's "backup N min ago" chip
                data["watchdog"] = watchdog.findings(self.store, stale_min=hud.stale_minutes(conf))   # the ways the board is stuck between agents, each with its fix
                self._send(200, data)
            elif url.path == "/api/config":
                conf = _config(self.store)
                colors = conf.get("agent_colors")   # [agent_colors] AGENT-1 = "#2563eb": overrides the palette slot a name gets
                self._send(200, {"dispatch": bool(conf.get("ui", {}).get("dispatch", True)), "owner": self.store.owner,
                                  "stale_minutes": hud.stale_minutes(conf),
                                  "agent_colors": {str(k): v for k, v in colors.items() if isinstance(v, str)} if isinstance(colors, dict) else {}})
            elif url.path == "/api/task":
                try:
                    t = dict(Store.get(self.store.load(), (q.get("id") or [""])[0]))
                    if t.get("body_md"):
                        # rendered here, not stored: agent text is untrusted, and to_html()
                        # never passes raw HTML through, so the client can insert it as-is
                        t["body_html"] = mdlib.to_html(t["body_md"])
                        t["sections"] = mdlib.sections(t["body_md"])   # Changed / Checked / Next / flow, for the panel's layout
                    blob = "\n".join([t.get("result") or "", t.get("body_md") or "", *[str(x.get("text", "")) for x in t.get("log", [])]])
                    t["checks"] = reports.test_totals(blob)   # "675 tests pass": the chips that say whether it passed
                    if (t.get("status") == "done" or t.get("review")) and not t.get("parent_id"):   # finished work, closed or up for review
                        t["git"] = _git_summary(self.store, t)
                    self._send(200, t)
                except BoardError as e:
                    self._send(404, {"error": str(e)})
            elif url.path == "/api/chat":
                after = q.get("after", [None])[0]
                after = int(after) if after and after.lstrip("-").isdigit() else None
                self._send(200, {"messages": self.store.chat_list(after=after, limit=200), "agents": self.store.chat_agents(),
                                 "receipts": listeners.receipts(self.store.dir)})   # who read what, who is listening: the panel's delivered / read / answered
            elif url.path == "/api/transcript":
                # the session's transcript for one agent, read only, tailed from the file its session registered on claim/start
                name = (q.get("agent") or [""])[0]
                out = transcriptlib.read(hookslib.transcript_for(self.store.dir, name), board_dir=self.store.dir) if name else {"lines": [], "missing": True, "why": "no agent named"}
                out["agent"] = name
                self._send(200, out)
            elif url.path in ("/api/orch-prompt", "/api/prompt") and not self._same_site():
                # building a prompt runs the card's context providers (a configured shell command, an http GET): a side effect. A GET is
                # reachable blind from another site (an <img> on a hostile page), so a browser that says cross-site is refused and nothing runs.
                self._send(403, {"error": "bad origin"})
            elif url.path == "/api/orch-prompt":
                text = promptlib.build_orch_prompt(self.store.load(), self.store.dir, port=port)
                self._send(200, {"prompt": text})
            elif url.path == "/api/prompt":
                try:
                    task = Store.get(self.store.load(), (q.get("id") or [""])[0])
                    text, warnings = promptlib.build_prompt(task, self.store.dir, public=False, tasks=self.store.load())
                    self._send(200, {"prompt": text, "warnings": warnings})
                except BoardError as e:
                    self._send(404, {"error": str(e)})
            else:
                self._send(404, {"error": "not found"})

        def _plugin(self, method, path, data):
            """/api/x/<plugin>/<route>: only while plugins are allowed, only what that plugin registered. A plugin's BoardError message is
            shown (it is the plugin's own words for the owner); any other error reaches the client as its class name, never its message."""
            m = PLUGIN_PATH.match(path)
            hit = plugins.route(method, m.group(1), m.group(2)) if m else None
            if hit is None:
                self._send(404, {"error": "not found"})
            elif hit[0] == "asset":
                self._send(200, hit[1][1].encode(), hit[1][0], {"X-Content-Type-Options": "nosniff"})
            elif method == "GET" and not self._same_site():
                # a GET route is reachable blind from another site (an <img>, a no-cors fetch): the Host is the real one and a simple GET
                # carries no Origin. A browser that says cross-site or same-site is refused before the plugin runs; curl and the CLI send nothing
                self._send(403, {"error": "bad origin"})
            else:
                try:
                    out = hit[1](self.store, data)
                except BoardError as e:
                    self._send(400, {"error": str(e)})
                    return
                except Exception as e:   # noqa: BLE001
                    self._send(500, {"error": e.__class__.__name__})
                    return
                if isinstance(out, dict):
                    self._send(200, out)
                else:
                    self._send(500, {"error": "bad reply"})   # a plugin route answers with a dict

        def do_POST(self):
            if not self._guard(post=True):
                return
            try:
                body = self._json_body()
                bound = self._bind(urlparse(self.path))
                if bound is None:
                    return
                path = bound.path
                if path == "/api/transcribe":
                    self._send(200, {"text": voice.transcribe_b64(body.get("audio"), self.store.dir)})
                elif path == "/api/tasks":
                    t = self.store.add(body["title"], body.get("description", ""),
                                  body.get("status"), body.get("ctx", []),
                                  parent_id=body.get("parent_id"))
                    self._send(200, t)
                elif path == "/api/edit":
                    self._send(200, self.store.edit(body["id"], body.get("title"), body.get("description"), body.get("blocked_by")))
                elif path == "/api/move":
                    loaded = self.store.load()
                    prev = Store.get(loaded, body["id"])
                    prev_kids = [k for k in loaded if k.get("parent_id") == body["id"]]   # a move cascades onto them
                    prev_before = self.store.next_sibling(body["id"])
                    moved = self.store.move(body["id"], body["status"], body.get("before"))
                    self._send(200, {"task": moved, "prev": prev, "prev_before": prev_before, "prev_kids": prev_kids})
                elif path == "/api/restore":
                    self._send(200, self.store.restore(body["task"], body.get("before"), body.get("kids")))
                elif path == "/api/bulk-move":
                    ids = _ids(body)
                    loaded = self.store.load()
                    prev = [{"task": Store.get(loaded, i), "before": self.store.next_sibling(i),
                             "kids": [k for k in loaded if k.get("parent_id") == i]} for i in ids]
                    moved = self.store.bulk_move(ids, body["status"])
                    self._send(200, {"tasks": moved, "prev": prev})
                elif path == "/api/bulk-archive":
                    self._send(200, {"ids": self.store.bulk_archive(_ids(body))})
                elif path == "/api/clear-done":
                    self._send(200, {"ids": self.store.clear_done()})
                elif path == "/api/unarchive":
                    self.store.unarchive(_ids(body))
                    self._send(200, {"ok": True})
                elif path == "/api/send-back":
                    self._send(200, self.store.send_back(body["id"], body["text"]))
                elif path == "/api/watchdog-fix":   # one click on the HUD: one named fix (watchdog.heal), one history line
                    self._send(200, {"touched": watchdog.heal(self.store, str(body.get("action", "")), str(body.get("id", "")))})
                elif path == "/api/run-kill":
                    self._send(200, {"result": runs.kill_run(self.store.dir, body["id"])})
                elif path == "/api/delete":
                    loaded = self.store.load()
                    prev = Store.get(loaded, body["id"])
                    prev_kids = [k for k in loaded if k.get("parent_id") == body["id"]]   # a parent takes its subtasks with it
                    prev_before = self.store.next_sibling(body["id"])
                    self.store.delete(body["id"])
                    self._send(200, {"ok": True, "prev": prev, "prev_before": prev_before, "prev_kids": prev_kids})
                elif path == "/api/reply":
                    if not isinstance(body["text"], str):
                        raise BoardError("text must be a string")
                    self._send(200, self.store.reply(body["id"], body["text"]))
                elif path == "/api/chat":
                    # the only HTTP poster is the board UI (agents use the CLI), so it's always the owner
                    sender = body.get("sender") or self.store.owner
                    if not isinstance(sender, str) or not isinstance(body["text"], str):
                        raise BoardError("sender and text must be strings")
                    text, to = body["text"], body.get("to")
                    at = re.match(r"^@([\w-]+)\s+(.+)$", text.strip(), re.S)   # "@AGENT-2 can you…" addresses that agent
                    if at and not to:
                        to, text = at.group(1), at.group(2)
                    m = self.store.chat_send(sender, text, "user", to=to if isinstance(to, str) else None,
                                             reply_to=body.get("reply_to") if isinstance(body.get("reply_to"), int) else None)
                    self._send(200, m)
                elif path == "/api/chat-agents":
                    self._send(200, {"agents": self.store.set_chat_agents(bool(body.get("on")))})
                elif path == "/api/chat-decide":
                    self._send(200, self.store.chat_decide(body["seq"], body["decision"]))
                elif path == "/api/chat-nudge":
                    # the owner's one click on an unread line: the board asks ORCH to message that agent's session
                    m = self.store.chat_nudge(body["seq"])
                    self._send(200, {"message": m, "orch_listening": listeners.is_listening(self.store.dir, "ORCH")})
                elif path.startswith("/api/x/"):
                    self._plugin("POST", path, body)   # a plugin's own route; 404 unless plugins are allowed
                else:
                    self._send(404, {"error": "not found"})
            except (BoardError, KeyError, ValueError, TypeError, AttributeError) as e:   # bad shapes are the client's mistake: 400, never a dropped connection
                self._send(400, {"error": str(e) or e.__class__.__name__})

    return Handler


def serve(store, port=8765, open_browser=True):
    private.tighten_dir(store.dir)   # whatever an earlier version left readable by others (private.py)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, port))
    except OSError as e:
        raise SystemExit(f"agentboard: cannot listen on port {port} ({e.strerror}); "
                         f"is another board running? Try --port {port + 1}")
    url = f"http://localhost:{port}/"
    try:
        others = [n for n in boards.load()["boards"] if boards.name_for(store.dir) != n]
    except BoardError:
        others = []
    print(f"agentboard: {url}\n  board: {store.dir}" + "".join(f"\n  also: {url}b/{n}/" for n in others) + "\n  Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()

    last_sweep = [0.0]

    def _backups():   # an idle board still gets its hourly snapshot and its nightly copy: this one and every registered board, each with its own config
        while True:
            try:
                every = [store] + [Store(Path(b["path"]).expanduser()) for b in boards.load()["boards"].values()
                                   if Path(b["path"]).expanduser().resolve() != store.dir.resolve()]
            except BoardError:
                every = [store]
            for st in every:
                try:
                    st.backups.tick()
                except Exception:   # noqa: BLE001  (a backup problem never stops a board)
                    pass
            if time.time() - last_sweep[0] >= 3600:   # the ageing sweep: on start, then hourly
                last_sweep[0] = time.time()
                for st in every:
                    try:
                        reports.sweep(st.dir)
                    except Exception:   # noqa: BLE001
                        pass
            time.sleep(300)

    threading.Thread(target=_backups, daemon=True).start()

    def _autopilot():   # [chat] autopilot / casual: the board's own rounds on the cheaper model, when switched on
        from . import agentchat, hud, lockdown, runs
        tick, last_auto = 20.0, 0.0
        while True:
            if lockdown.locked("claude"):   # AGENTBOARD_LOCKDOWN: the rounds do not run at all, and say nothing about it
                time.sleep(tick)
                continue
            try:
                conf = promptlib.load_config(store.dir)
                chat = conf.get("chat", {}) if isinstance(conf.get("chat"), dict) else {}
                every = float(chat.get("autopilot_every", agentchat.DEFAULT_AUTOPILOT_EVERY))
                if chat.get("casual") is True:
                    agentchat.casual_once(store, runs.claude_binary(store.dir), log=lambda m: print(f"agentboard: {m}"))
                if chat.get("autopilot") is True and store.chat_agents() and time.time() - last_auto >= max(30.0, every):
                    last_auto = time.time()
                    agentchat.autopilot_once(store, runs.claude_binary(store.dir), hud.roster(conf), log=lambda m: print(f"agentboard: {m}"))
            except Exception as e:   # noqa: BLE001  (a draft problem never stops a board)
                print(f"agentboard: chat rounds: {e}")
            time.sleep(tick)

    threading.Thread(target=_autopilot, daemon=True).start()

    loaded = plugins.load()   # [] unless this machine allows plugins (AGENTBOARD_PLUGINS=1, no lock)
    if loaded:
        print("  plugins: " + ", ".join(loaded))
        plugins.start_threads(store)
    serverstate.write(store.dir, port, loaded)   # what this server was started with (lock, plugins), for agentboard doctor; never raises
    atexit.register(serverstate.remove, store.dir)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
