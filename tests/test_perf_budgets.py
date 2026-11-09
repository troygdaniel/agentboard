"""Performance budgets at scale (overnight-perf-scale): a 1,000-card board with 2,000 chat lines, a real server on an ephemeral port, and the
costs a normal laptop must stay under. Each budget is about three times what this Mac measured after the Nov 8 fixes, scaled by the
machine's state the way tests/timing.py does (a known-linear pass is timed first; a slow or busy machine gets a proportionally larger
limit, never a smaller one; the best of three tries counts), so a loaded laptop does not fail green code and a regression that doubles
a cost still does. The numbers behind each budget are in docs/overnight/overnight-perf-scale.md.

Why these and not "page load in a browser": the page's own cost is measured by tests/perf_bench.py --browser, which needs Chrome; the suite
keeps to what runs anywhere. The server-side costs below are what every open page pays once a second."""
import http.client
import json
import re
import socket
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import hud, server
from agentboard.store import Store
from tests import perf_bench, timing

CARDS, CHAT = 1000, 2000
# seconds on an idle laptop (measured 2026-11-08 on an M-series Mac, Python 3.14; the limit is this times the machine's factor)
BUDGET = {
    "store.load": 0.03,              # measured 7 ms: lock, parse 2 MB, check every card
    "/api/tasks cold": 0.06,         # measured ~15 ms: load + slim + dumps of 430 KB
    "/api/tasks cached": 0.01,       # measured <1 ms: the file did not change, so the bytes are the ones from last time
    "/api/tasks 304": 0.01,          # measured <1 ms: If-None-Match matched, no body
    "/api/hud cold": 0.20,           # measured ~65 ms: hud.build over 1,000 cards (was 140 ms with strptime)
    "/api/hud cached": 0.01,
    "/api/chat cold": 0.05,          # measured ~10 ms: two reads of the board file for the last 200 lines and the switch
    "/api/chat cached": 0.01,
    "store.update": 0.05,            # measured ~15 ms: a full rewrite of 2 MB, atomic, with the .bak link
    "store.claim": 0.05,
    "hud.build": 0.15,               # measured ~55 ms in-process at 1,000 cards
    "chat_list 10k": 0.08,           # measured ~25 ms: the last 200 of 10,000 lines (one read of the file)
}
SIZE_BUDGET = {"/api/tasks": 700_000, "/api/hud": 250_000, "/api/chat": 60_000}   # bytes at 1,000 cards (measured 432 KB, 148 KB with the watchdog findings the combined tree added, 39 KB)


class Scale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.board = Path(cls.tmp.name) / ".agentboard"
        cls.store = perf_bench.seed(cls.board, CARDS, CHAT)
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            cls.port = sk.getsockname()[1]
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), server.make_handler(cls.store, cls.port))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        tasks = cls.store.load()
        parents = {t.get("parent_id") for t in tasks if t.get("parent_id")}
        cls.todo = [t["id"] for t in tasks if t["status"] == "todo" and not t.get("parent_id") and t["id"] not in parents]   # childless: a parent's % is computed

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", path, headers={"Host": f"localhost:{self.port}", **(headers or {})})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body, dict(r.getheaders())

    def touch(self):
        self.store.update(self.todo[0], 0, f"touch {time.perf_counter()}")

    def check(self, name, fn, *a):
        dt, out, lim = timing.fast(fn, BUDGET[name], *a)
        self.assertLess(dt, lim, f"{name}: {dt * 1000:.0f} ms, budget {lim * 1000:.0f} ms (x{timing.factor():.1f} for this machine)")
        return out

    def test_the_store_reads_and_writes_within_budget(self):
        tasks = self.check("store.load", self.store.load)
        self.assertGreaterEqual(len(tasks), CARDS)
        self.check("store.update", self.store.update, self.todo[1], 10, "a line")
        self.check("store.claim", self.store.claim, self.todo[2], "AGENT-9")

    def test_each_polled_route_cold_cached_and_304(self):
        for path, label in (("/api/tasks", "/api/tasks"), ("/api/hud", "/api/hud"), ("/api/chat", "/api/chat")):
            with self.subTest(path):
                # A cold poll is a GET right after a write moved the file. The write (a 2 MB rewrite with an fsync) is not in the budget: the
                # figures above measured the GET alone, and a busy disk made the sum fail on its own. So each try touches first and times only
                # the GET. A retry touches again, so the bytes to compare with the cached ones are the LAST try's (timing.fast hands back the
                # first, which made a slow first request after a fresh seed look like a stale cache: seen in shuffled order on Python 3.9).
                tries, best, lim = [], float("inf"), timing.limit(BUDGET[f"{label} cold"])
                for _ in range(timing.TRIES):
                    self.touch()
                    dt, res = timing.timed(self.get, path)
                    tries.append(res)
                    best = min(best, dt)
                    if best < lim:
                        break
                    lim = timing.limit(BUDGET[f"{label} cold"], fresh=True)
                self.assertLess(best, lim, f"{label} cold: {best * 1000:.0f} ms, budget {lim * 1000:.0f} ms (x{timing.factor():.1f} for this machine)")
                code, body, hdr = tries[-1]
                self.assertEqual(code, 200)
                self.assertLess(len(body), SIZE_BUDGET[path], f"{path} is {len(body)} bytes")
                tag = hdr.get("ETag")
                self.assertTrue(tag and tag.startswith('"'), hdr)
                code2, body2, hdr2 = self.check(f"{label} cached", self.get, path)
                self.assertEqual((code2, body2 == body or path == "/api/hud"), (200, True))   # the HUD body carries the clock; the others are byte-identical
                code3, body3, _ = self.check(f"{label} 304" if path == "/api/tasks" else f"{label} cached", self.get, path, {"If-None-Match": hdr2.get("ETag")})
                self.assertEqual((code3, body3), (304, b""))

    def test_a_change_is_seen_on_the_next_poll(self):
        """The cache must never serve a stale board: a write moves the file's inode, so the very next poll rebuilds."""
        code, body, hdr = self.get("/api/tasks")
        marker = f"marker {time.perf_counter()}"
        self.store.update(self.todo[3], 0, marker)
        code2, body2, hdr2 = self.get("/api/tasks", {"If-None-Match": hdr["ETag"]})
        self.assertEqual(code2, 200)
        self.assertIn(marker, body2.decode())
        self.assertNotEqual(hdr2["ETag"], hdr["ETag"])
        code3, body3, _ = self.get("/api/chat")
        self.store.chat_send("you", "a fresh line", "user")   # the owner's line posts whatever the agents-talk switch says
        code4, body4, _ = self.get("/api/chat")
        self.assertIn("a fresh line", body4.decode())

    def test_the_hud_builds_within_budget_in_process(self):
        tasks = self.store.load()
        data = self.check("hud.build", hud.build, tasks, None, 60, 120)
        self.assertIn("agents", data)

    def test_ten_thousand_chat_lines(self):
        with tempfile.TemporaryDirectory() as d:
            s = perf_bench.seed(Path(d) / ".agentboard", 50, 10_000)
            msgs = self.check("chat_list 10k", s.chat_list)
            self.assertEqual(len(msgs), 100)   # the default limit; the page asks for 200
            self.assertEqual(len(s.chat_list(limit=200)), 200)

    def test_the_page_remembers_a_tag_only_with_the_body_it_came_with(self):
        """xr-perf-etag-stale-while-typing: a 200 that arrives while something is being typed is dropped (hold), so its tag must not be kept,
        or the next poll turns into a 304 and the board stays stale until the file changes again. The one assignment to tasksTag sits inside
        the branch that applies the body."""
        page = (Path(__file__).parents[1] / "src" / "agentboard" / "static" / "index.html").read_text()
        body = re.search(r"async function load\(\) \{(.*?)\n\}", page, re.S).group(1)
        assigns = [m.start() for m in re.finditer(r"\btasksTag = ", body)]
        self.assertEqual(len(assigns), 1, "tasksTag must be assigned in exactly one place in load()")
        hold_block = body.index("if (!hold) {")
        self.assertGreater(assigns[0], hold_block, "the tag is remembered only once the body is applied")
        self.assertIn("const tag = r.status === 304 ? tasksTag : (r.headers.get('ETag') || '')", body)

    def test_a_304_carries_the_safety_headers(self):
        code, body, hdr = self.get("/api/tasks")
        code2, body2, hdr2 = self.get("/api/tasks", {"If-None-Match": hdr["ETag"]})
        self.assertEqual((code2, body2), (304, b""))
        self.assertEqual(hdr2.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(hdr2.get("Cache-Control"), "no-store")

    def test_the_budgets_are_tied_to_the_machine(self):
        """The limit grows with the machine's factor and never shrinks below the budget."""
        for name, b in BUDGET.items():
            self.assertGreaterEqual(timing.limit(b), b, name)
        self.assertLessEqual(timing.limit(BUDGET["/api/hud cold"]), timing.CEILING_S)


if __name__ == "__main__":
    unittest.main()
