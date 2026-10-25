import tempfile
import unittest
from pathlib import Path

from agentboard.store import Store, twins


class TwinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_on_a_held_card_reuses_it(self):
        self.s.add("Fix the relay", status="todo", task_id="fix-relay")
        self.s.claim("fix-relay", "AGENT-1", "green")
        t, created = self.s.start_card("Fix the relay", "AGENT-1")
        self.assertFalse(created)
        self.assertEqual(t["id"], "fix-relay")
        self.assertEqual(len([x for x in self.s.load() if x["title"] == "Fix the relay"]), 1)

    def test_start_by_card_id_title_reuses_it_too(self):
        self.s.add("Fix the relay", status="todo", task_id="fix-relay")
        self.s.claim("fix-relay", "AGENT-1")
        t, created = self.s.start_card("fix-relay", "AGENT-1")
        self.assertFalse(created)
        self.assertEqual(t["id"], "fix-relay")

    def test_claim_on_a_held_card_is_a_no_op(self):
        self.s.add("A", status="todo")
        first = self.s.claim("a", "AGENT-2", "green")
        n = len(first["log"])
        again = self.s.claim("a", "AGENT-2")
        self.assertEqual(again["agent"], "AGENT-2")
        self.assertEqual(len(again["log"]), n)

    def test_dedupe_finds_and_merges_a_twin(self):
        self.s.add("Fix the relay", status="todo", task_id="fix-relay")
        self.s.claim("fix-relay", "AGENT-1")
        # an old-style twin, as a second `start` used to make it
        self.s.add("Fix the relay", status="todo", task_id="fix-relay-2")
        self.s.claim("fix-relay-2", "AGENT-1")
        self.assertEqual([(k["id"], t["id"]) for k, t in twins(self.s.load())], [("fix-relay", "fix-relay-2")])
        plan = self.s.dedupe(apply=False)
        self.assertEqual(plan, [("fix-relay", "fix-relay-2")])
        self.assertTrue(any(t["id"] == "fix-relay-2" for t in self.s.load()))  # dry run changes nothing
        self.s.dedupe(apply=True)
        ids = [t["id"] for t in self.s.load()]
        self.assertIn("fix-relay", ids)
        self.assertNotIn("fix-relay-2", ids)


if __name__ == "__main__":
    unittest.main()
