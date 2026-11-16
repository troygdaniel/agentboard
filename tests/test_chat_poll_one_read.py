"""GET /api/chat reads the board file once to build its answer, not three times (sweep-perf: the last lines, the agents switch and the names a line can
reach were three calls, each parsing the whole file, 25 ms apiece at 5,000 cards). The test counts reads of the file, so a busy Mac cannot flake it."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard.server import make_handler
from agentboard.store import Store


class ChatPoll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)
        self.s.add("A card", status="todo", task_id="c1")
        self.s.chat_send("Atlas", "first line")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def get(self, path="/api/chat"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": f"localhost:{self.port}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_one_read_of_the_board_file_to_build_the_answer(self):
        self.get()
        self.s.chat_send("Atlas", "second line")   # the file changed, so the answer is built again
        reads = []
        real = Store._read

        def counting(store, *a, **k):
            reads.append(1)
            return real(store, *a, **k)
        with mock.patch.object(Store, "_read", counting):
            body = self.get()
        self.assertEqual([m["text"] for m in body["messages"]], ["first line", "second line"])
        self.assertLessEqual(len(reads), 1, f"{len(reads)} reads of the board file to build one /api/chat answer")

    def test_the_answer_has_the_same_parts_as_before(self):
        body = self.get()
        self.assertEqual(set(body), {"messages", "agents", "receipts", "retired", "names"})
        self.assertIs(body["agents"], self.s.chat_agents())
        self.assertEqual(body["names"], self.s.known_names())
        self.assertEqual(body["messages"], self.s.chat_list(after=None, limit=200))

    def test_the_view_matches_the_three_calls_it_replaces(self):
        for after in (None, 0, 1):
            msgs, agents, names = self.s.chat_view(after=after, limit=200)
            self.assertEqual(msgs, self.s.chat_list(after=after, limit=200))
            self.assertEqual(agents, self.s.chat_agents())
            self.assertEqual(names, self.s.known_names())


if __name__ == "__main__":
    unittest.main()
