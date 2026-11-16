"""A card with a wrong-typed field is tidied as it is read, not left to crash a dozen readers (night sweep, functional lane).

The loader refuses a file whose card has no id, a bad status or a log that is not a list, with a line saying what to run. But a card whose agent is a number, whose
log holds a number, whose description is a list, whose title is a number or whose `updated` is null (a hand edit, an older version, a bad merge) passed it and then
crashed the HUD, the summary, the report, the rollup, the prompt and the page's detail panel with a TypeError or an AttributeError. The loader now tidies those
fields in memory (a number becomes its text, a log keeps only its entries, a null time falls back to the card's creation time) and the next save writes the tidy
card. A good card is left exactly as it was; the cards the loader refuses are still refused."""
import contextlib
import copy
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, server
from agentboard.store import Store

ODD = {
    "agent is a number": {"agent": 7},
    "agent is a list": {"agent": ["a"]},
    "description is a list": {"description": ["a", "b"]},
    "title is a number": {"title": 5},
    "updated is null": {"updated": None},
    "log holds numbers and text": {"log": [1, None, "x", {"at": "2026-11-15T10:00:00", "text": "kept"}]},
}
ROUTES = ["/api/tasks", "/api/hud", "/api/task?id=odd-1", "/api/prompt?id=odd-1", "/summary", "/story", "/reports", "/api/chat", "/api/orch-prompt", "/"]
COMMANDS = [("list",), ("rollup",), ("status",), ("watchdog",), ("report",), ("summary",), ("prompt", "odd-1")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(root / "proj" / ".agentboard")
        self.s.add("Good card", status="todo", task_id="good")
        self.s.add("Odd card", status="doing", task_id="odd-1")
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)

    def put(self, change):
        d = json.loads(self.s.path.read_text())
        for t in d["tasks"]:
            if t["id"] == "odd-1":
                t.update(change)
        self.s.path.write_text(json.dumps(d))

    def odd(self):
        return next(t for t in self.s.load() if t["id"] == "odd-1")


class TheLoaderTidies(Base):
    def test_each_odd_field_comes_out_the_right_kind(self):
        for label, change in ODD.items():
            self.put(change)
            t = self.odd()
            self.assertIsInstance(t["title"], str, label)
            self.assertIsInstance(t.get("description", ""), str, label)
            self.assertTrue(t.get("agent") is None or isinstance(t["agent"], str), label)
            self.assertIsInstance(t.get("updated", ""), str, label)
            self.assertTrue(isinstance(t["log"], list) and all(isinstance(e, dict) for e in t["log"]), label)

    def test_the_next_save_writes_the_tidy_card(self):
        self.put({"agent": 7})
        self.s.claim("good", "Pat-1")   # a save
        raw = next(t for t in json.loads(self.s.path.read_text())["tasks"] if t["id"] == "odd-1")
        self.assertEqual(raw["agent"], "7")

    def test_a_number_keeps_its_digits_and_a_null_time_takes_the_creation_time(self):
        self.put({"agent": 7, "title": 5, "updated": None})
        t = self.odd()
        self.assertEqual((t["agent"], t["title"]), ("7", "5"))
        self.assertEqual(t["updated"], t["created"])

    def test_the_log_keeps_only_its_entries(self):
        self.put({"log": [1, None, "x", {"at": "2026-11-15T10:00:00", "text": "kept"}, ["a"]]})
        self.assertEqual([e["text"] for e in self.odd()["log"]], ["kept"])

    def test_a_good_board_is_read_exactly_as_it_is(self):
        raw = json.loads(self.s.path.read_text())["tasks"]
        self.assertEqual(self.s.load(), raw)

    def test_a_card_the_loader_refuses_is_still_refused(self):
        self.put({"status": "weird"})
        from agentboard.store import BoardError
        with self.assertRaises(BoardError):
            self.s.load()


class EveryReaderCopes(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                cli.main(list(argv))
            except SystemExit:
                pass   # a clear refusal is fine; a traceback is not

    def test_no_route_answers_500_and_no_command_raises(self):
        for label, change in ODD.items():
            self.put(change)
            server._DOG_CACHE.clear()
            for path in ROUTES:
                self.assertLess(self.get(path), 500, f"{label}: GET {path}")
            for argv in COMMANDS:
                try:
                    self.run_cli(*argv)
                except Exception as e:   # noqa: BLE001 - any raw exception is the bug
                    self.fail(f"{label}: agentboard {' '.join(argv)} raised {e.__class__.__name__}: {e}")


if __name__ == "__main__":
    unittest.main()
