"""`agentboard rm --demo` removes the sample cards that were cleared to archive.json too (retest after the night sweep, 15 Nov).

Since 8d9be7c a cleared card moves out of tasks.json into archive.json. `rm --demo` read only the live board, so after `agentboard clear` the
done sample card (demo-ci and its two steps) stayed in the archive for good: every later `rm --demo` left three demo- cards behind, and a new
`agentboard demo` could not seed demo-ci again (an archived id is never reused), so the Done column's sample was missing. Throwaway board only."""
import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, demo
from agentboard.store import Store


class RmDemoClearsTheArchiveToo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.s = Store(Path(self.tmp) / ".agentboard")
        demo.seed(self.s)
        self.s.clear_done()                                   # demo-ci and its two steps move to archive.json
        self.assertEqual(sorted(t["id"] for t in self.s.load_archived()), ["demo-ci", "demo-ci-jobs", "demo-ci-run"])

    def rm_demo(self):
        out = io.StringIO()
        with mock.patch.object(cli, "_store", return_value=self.s), mock.patch.dict(os.environ, {"AGENTBOARD_NAME": ""}), contextlib.redirect_stdout(out):
            cli.cmd_rm(argparse.Namespace(id=None, demo=True))
        return out.getvalue()

    def test_rm_demo_leaves_no_sample_card_live_or_archived(self):
        out = self.rm_demo()
        self.assertEqual([t["id"] for t in self.s.load_all() if t["id"].startswith("demo-")], [])
        self.assertEqual(self.s.load_archived(), [])
        self.assertIn("removed 12 task(s)", out)             # the nine live ones and the three archived

    def test_a_new_seed_after_it_is_whole_again(self):
        self.rm_demo()
        self.assertEqual(demo.seed(self.s), 12)
        live = {t["id"]: t for t in self.s.load()}
        self.assertEqual(live["demo-ci"]["status"], "done", "the Done column's sample card is back on the board")
        self.assertEqual(len(live), 12)

    def test_other_archived_cards_are_left_alone(self):
        self.s.add("Real work", status="todo", task_id="real")
        self.s.update("real", 100, "done", status="done")
        self.s.clear_done()
        self.rm_demo()
        self.assertEqual([t["id"] for t in self.s.load_archived()], ["real"])


if __name__ == "__main__":
    unittest.main()
