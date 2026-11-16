"""A card cannot be made to wait, through others, on itself (night sweep, functional lane).

edit(blocked_by=...) refused a card waiting on its own subtask and dropped a card waiting on itself, but accepted A waits on B while B waits on A (and longer
loops). Neither card could then be claimed without --force, which agents are told never to use, and the night queue skipped both: a deadlock nobody was told
about. The edit that would close the loop is refused and says which cards."""
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import json
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import server
from agentboard.store import BoardError, Store


class Loops(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        for i in "abcd":
            self.s.add(f"Card {i}", status="todo", task_id=i)

    def blocked(self, i):
        return next(t for t in self.s.load() if t["id"] == i).get("blocked_by")

    def test_two_cards_waiting_on_each_other_are_refused(self):
        self.s.edit("b", blocked_by=["a"])
        with self.assertRaises(BoardError) as e:
            self.s.edit("a", blocked_by=["b"])
        self.assertIn("loop", str(e.exception))
        self.assertIn("a", str(e.exception))
        self.assertIsNone(self.blocked("a"))   # nothing was changed

    def test_a_longer_loop_is_refused_too(self):
        self.s.edit("b", blocked_by=["a"])
        self.s.edit("c", blocked_by=["b"])
        with self.assertRaises(BoardError):
            self.s.edit("a", blocked_by=["c"])
        self.assertIsNone(self.blocked("a"))

    def test_waiting_on_several_is_fine_and_so_is_a_diamond(self):
        self.s.edit("b", blocked_by=["d"])
        self.s.edit("c", blocked_by=["d"])
        self.s.edit("a", blocked_by=["b", "c"])   # a waits on b and c, both wait on d: no loop
        self.assertEqual(self.blocked("a"), ["b", "c"])

    def test_changing_a_wait_to_one_that_is_not_a_loop_still_works(self):
        self.s.edit("b", blocked_by=["a"])
        self.s.edit("a", blocked_by=["c"])
        self.assertEqual(self.blocked("a"), ["c"])

    def test_a_card_waiting_on_itself_is_still_dropped_quietly(self):
        self.s.edit("a", blocked_by=["a"])
        self.assertIsNone(self.blocked("a"))


class Page(unittest.TestCase):
    def test_the_page_gets_a_400_and_the_board_is_unchanged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        s = Store(Path(tmp.name) / ".agentboard")
        s.add("A", status="todo", task_id="a")
        s.add("B", status="todo", task_id="b", blocked_by=["a"])
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/edit", json.dumps({"id": "a", "blocked_by": ["b"]}).encode(), {"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 400)
        self.assertIsNone(next(t for t in s.load() if t["id"] == "a").get("blocked_by"))


if __name__ == "__main__":
    unittest.main()
