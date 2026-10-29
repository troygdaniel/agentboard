"""Assign from the board: a queued card gets a holder, the chat tells ORCH, /api/agents lists who is free first."""
import json
import tempfile
import unittest
from pathlib import Path

from agentboard.store import BoardError, Store

from tests.test_reports import HttpTests as _Http


class AssignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Rate-limit the SMS", status="todo")

    def test_assign_sets_the_holder_logs_it_and_tells_orch_in_chat(self):
        t = self.s.assign("rate-limit-the-sms", "AGENT-3", "purple")
        self.assertEqual((t["status"], t["agent"], t["color"]), ("todo", "AGENT-3", "purple"))
        self.assertEqual(t["log"][-1]["text"], "Assigned to AGENT-3")
        self.assertEqual(t["log"][-1]["by"], "Troy")
        msgs = self.s.chat_list()
        self.assertEqual(len(msgs), 1)
        self.assertEqual((msgs[0]["sender"], msgs[0]["kind"]), ("Troy", "user"))
        self.assertEqual(msgs[0]["text"], "ORCH: Troy assigned rate-limit-the-sms to AGENT-3; hand it over.")

    def test_the_agent_then_claims_it_as_usual(self):
        self.s.assign("rate-limit-the-sms", "AGENT-3")
        t = self.s.claim("rate-limit-the-sms", "AGENT-3", "purple")
        self.assertEqual((t["status"], t["agent"]), ("doing", "AGENT-3"))

    def test_unassign_clears_the_holder_and_says_so(self):
        self.s.assign("rate-limit-the-sms", "AGENT-3")
        t = self.s.assign("rate-limit-the-sms", None)
        self.assertNotIn("agent", t)
        self.assertEqual(t["log"][-1]["text"], "Assignment removed")
        self.assertIn("took rate-limit-the-sms back from AGENT-3", self.s.chat_list()[-1]["text"])

    def test_assigning_the_same_agent_again_is_a_no_op(self):
        self.s.assign("rate-limit-the-sms", "AGENT-3")
        self.s.assign("rate-limit-the-sms", "AGENT-3")
        self.assertEqual(len(self.s.chat_list()), 1)
        self.assertEqual(sum(1 for e in Store.get(self.s.load(), "rate-limit-the-sms")["log"] if e["text"].startswith("Assigned")), 1)

    def test_only_queued_top_level_cards(self):
        self.s.start("Live card", "AGENT-1")
        with self.assertRaises(BoardError):
            self.s.assign("live-card", "AGENT-2")
        self.s.add("Kid", status="todo", parent_id="rate-limit-the-sms")
        with self.assertRaises(BoardError):
            self.s.assign("kid", "AGENT-2")
        self.s.add("Parked", status="backlog")
        self.assertEqual(self.s.assign("parked", "AGENT-2")["agent"], "AGENT-2")   # Later cards can be handed out too


class AgentsRouteTests(_Http):
    def test_agents_are_listed_idle_first_and_assign_posts_to_chat(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text('[orch]\nagents = [{name="AGENT-1"}, {name="AGENT-2"}, {name="AGENT-3"}]\n')
        self.s.start("Busy work", "AGENT-1", "green")
        self.s.start("Old work", "AGENT-2", "blue")
        self.s.update("old-work", text="done", status="done")
        self.s.add("Queued", status="todo")
        agents = json.loads(self.get("/api/agents")[1])["agents"]
        self.assertEqual([(a["name"], a["state"]) for a in agents], [("AGENT-2", "idle"), ("AGENT-3", "idle"), ("AGENT-1", "working")])
        self.assertEqual(agents[2]["task"], "Busy work")
        self.assertEqual(agents[0]["task"], "")
        t = self.post("/api/assign", {"id": "queued", "agent": "AGENT-3"})
        self.assertEqual(t["agent"], "AGENT-3")
        self.assertIn("assigned queued to AGENT-3", json.loads(self.get("/api/chat")[1])["messages"][-1]["text"])
        self.assertEqual(next(x for x in json.loads(self.get("/api/tasks")[1])["tasks"] if x["id"] == "queued")["agent"], "AGENT-3")   # still queued, now with a holder

    def test_bad_shapes_are_a_400(self):
        import urllib.error
        self.s.add("Queued", status="todo")
        for body in ({"id": "queued", "agent": 3}, {"id": "nope", "agent": "AGENT-1"}, {"agent": "AGENT-1"}):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/assign", body)
            self.assertEqual(e.exception.code, 400)
            e.exception.close()


if __name__ == "__main__":
    unittest.main()
