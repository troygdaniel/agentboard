"""Local HTTP server: serves the board UI and a small JSON API. Localhost only."""
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import hud
from . import markdown as mdlib
from . import prompt as promptlib
from .store import BoardError, Store, subtask_counts

STATIC = Path(__file__).parent / "static"
MAX_BODY = 1_000_000


def _ids(body):
    ids = body["ids"]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise BoardError("ids must be a list of task ids")
    return ids


def make_handler(store, port):
    def _config():
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
        def _send(self, code, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
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

        # -- routes --------------------------------------------------------
        def do_GET(self):
            if not self._guard():
                return
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                self._route_get(url, q)
            except BoardError as e:
                self._send(500, {"error": str(e)})

        def _route_get(self, url, q):
            if url.path in ("/", "/index.html", "/hud"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/tasks":
                # list view stays light; history, prompt and the rich body come from /api/task
                everything = store.load()
                counts = subtask_counts(everything)   # archived subtasks still count toward a parent's segments
                slim = []
                for t in everything:
                    if t.get("archived"):
                        continue
                    d = {k: v for k, v in t.items() if k not in ("log", "prompt", "body_md")}
                    if t["id"] in counts:
                        d["subs_total"], d["subs_done"] = counts[t["id"]]
                    slim.append(d)
                self._send(200, {"tasks": slim})
            elif url.path == "/api/projects":
                self._send(200, {"projects": store.load_projects()})
            elif url.path == "/api/hud":
                self._send(200, hud.build(store.load(), abandoned_min=hud.stale_minutes(_config())))
            elif url.path == "/api/config":
                conf = _config()
                self._send(200, {"dispatch": bool(conf.get("ui", {}).get("dispatch", True)),
                                  "stale_minutes": hud.stale_minutes(conf)})
            elif url.path == "/api/task":
                try:
                    t = dict(Store.get(store.load(), (q.get("id") or [""])[0]))
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
                self._send(200, {"messages": store.chat_list(after=after, limit=200)})
            elif url.path == "/api/prompt":
                try:
                    task = Store.get(store.load(), (q.get("id") or [""])[0])
                    text, warnings = promptlib.build_prompt(task, store.dir, public=False)
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
                path = urlparse(self.path).path
                if path == "/api/tasks":
                    t = store.add(body["title"], body.get("description", ""),
                                  body.get("status"), body.get("ctx", []),
                                  project_id=body.get("project_id"), parent_id=body.get("parent_id"))
                    self._send(200, t)
                elif path == "/api/projects":
                    p = store.add_project(body["name"], body.get("color"), body.get("description", ""))
                    self._send(200, p)
                elif path == "/api/project-update":
                    p = store.update_project(body["id"], body.get("name"), body.get("color"), body.get("description"))
                    self._send(200, p)
                elif path == "/api/project-delete":
                    store.delete_project(body["id"])
                    self._send(200, {"ok": True})
                elif path == "/api/task-project":
                    t = store.set_project(body["id"], body.get("project_id"))
                    self._send(200, t)
                elif path == "/api/move":
                    loaded = store.load()
                    prev = Store.get(loaded, body["id"])
                    prev_kids = [k for k in loaded if k.get("parent_id") == body["id"]]   # a move cascades onto them
                    prev_before = store.next_sibling(body["id"])
                    moved = store.move(body["id"], body["status"], body.get("before"))
                    self._send(200, {"task": moved, "prev": prev, "prev_before": prev_before, "prev_kids": prev_kids})
                elif path == "/api/restore":
                    self._send(200, store.restore(body["task"], body.get("before"), body.get("kids")))
                elif path == "/api/bulk-move":
                    ids = _ids(body)
                    loaded = store.load()
                    prev = [{"task": Store.get(loaded, i), "before": store.next_sibling(i),
                             "kids": [k for k in loaded if k.get("parent_id") == i]} for i in ids]
                    moved = store.bulk_move(ids, body["status"])
                    self._send(200, {"tasks": moved, "prev": prev})
                elif path == "/api/bulk-archive":
                    self._send(200, {"ids": store.bulk_archive(_ids(body))})
                elif path == "/api/bulk-project":
                    prev = store.bulk_set_project(_ids(body), body.get("project_id"))
                    self._send(200, {"prev": prev})
                elif path == "/api/clear-done":
                    self._send(200, {"ids": store.clear_done()})
                elif path == "/api/unarchive":
                    store.unarchive(_ids(body))
                    self._send(200, {"ok": True})
                elif path == "/api/color":
                    self._send(200, store.set_agent_color(body["id"], body["color"]))
                elif path == "/api/delete":
                    store.delete(body["id"])
                    self._send(200, {"ok": True})
                elif path == "/api/chat":
                    # the only HTTP poster is the board UI (agents use the CLI), so it's always "you"
                    sender = body.get("sender") or "Troy"
                    if not isinstance(sender, str) or not isinstance(body["text"], str):
                        raise BoardError("sender and text must be strings")
                    m = store.chat_send(sender, body["text"], "user")
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
    print(f"agentboard: {url}\n  board: {store.dir}\n  Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
