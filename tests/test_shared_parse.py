"""The server parses the board file once per version of it, not once per endpoint (sweep-perf, finding the-card-list-sends-every-finish: after each write the page's
polls of /api/tasks, /api/hud, /api/chat, /api/night and a card's detail each parsed the same 5 MB file, 21 ms apiece at 5,000 cards, and each waited for the board lock).
Only the server's GET requests share a parse (store.viewing()); the CLI and every writer still parse for themselves, and nothing a GET does may change what is shared.
The tests count parses instead of timing them, so a busy Mac cannot flake them."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import store as store_mod
from agentboard.server import make_handler
from agentboard.store import Store

ROUTES = ["/api/tasks", "/api/hud", "/api/chat", "/api/night", "/api/task?id=c3", "/api/task?id=c1", "/api/config", "/api/settings", "/api/health", "/api/boards"]


class Shared(unittest.TestCase):
    def setUp(self):
        store_mod._SHARED.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)
        for i in range(12):
            self.s.add(f"Card {i}", status="todo", task_id=f"c{i}")
        self.s.claim("c3", "atlas")
        self.s.chat_send("atlas", "a line")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": f"localhost:{self.port}"})
        return urllib.request.urlopen(req, timeout=10).read()

    def count_parses(self, fn):
        calls, real = [], Store._read

        def counting(store, *a, **k):
            calls.append(1)
            return real(store, *a, **k)
        with mock.patch.object(Store, "_read", counting):
            fn()
        return len(calls)

    def test_one_parse_after_a_write_for_every_endpoint(self):
        self.s.add("Fresh", status="todo", task_id="fresh")
        n = self.count_parses(lambda: [self.get(r) for r in ROUTES])
        self.assertLessEqual(n, 1, f"{n} parses of the board file for one round of GETs after one write")

    def test_no_parse_at_all_when_nothing_changed(self):
        [self.get(r) for r in ROUTES]
        n = self.count_parses(lambda: [self.get(r) for r in ROUTES])
        self.assertEqual(n, 0, f"{n} parses of an unchanged board file")

    def test_a_write_shows_in_the_next_get(self):
        before = json.loads(self.get("/api/tasks"))["tasks"]
        self.s.add("Fresh", status="todo", task_id="fresh")
        after = json.loads(self.get("/api/tasks"))["tasks"]
        self.assertEqual(len(after), len(before) + 1)
        self.assertIn("fresh", [t["id"] for t in after])
        self.s.chat_send("atlas", "a second line")
        self.assertEqual([m["text"] for m in json.loads(self.get("/api/chat"))["messages"]][-1], "a second line")
        self.s.update("c3", 77, "moving")
        self.assertEqual(json.loads(self.get("/api/task?id=c3"))["progress"], 77)

    def test_a_card_moved_to_the_archive_is_never_missing_in_between(self):
        self.get("/api/hud")
        self.s.update("c5", 100, "done")
        self.s.clear_done()   # the card goes to archive.json: the HUD reads both files
        hud = json.loads(self.get("/api/hud"))
        self.assertIn("events", hud)

    def test_the_gets_do_not_change_what_they_share(self):
        for _ in range(3):
            [self.get(r) for r in ROUTES]
        shared = {k[0]: v[1] for k, v in store_mod._SHARED.items()}
        self.assertIn("board", shared)
        self.assertIn("all", shared)
        fresh = Store(self.s.dir)   # what the files say, parsed again outside any GET
        self.assertEqual(json.dumps(shared["board"], sort_keys=True), json.dumps(fresh._read(), sort_keys=True), "a GET changed the parse it shares")
        self.assertEqual(json.dumps(shared["all"], sort_keys=True), json.dumps(fresh.load_all(), sort_keys=True), "a GET changed the card list it shares")

    def test_outside_a_get_every_read_is_its_own_copy(self):
        a = self.s.load()
        a.append({"id": "scribble"})
        a[0]["title"] = "scribbled"
        b = self.s.load()
        self.assertNotIn("scribble", [t["id"] for t in b])
        self.assertNotEqual(b[0]["title"], "scribbled")


if __name__ == "__main__":
    unittest.main()
