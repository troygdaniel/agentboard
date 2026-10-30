"""Hand to…: a live card goes to another agent from the board; the chat tells ORCH."""
import json
import tempfile
import unittest
from pathlib import Path

from agentboard.store import BoardError, Store

from tests.test_reports import HttpTests as _Http


class HandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.start("Backfill audit log", "AGENT-4", "orange")
        self.s.update("backfill-audit-log", 70, "half the rows migrated")

    def test_a_live_card_goes_to_the_top_of_todo_under_the_new_agent(self):
        self.s.add("Older queued", status="todo")
        t = self.s.hand_to("backfill-audit-log", "AGENT-5", "teal")
        self.assertEqual((t["status"], t["agent"], t["color"], t["progress"]), ("todo", "AGENT-5", "teal", 70))
        self.assertEqual(t["log"][-1]["text"], "Handed from AGENT-4 to AGENT-5")
        self.assertEqual(t["log"][-1]["by"], "Troy")
        self.assertEqual([x["id"] for x in self.s.load() if x["status"] == "todo"], ["backfill-audit-log", "older-queued"])
        self.assertEqual(self.s.chat_list()[-1]["text"], "ORCH: Troy handed backfill-audit-log from AGENT-4 to AGENT-5; hand it over.")
        c = self.s.claim("backfill-audit-log", "AGENT-5")
        self.assertEqual((c["status"], c["agent"]), ("doing", "AGENT-5"))

    def test_an_ask_clears_and_the_subtasks_follow(self):
        self.s.add("Kid one", status="doing", parent_id="backfill-audit-log")
        self.s.ask("backfill-audit-log", "Which table first?")
        self.s.reply("backfill-audit-log", "users")
        t = self.s.hand_to("backfill-audit-log", "AGENT-5")
        for f in ("needs_input", "question", "reply", "review"):
            self.assertNotIn(f, t)
        kid = Store.get(self.s.load(), "kid-one")
        self.assertEqual(kid["status"], "todo")
        self.assertNotIn("agent", kid)   # the new agent's claim takes it

    def test_review_progress_is_capped_so_the_card_reads_as_open_again(self):
        self.s.review("backfill-audit-log", "done, please check")
        t = self.s.hand_to("backfill-audit-log", "AGENT-5")
        self.assertEqual(t["progress"], 95)
        self.assertNotIn("review", t)

    def test_a_queued_card_is_simply_assigned(self):
        self.s.add("Queued", status="todo")
        t = self.s.hand_to("queued", "AGENT-5")
        self.assertEqual((t["status"], t["agent"]), ("todo", "AGENT-5"))
        self.assertIn("assigned queued to AGENT-5", self.s.chat_list()[-1]["text"])

    def test_refusals(self):
        with self.assertRaises(BoardError):
            self.s.hand_to("backfill-audit-log", "AGENT-4")      # already theirs
        with self.assertRaises(BoardError):
            self.s.hand_to("backfill-audit-log", "")
        self.s.add("Kid", status="doing", parent_id="backfill-audit-log")
        with self.assertRaises(BoardError):
            self.s.hand_to("kid", "AGENT-5")
        self.s.update("backfill-audit-log", text="done", status="done")
        with self.assertRaises(BoardError):
            self.s.hand_to("backfill-audit-log", "AGENT-5")


class HandRouteTests(_Http):
    def test_the_route_hands_over_and_rejects_bad_shapes(self):
        import urllib.error
        self.s.start("Live", "AGENT-1")
        t = self.post("/api/hand", {"id": "live", "agent": "AGENT-2"})
        self.assertEqual((t["status"], t["agent"]), ("todo", "AGENT-2"))
        self.assertIn("handed live from AGENT-1 to AGENT-2", json.loads(self.get("/api/chat")[1])["messages"][-1]["text"])
        for body in ({"id": "live", "agent": 2}, {"id": "live"}, {"id": "nope", "agent": "AGENT-2"}):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/hand", body)
            self.assertEqual(e.exception.code, 400)
            e.exception.close()


if __name__ == "__main__":
    unittest.main()
