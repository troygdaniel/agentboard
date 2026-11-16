"""`agentboard demo --live` on the seeded board (card sweep-newuser, 15 Nov).

The sample cards in progress have subtasks, as every real card does, and a parent's % is computed from them: the board refuses `update <parent> <pct>`.
The live demo picked any Doing sample card and set its %, so on the seeded board it died on its first tick with that refusal ("demo-billing: its %
is computed from its subtasks"), on every Python. It must work a card with steps through its steps, like a real agent, and review the card when the
last step closes. Runs on a throwaway board with the clock and the sleeps faked: no waiting, no notification."""
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, demo
from agentboard.store import Store


class TheLiveDemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.s = Store(Path(self.tmp) / ".agentboard")
        demo.seed(self.s)

    def run_live(self, minutes, prefer):
        """Run the loop for `minutes` fake minutes (each sleep is one); random.choice takes a card whose id is in `prefer` whenever one is offered."""
        clock = [1000.0]
        real_choice = random.choice

        def choice(seq):
            picks = [x for x in seq if isinstance(x, dict) and x.get("id") in prefer]
            return picks[0] if picks else real_choice(seq)
        random.seed(7)
        with mock.patch.object(time, "time", lambda: clock[0]), mock.patch.object(time, "sleep", lambda x: clock.__setitem__(0, clock[0] + 60)), \
                mock.patch.object(random, "choice", choice), mock.patch.object(cli, "_notify"):
            cli._demo_live(self.s, minutes)

    def by_id(self):
        return {t["id"]: t for t in self.s.load()}

    def test_a_sample_card_with_open_steps_is_worked_through_its_steps_not_its_own_percent(self):
        self.run_live(3, prefer=("demo-billing",))          # three ticks, each offered the parent first
        t = self.by_id()
        self.assertEqual(t["demo-billing"]["status"], "doing")
        self.assertGreater(t["demo-billing-invoices"]["progress"], 40, "the open step is what moved")

    def test_when_its_last_step_closes_the_card_goes_to_review_and_is_signed_off(self):
        self.run_live(40, prefer=("demo-docs", "demo-docs-routes", "demo-docs-write"))
        t = self.by_id()
        self.assertTrue(all(t[k]["status"] == "done" for k in ("demo-docs-routes", "demo-docs-write")), {k: t[k]["status"] for k in t})
        self.assertTrue(t["demo-docs"].get("review") or t["demo-docs"]["status"] == "done", t["demo-docs"])   # reviewed when the last step closed (review is a flag on a Doing card); the simulated user may have signed off since

    def test_the_whole_loop_runs_for_a_while_on_the_seeded_board(self):
        self.run_live(60, prefer=())                           # the real mix: parents, steps, new cards, asks, reviews, sign-offs
        live = [t for t in self.s.load() if t["id"].startswith("demo-live-")]
        self.assertTrue(live, "new cards were started once a seeded card was done with")
        self.assertTrue(any(t.get("review") or t["status"] == "done" for t in live), "and some were worked to the end")


if __name__ == "__main__":
    unittest.main()
