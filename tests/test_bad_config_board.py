"""A typo in config.toml must not blank the board (night sweep, functional lane).

server._config already answers {} for an unreadable config.toml, "so a typo there must not blank the HUD or the board": /api/hud and /api/config stay 200.
But GET /api/tasks, the route that draws every card, asked watchdog.threshold(), which reads the config strictly, and answered 500, so the page had nothing
to draw until the file was fixed. The watchdog's stale threshold now falls back to its default on the server's board routes. Commands stay strict (`agentboard
watchdog` still says which file to fix), and the ORCH prompt, which is built from the roster in that file, still refuses with the file named."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import server, watchdog
from agentboard.store import BoardError, Store

BAD = {"not toml": b"[[[ this is not toml\nx = = =\n", "not utf-8": '[board]\nowner = "José"\n'.encode("latin-1")}


class TheBoardKeepsDrawing(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        self.s.add("A card", status="todo", task_id="a-card")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        server._DOG_CACHE.clear()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_the_cards_still_come_with_a_config_that_cannot_be_read(self):
        for label, raw in BAD.items():
            (self.s.dir / "config.toml").write_bytes(raw)
            server._DOG_CACHE.clear()
            code, body = self.get("/api/tasks")
            self.assertEqual(code, 200, label)
            self.assertIn("a-card", [t["id"] for t in json.loads(body)["tasks"]] if isinstance(json.loads(body), dict) else [t["id"] for t in json.loads(body)], label)
            for path in ("/api/hud", "/api/config"):
                self.assertEqual(self.get(path)[0], 200, f"{label} {path}")

    def test_the_orch_prompt_still_says_which_file_to_fix(self):
        (self.s.dir / "config.toml").write_bytes(BAD["not toml"])
        code, body = self.get("/api/orch-prompt")
        self.assertEqual(code, 500)
        self.assertIn("config.toml", body)
        self.assertIn("fix or delete it", body)

    def test_the_command_line_stays_strict(self):
        (self.s.dir / "config.toml").write_bytes(BAD["not toml"])
        with self.assertRaises(BoardError):
            watchdog.threshold(self.s)

    def test_a_good_config_keeps_its_threshold(self):
        (self.s.dir / "config.toml").write_text("[board]\nstale_minutes = 7\n")
        self.assertEqual(watchdog.threshold(self.s), 7)
        self.assertEqual(self.get("/api/tasks")[0], 200)


if __name__ == "__main__":
    unittest.main()
