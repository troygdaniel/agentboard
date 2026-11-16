"""The board never writes a state its own loader refuses, and Undo takes only a card it can read (night sweep, functional lane).

POST /api/restore (the page's Undo) puts back a whole card the client sends. It checked the status only, so a card with a number for an id, or no id, was
written with a 200 and then EVERY read of the board answered 500 ("card 104 has no id; run agentboard verify") until someone repaired tasks.json by hand.
Two guards now: _write checks the cards exactly as the loader does before it saves (so no path can write what _read refuses), and restore checks the shape of
the card and of each subtask it is given."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import server
from agentboard.store import BoardError, Store

CARD = {"id": "restored-x", "title": "restored", "description": "", "status": "todo", "progress": 0, "status_text": "", "ctx": [], "prompt": "",
        "created": "2026-11-15T20:00:00", "updated": "2026-11-15T20:00:00", "log": []}


def card(**change):
    return {**CARD, **change}


class TheStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        self.s.add("Existing", status="todo", task_id="existing")
        self.before = self.s.path.read_text()

    def assert_refused_and_unchanged(self, snapshot, kids=None, msg=""):
        with self.assertRaises(BoardError, msg=msg):
            self.s.restore(snapshot, None, kids)
        self.assertEqual(self.s.path.read_text(), self.before, f"{msg}: the file changed")
        self.s.load()   # and the board still reads

    def test_a_card_with_a_bad_id_is_refused_and_nothing_is_written(self):
        for ident in (12, None, "", "   ", ["a"]):
            self.assert_refused_and_unchanged(card(id=ident), msg=f"id {ident!r}")

    def test_a_card_with_the_wrong_kind_of_field_is_refused(self):
        for change in (dict(title=5), dict(title=None), dict(agent=7), dict(log="oops"), dict(log=[1]), dict(progress="abc"), dict(progress=500), dict(progress=True),
                       dict(description=["a"]), dict(status="weird")):
            self.assert_refused_and_unchanged(card(**change), msg=str(change))

    def test_a_bad_subtask_refuses_the_whole_undo_and_leaves_the_parent_where_it_was(self):
        self.assert_refused_and_unchanged(card(), kids=[card(id="kid", title=9)], msg="kid with a number for a title")
        self.assert_refused_and_unchanged(card(), kids=["not a card"], msg="kid that is text")

    def test_a_good_card_and_its_subtasks_are_put_back(self):
        t = self.s.add("Parent", status="todo", task_id="parent")
        k = self.s.add("Kid", parent_id="parent", task_id="kid")
        snap_p, snap_k = dict(t), dict(k)
        self.s.delete("parent")
        self.assertNotIn("parent", [x["id"] for x in self.s.load()])
        self.s.restore(snap_p, None, [snap_k])
        self.assertEqual(sorted(x["id"] for x in self.s.load()), ["existing", "kid", "parent"])

    def test_no_write_path_can_leave_a_card_the_loader_refuses(self):
        with self.assertRaises(BoardError) as e:
            with self.s.transaction() as tasks:
                tasks.append({"id": 5, "status": "todo"})
        self.assertIn("nothing was saved", str(e.exception))
        self.assertEqual(self.s.path.read_text(), self.before)
        with self.assertRaises(BoardError):
            with self.s.transaction() as tasks:
                tasks[0]["status"] = "weird"
        self.assertEqual(self.s.path.read_text(), self.before)


class ThePage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        self.s.add("Existing", status="todo", task_id="existing")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_undo_with_a_card_that_has_no_id_is_a_400_and_the_board_keeps_answering(self):
        for ident in (12, None):
            self.assertEqual(self.post("/api/restore", {"task": card(id=ident)}), 400, repr(ident))
            self.assertEqual(self.get("/api/tasks"), 200, f"after id {ident!r}")

    def test_undo_still_works_from_the_page(self):
        self.assertEqual(self.post("/api/restore", {"task": card()}), 200)
        self.assertIn("restored-x", [t["id"] for t in self.s.load()])


if __name__ == "__main__":
    unittest.main()
