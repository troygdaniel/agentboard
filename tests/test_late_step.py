"""A step added to a card that is waiting for review takes the review back (night sweep, card sweep-func-cli).
`add "late" --parent P` on a card handed in with `review` dropped its % to 67 and left it saying "ready for review" with a step still open, and the owner read
a finished card that was not. The review (and an ORCH sign-off on it) is withdrawn, the history says why, and the step is the agent's to finish; a card that was
not in review, or a step that arrives already done, changes nothing else."""
import tempfile
import unittest
from pathlib import Path

from agentboard.store import Store


class LateStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Parent", status="todo", task_id="p")
        for sid in ("a", "b"):
            self.s.add(f"Step {sid}", parent_id="p", task_id=f"p-{sid}")
        self.s.claim("p", "AG-1")

    def card(self, cid="p"):
        return Store.get(self.s.load(), cid)

    def hand_in(self):
        for sid in ("a", "b"):
            self.s.update(f"p-{sid}", 100)
        self.s.review("p", "ready", "## Next\n- nothing", by="AG-1")

    def test_a_new_step_withdraws_the_review_and_says_why(self):
        self.hand_in()
        self.assertTrue(self.card().get("review"))
        self.s.add("Late step", parent_id="p", task_id="p-late")
        p = self.card()
        self.assertFalse(p.get("review"))
        self.assertEqual((p["status"], p["progress"]), ("doing", 67))
        self.assertIn("Back at work", p["log"][-1]["text"])
        self.assertIn("Late step", p["log"][-1]["text"])

    def test_an_orch_sign_off_on_the_withdrawn_review_goes_with_it(self):
        self.hand_in()
        self.s.signoff("p", {"merged": "abc1234", "ahead": None, "tests": [], "gate": None, "verified_by": None}, by="ORCH")
        self.assertTrue(self.card().get("signoff"))
        self.s.add("Late step", parent_id="p", task_id="p-late")
        self.assertFalse(self.card().get("signoff"))

    def test_finishing_the_late_step_lets_the_card_be_handed_in_again(self):
        self.hand_in()
        self.s.add("Late step", parent_id="p", task_id="p-late")
        self.s.update("p-late", 100)
        self.s.review("p", "ready again", "## Next\n- nothing", by="AG-1")
        p = self.card()
        self.assertTrue(p.get("review"))
        self.assertEqual(p["progress"], 100)

    def test_a_card_that_was_not_in_review_logs_nothing_extra(self):
        before = len(self.card()["log"])
        self.s.add("Another step", parent_id="p", task_id="p-c")
        p = self.card()
        self.assertEqual(len(p["log"]), before)
        self.assertFalse(p.get("review"))

    def test_a_question_waiting_on_the_owner_stays_asked(self):
        self.s.ask("p", "Which way?", None, by="AG-1")
        self.s.add("Another step", parent_id="p", task_id="p-c")
        self.assertTrue(self.card().get("needs_input"))


if __name__ == "__main__":
    unittest.main()
