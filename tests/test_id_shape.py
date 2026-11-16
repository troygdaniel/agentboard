"""A card id someone types (`add --id`, `start --id`) is a short word that is safe in a file name, a URL and a shell (night sweep, card sweep-func-cli).
`add --id "../../esc"`, `--id "a/b"`, `--id "Has Space"` and an id of 80 characters were all accepted and then reached places that build a path from the id
(reports/<id>-<stamp>.html, reports/<id>.md, runs/<id>/) and the page's #<id> links. The ids the board makes itself (a slug of the title) always fit the rule."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import BoardError, Store

BAD = ["Has Space", "a/b", "../../esc", "..", ".hidden", "-lead", "_lead", "x" * 65, "tab\tid", "new\nline", "back\\slash", "semi;colon", "q'uote", "dollar$id",
       "ünï", "a b", " lead", "trail "]
GOOD = ["retro-done-shows-worktrees", "A1", "demo-live-3", "x" * 64, "v1.2_beta", "c1-step", "2026-11-14-card", "a"]


class IdShape(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def ids(self):
        return [t["id"] for t in self.s.load()]

    def test_add_refuses_an_id_that_is_not_a_short_safe_word(self):
        for bad in BAD:
            with self.assertRaises(BoardError, msg=repr(bad)):
                self.s.add("A card", task_id=bad)
        self.assertEqual(self.ids(), [])

    def test_start_refuses_the_same_ids(self):
        for bad in BAD:
            with self.assertRaises(BoardError, msg=repr(bad)):
                self.s.start("A card", "AG-1", task_id=bad)
        self.assertEqual(self.ids(), [])

    def test_ordinary_ids_pass_and_so_does_no_id_at_all(self):
        for good in GOOD:
            self.assertEqual(self.s.add("Card " + good[:10], task_id=good)["id"], good)
        self.assertEqual(self.s.add("From the title")["id"], "from-the-title")
        self.assertEqual(self.s.add("Empty id means none", task_id="")["id"], "empty-id-means-none")
        self.assertEqual(self.s.start("A started card", "AG-1", task_id="started-one")["id"], "started-one")

    def test_the_ids_the_board_makes_itself_always_fit(self):
        tid = self.s.add("Ünïcode & punctuation!! " + "long " * 30)["id"]
        self.assertRegex(tid, r"[a-z0-9][a-z0-9-]{0,63}")
        parent = self.s.add("Parent " + "p" * 38, task_id="parent-" + "p" * 38)["id"]
        for i in range(3):
            kid = self.s.add("Same step", parent_id=parent)["id"]
            self.assertTrue(kid)

    def test_the_cli_says_what_a_card_id_is_and_adds_nothing(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop("AGENTBOARD_NAME", None)
            with self.assertRaises(SystemExit) as cm:
                cli.main(["add", "A card", "--id", "../../esc"])
        self.assertIn("letters, digits", str(cm.exception.code))
        self.assertEqual(self.ids(), [])


if __name__ == "__main__":
    unittest.main()
