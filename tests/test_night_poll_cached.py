"""The page asks /api/night every 15 s from every open tab; the answer reads the whole board file, 25 ms at 5,000 cards, each time (sweep-perf).
It is now built once while neither the board file nor night.json has changed (and at most once in 5 s, because `on` and `ended` move with the clock).
The test counts reads of the board file, not milliseconds, so a busy Mac cannot flake it."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import night
from agentboard.server import make_handler
from agentboard.store import Store


class NightPoll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)
        self.s.add("Queued card", status="todo", task_id="q1")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def get(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/night", headers={"Host": f"localhost:{self.port}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_five_polls_read_the_board_file_once(self):
        night.turn_on(self.s, "07:00", by="ORCH")
        night.queue_add(self.s, ["q1"], by="ORCH")
        first = self.get()
        self.assertTrue(first["on"])
        self.assertEqual([r["id"] for r in first["queue"]], ["q1"])
        reads = []
        real = Store.load

        def counting(store, *a, **k):
            reads.append(1)
            return real(store, *a, **k)
        with mock.patch.object(Store, "load", counting):
            answers = [self.get() for _ in range(5)]
        self.assertEqual(answers, [first] * 5)
        self.assertLessEqual(len(reads), 1, f"{len(reads)} reads of the board file for 5 polls with nothing changed")

    def test_a_change_to_the_queue_or_the_switch_shows_in_the_next_poll(self):
        self.assertEqual(self.get()["queue"], [])
        night.queue_add(self.s, ["q1"], by="ORCH")      # night.json changes, the board file does not
        self.assertEqual([r["id"] for r in self.get()["queue"]], ["q1"])
        night.turn_on(self.s, "07:00", by="ORCH")
        self.assertTrue(self.get()["on"])
        night.turn_off(self.s, by="ORCH")
        self.assertFalse(self.get()["on"])

    def test_a_card_that_stops_waiting_leaves_the_queue_in_the_next_poll(self):
        night.queue_add(self.s, ["q1"], by="ORCH")
        self.assertEqual([r["id"] for r in self.get()["queue"]], ["q1"])
        self.s.claim("q1", "atlas")                       # the board file changes, night.json does not
        self.assertEqual(self.get()["queue"], [])


if __name__ == "__main__":
    unittest.main()
