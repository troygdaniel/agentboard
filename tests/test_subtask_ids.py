"""ux-subtask-ids-collide-across-agents-ste: when a subtask's name is already a card id on the board, its id becomes its parent's id plus
its own (task-for-bea-step-one) instead of step-one-2, so the id says which card the step belongs to. A step whose name is free keeps the
short id, as every existing board and test expects."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import BoardError, Store


class SubtaskIds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)})
        p.start()
        self.addCleanup(p.stop)

    def test_step_one_under_two_cards_is_two_ids_that_name_their_card(self):
        a = self.s.start("Task for Atlas", "atlas")
        b = self.s.start("Task for Bea", "bea")
        one = self.s.add("Step one", parent_id=a["id"])
        two = self.s.add("Step one", parent_id=b["id"])
        self.assertEqual((one["id"], two["id"]), ("step-one", "task-for-bea-step-one"))   # the first keeps the short id; the second says whose it is
        again = self.s.add("Step one", parent_id=a["id"])   # the same step twice under one card: its card's name, then the usual -2
        self.assertEqual(again["id"], "task-for-atlas-step-one")
        self.assertEqual(self.s.add("Step one", parent_id=a["id"])["id"], "task-for-atlas-step-one-2")
        self.assertEqual([t["parent_id"] for t in self.s.load() if t.get("parent_id")], [a["id"], b["id"], a["id"], a["id"]])

    def test_a_top_level_card_and_an_explicit_id_are_unchanged(self):
        self.assertEqual(self.s.add("Step one")["id"], "step-one")
        a = self.s.start("Task for Atlas", "atlas")
        self.assertEqual(self.s.add("Step one", parent_id=a["id"], task_id="my-own-id")["id"], "my-own-id")
        with self.assertRaises(BoardError):
            self.s.add("Another", parent_id=a["id"], task_id="my-own-id")

    def test_a_long_parent_id_keeps_the_whole_step_name(self):
        self.s.add("Check the narrow view on a phone")   # the plain slug is taken by a card
        a = self.s.start("A rather long card title that runs past forty characters easily", "atlas")
        self.assertGreaterEqual(len(a["id"]), 39)   # the slug is cut at 40 and loses a trailing dash
        one = self.s.add("Check the narrow view on a phone", parent_id=a["id"])
        self.assertTrue(one["id"].startswith(a["id"] + "-check-the-narrow-view-on-a-phone"), one["id"])

    def test_the_cli_prints_the_prefixed_id_and_claim_takes_it_along(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["add", "Parent card", "--status", "todo"])
            cli.main(["add", "Step one", "--status", "todo"])   # takes the plain slug
            cli.main(["add", "Step one", "--parent", "parent-card"])
        self.assertIn("added parent-card-step-one", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["claim", "parent-card", "--name", "atlas"])
        sub = next(t for t in self.s.load() if t["id"] == "parent-card-step-one")
        self.assertEqual((sub["status"], sub["agent"]), ("doing", "atlas"))


if __name__ == "__main__":
    unittest.main()
