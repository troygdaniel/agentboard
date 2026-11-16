"""A log line with no usable stamp is skipped, not fatal (night sweep, finding from a hud.build fuzz).

hud.build sorts an agent's recent lines by their stamp and reads `e["at"]` for the three newest. A line whose stamp is null or a number sorted against text and raised
TypeError, a line with no stamp key at all raised KeyError, and a line whose text was a number raised TypeError when the sub-card's title was put in front of it.
Any of them made /api/hud, and so the whole HUD and its feed, answer 500 for as long as the line stayed in the card. The line now counts as an empty stamp (it sorts
first and shows with no time), and the lines with good stamps come out as before."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import hud, server
from agentboard.store import Store

NOW = datetime(2026, 11, 15, 12, 0, 0)
GOOD = {"at": "2026-11-15T11:00:00", "status": "doing", "progress": 20, "text": "a good line"}
ODD = {"at is null": {"at": None, "text": "no stamp"}, "at is a number": {"at": 5, "text": "number stamp"}, "no at at all": {"text": "no key"}, "text is a number": {"at": "2026-11-15T11:30:00", "text": 3}}


class Hud(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        self.s.add("Card", status="todo", task_id="card")
        self.s.claim("card", "Pat-1")

    def put_log(self, *entries):
        d = json.loads(self.s.path.read_text())
        for t in d["tasks"]:
            if t["id"] == "card":
                t["log"] = [GOOD, *entries]
        self.s.path.write_text(json.dumps(d))

    def recent(self):
        data = hud.build(self.s.load(), now=NOW)
        return next(a for a in data["agents"] if a["name"] == "Pat-1")["recent"]

    def test_a_line_with_no_usable_stamp_does_not_stop_the_hud(self):
        for label, entry in ODD.items():
            self.put_log(entry)
            try:
                recent = self.recent()
            except (TypeError, KeyError) as e:
                self.fail(f"{label}: hud.build raised {e.__class__.__name__}: {e}")
            self.assertIn("a good line", [r["text"] for r in recent], label)
            self.assertTrue(all(isinstance(r["at"], str) and isinstance(r["text"], str) for r in recent), label)

    def test_the_good_lines_come_out_as_they_did_without_the_odd_one(self):
        self.put_log()
        clean = self.recent()
        self.put_log(ODD["at is null"])
        self.assertEqual([r for r in self.recent() if r["text"] != "no stamp"], clean)

    def test_the_page_gets_its_hud(self):
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(self.s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        for label, entry in ODD.items():
            self.put_log(entry)
            server._DOG_CACHE.clear()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hud") as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            self.assertEqual(code, 200, label)


if __name__ == "__main__":
    unittest.main()
