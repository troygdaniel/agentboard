"""Local HTTP server: serves the board UI and a small JSON API. Localhost only."""
import json
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import boards, hud
from . import reports, runs, summary, voice
from . import markdown as mdlib
from . import prompt as promptlib
from .store import BoardError, Store, subtask_counts, subtask_list

STATIC = Path(__file__).parent / "static"
BOARD_PATH = re.compile(r"^/b/([a-z0-9][a-z0-9_-]{0,39})(/.*)?$")
MAX_BODY = 1_000_000


def _ids(body):
    ids = body["ids"]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise BoardError("ids must be a list of task ids")
    return ids


# report pages carry their own inline script and style, talk only to this server, and load nothing else
REPORT_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'",
                  "X-Content-Type-Options": "nosniff"}


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
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    self._send(415, {"error": "json required"})
                    return False
            return True

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

        def _route_get(self, url, q):
            if url.path in ("/", "/index.html", "/hud"):
                html = (STATIC / "index.html").read_text()
                inject = f"<script>window.AB_BASE = {json.dumps(self.base)};</script><script src=\"{self.base}/voice.js\" defer></script>"   # the page prefixes its /api calls with this
                self._send(200, html.replace("</head>", inject + "</head>", 1).encode(), "text/html; charset=utf-8")
            elif url.path == "/voice.js":
                self._send(200, (STATIC / "voice.js").read_bytes(), "text/javascript; charset=utf-8")
            elif url.path == "/api/voice":
                self._send(200, voice.status(self.store.dir))
            elif url.path in ("/summary", "/summary/"):
                try:
                    data = summary.build(self.store, (q.get("since") or [summary.DEFAULT_SINCE])[0], (q.get("project") or [None])[0])
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
                self._send(200, {"tasks": slim})
            elif url.path == "/api/projects":
                self._send(200, {"projects": self.store.load_projects()})
            elif url.path == "/api/hud":
                conf = _config(self.store)
                data = hud.build(self.store.load(), abandoned_min=hud.stale_minutes(conf), retired=hud.retired(conf), roster=hud.roster(conf))
                data["backup"] = self.store.backups.status()   # {last_backup_min, snapshots, last_sync, sync_dir}: the HUD's "backup N min ago" chip
                self._send(200, data)
            elif url.path == "/api/config":
                conf = _config(self.store)
                self._send(200, {"dispatch": bool(conf.get("ui", {}).get("dispatch", True)),
                                  "stale_minutes": hud.stale_minutes(conf)})
            elif url.path == "/api/task":
                try:
                    t = dict(Store.get(self.store.load(), (q.get("id") or [""])[0]))
                    if t.get("body_md"):
                        # rendered here, not stored: agent text is untrusted, and to_html()
                        # never passes raw HTML through, so the client can insert it as-is
                        t["body_html"] = mdlib.to_html(t["body_md"])
                    self._send(200, t)
                except BoardError as e:
                    self._send(404, {"error": str(e)})
            elif url.path == "/api/chat":
                after = q.get("after", [None])[0]
                after = int(after) if after and after.lstrip("-").isdigit() else None
                self._send(200, {"messages": self.store.chat_list(after=after, limit=200)})
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
                                  project_id=body.get("project_id"), parent_id=body.get("parent_id"))
                    self._send(200, t)
                elif path == "/api/projects":
                    p = self.store.add_project(body["name"], body.get("color"), body.get("description", ""))
                    self._send(200, p)
                elif path == "/api/project-update":
                    p = self.store.update_project(body["id"], body.get("name"), body.get("color"), body.get("description"))
                    self._send(200, p)
                elif path == "/api/project-delete":
                    self.store.delete_project(body["id"])
                    self._send(200, {"ok": True})
                elif path == "/api/task-project":
                    t = self.store.set_project(body["id"], body.get("project_id"))
                    self._send(200, t)
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
                elif path == "/api/bulk-project":
                    prev = self.store.bulk_set_project(_ids(body), body.get("project_id"))
                    self._send(200, {"prev": prev})
                elif path == "/api/clear-done":
                    self._send(200, {"ids": self.store.clear_done()})
                elif path == "/api/unarchive":
                    self.store.unarchive(_ids(body))
                    self._send(200, {"ok": True})
                elif path == "/api/color":
                    self._send(200, self.store.set_agent_color(body["id"], body["color"]))
                elif path == "/api/send-back":
                    self._send(200, self.store.send_back(body["id"], body["text"]))
                elif path == "/api/run-kill":
                    self._send(200, {"result": runs.kill_run(self.store.dir, body["id"])})
                elif path == "/api/delete":
                    self.store.delete(body["id"])
                    self._send(200, {"ok": True})
                elif path == "/api/reply":
                    if not isinstance(body["text"], str):
                        raise BoardError("text must be a string")
                    self._send(200, self.store.reply(body["id"], body["text"]))
                elif path == "/api/chat":
                    # the only HTTP poster is the board UI (agents use the CLI), so it's always "you"
                    sender = body.get("sender") or "Troy"
                    if not isinstance(sender, str) or not isinstance(body["text"], str):
                        raise BoardError("sender and text must be strings")
                    m = self.store.chat_send(sender, body["text"], "user")
                    self._send(200, m)
                else:
                    self._send(404, {"error": "not found"})
            except (BoardError, KeyError, ValueError, TypeError, AttributeError) as e:   # bad shapes are the client's mistake: 400, never a dropped connection
                self._send(400, {"error": str(e) or e.__class__.__name__})

    return Handler


def serve(store, port=8765, open_browser=True):
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
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
