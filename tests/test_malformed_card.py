"""A malformed card in tasks.json (sec2-malformed-card-bricks-board, Nov 7): a card without an id used to end every command in KeyError and
make GET /api/tasks drop the connection, so the page stopped updating. Now the read refuses with one readable line, the CLI prints it, and
the server answers 500 with it; any other bug in a GET answers 500 with its class name instead of a dead connection."""
import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, lookup, server
from agentboard.store import BoardError, Store

GOOD = {"id": "ok", "title": "fine", "status": "todo", "log": [], "created": "2026-11-07T00:00:00"}


class MalformedCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        self.store.dir.mkdir(parents=True, exist_ok=True)

    def write(self, tasks):
        self.store.path.write_text(json.dumps({"tasks": tasks, "chat": [], "chat_seq": 0}))

    def test_a_card_without_an_id_is_one_readable_refusal(self):
        self.write([GOOD, {"title": "no id here", "status": "todo"}])
        with self.assertRaises(BoardError) as cm:
            self.store.load()
        msg = str(cm.exception)
        self.assertIn("card 2 has no id", msg)
        self.assertIn("agentboard verify", msg)
        self.assertIn("restore latest", msg)

    def test_other_broken_shapes_are_named_too(self):
        for bad, words in (("not a dict", "is not an object"), ({"id": "", "status": "todo"}, "has no id"), ({"id": 7, "status": "todo"}, "has no id"),
                            ({"id": "x", "status": "flying"}, "unknown status"), ({"id": "x", "status": "todo", "log": "nope"}, "log that is not a list")):
            self.write([bad])
            with self.assertRaises(BoardError) as cm:
                self.store.load()
            self.assertIn(words, str(cm.exception), bad)
        self.store.path.write_text(json.dumps({"tasks": {"id": "x"}}))
        with self.assertRaises(BoardError):
            self.store.load()

    def test_a_good_file_and_the_odd_but_harmless_types_still_load(self):
        self.write([GOOD, {"id": "odd", "title": None, "status": "done", "result": {"a": 1}, "archived": "yes"}])
        self.assertEqual([t["id"] for t in self.store.load()], ["ok", "odd"])

    def test_the_cli_prints_the_line_instead_of_a_traceback(self):
        self.write([{"title": "no id"}])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict("os.environ", {"AGENTBOARD_DIR": str(self.store.dir)}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:   # the CLI's one-line exit, the way every BoardError ends
                cli.main(["list"])
        text = out.getvalue() + err.getvalue() + str(cm.exception)
        self.assertIn("card 1 has no id", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("KeyError", text)

    def test_lookup_gets_the_same_line(self):
        self.write([{"title": "no id"}])
        with self.assertRaises(BoardError) as cm:
            lookup.lookup(self.store, "anything")
        self.assertIn("has no id", str(cm.exception))


class ServerAnswersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        self.store.dir.mkdir(parents=True, exist_ok=True)
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store, 0))
        self.port = probe.server_address[1]
        probe.server_close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path, headers={"Host": f"localhost:{self.port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_the_page_poll_gets_a_500_with_the_line_not_a_dead_connection(self):
        self.store.path.write_text(json.dumps({"tasks": [GOOD, {"title": "no id"}]}))
        for path in ("/api/tasks", "/api/hud"):   # /api/task answers its own 404 for anything it cannot read, as before
            code, d = self.get(path)
            self.assertEqual(code, 500, path)
            self.assertIn("card 2 has no id", d["error"])

    def test_any_other_bug_in_a_get_answers_with_its_class_name(self):
        with mock.patch.object(Store, "load", side_effect=KeyError("id")):
            code, d = self.get("/api/tasks")
        self.assertEqual((code, d["error"]), (500, "server error (KeyError)"))


if __name__ == "__main__":
    unittest.main()
