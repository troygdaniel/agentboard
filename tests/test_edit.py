"""Edit in place: a card's title, description and blockers change from the board, each logged as Troy's."""
import json
import tempfile
import unittest
from pathlib import Path

from agentboard.store import BoardError, Store

from tests.test_reports import HttpTests as _Http


class EditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Rate-limit the SMS", "One hour cap.", status="todo")
        self.s.add("Write the changelog", status="todo")

    def test_title_and_description_change_with_one_log_line_each(self):
        t = self.s.edit("rate-limit-the-sms", title="Rate-limit inbound SMS", description="One hour cap, then 403.")
        self.assertEqual((t["id"], t["title"], t["description"]), ("rate-limit-the-sms", "Rate-limit inbound SMS", "One hour cap, then 403."))
        texts = [(e["text"], e.get("by")) for e in t["log"][-2:]]
        self.assertEqual(texts, [("Title changed from “Rate-limit the SMS”", "Troy"), ("Description changed", "Troy")])
        same = self.s.edit("rate-limit-the-sms", title="Rate-limit inbound SMS")   # nothing new: no log line, no clock bump
        self.assertEqual(len(same["log"]), len(t["log"]))
        self.assertEqual(same["updated"], t["updated"])

    def test_blockers_are_set_as_a_list_and_cleared(self):
        t = self.s.edit("rate-limit-the-sms", blocked_by=["write-the-changelog", "write-the-changelog", "rate-limit-the-sms"])
        self.assertEqual(t["blocked_by"], ["write-the-changelog"])
        self.assertEqual(t["log"][-1]["text"], "Blocked by Write the changelog")
        with self.assertRaises(BoardError):
            self.s.claim("rate-limit-the-sms", "AGENT-1")
        t = self.s.edit("rate-limit-the-sms", blocked_by=[])
        self.assertNotIn("blocked_by", t)
        self.assertEqual(t["log"][-1]["text"], "No longer blocked")

    def test_refusals(self):
        with self.assertRaises(BoardError):
            self.s.edit("rate-limit-the-sms", title="   ")
        with self.assertRaises(BoardError):
            self.s.edit("rate-limit-the-sms", blocked_by=["nope"])
        with self.assertRaises(BoardError):
            self.s.edit("rate-limit-the-sms", blocked_by="write-the-changelog")
        self.s.add("Kid", status="todo", parent_id="rate-limit-the-sms")
        with self.assertRaises(BoardError):
            self.s.edit("rate-limit-the-sms", blocked_by=["kid"])
        with self.assertRaises(BoardError):
            self.s.edit("rate-limit-the-sms", description=5)

    def test_the_holder_and_column_never_change(self):
        self.s.start("Live", "AGENT-1", "green")
        t = self.s.edit("live", title="Live, renamed", description="now with words")
        self.assertEqual((t["status"], t["agent"], t["title"]), ("doing", "AGENT-1", "Live, renamed"))


class EditRouteTests(_Http):
    def test_the_route_edits_and_rejects_bad_shapes(self):
        import urllib.error
        self.s.add("Queued", status="todo")
        t = self.post("/api/edit", {"id": "queued", "title": "Queued, renamed", "description": "d"})
        self.assertEqual((t["title"], t["description"]), ("Queued, renamed", "d"))
        self.assertEqual(next(x for x in json.loads(self.get("/api/tasks")[1])["tasks"] if x["id"] == "queued")["title"], "Queued, renamed")
        for body in ({"id": "queued", "title": ""}, {"id": "nope", "title": "x"}, {"id": "queued", "blocked_by": "x"}):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/edit", body)
            self.assertEqual(e.exception.code, 400)
            e.exception.close()


if __name__ == "__main__":
    unittest.main()
