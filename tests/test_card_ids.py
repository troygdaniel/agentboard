"""A card id is a plain word: letters, digits, - and _ (night sweep, lane sweep-sec-cli).

`add --id` and `start --id` took any string. The id is pasted into file paths (reports/<id>-<stamp>.html, reports/<id>.md, runs/<id>/<run>/, the
run's worktree) and into the commands a card prompt tells an agent to run (`agentboard claim <id> ...`). An id such as `../../x` reached outside the
board folder, and one with `;` or `$(` put shell text into those commands. New ids are checked where a card is made; the readers and writers that
build a path refuse an id that is not a plain word, so a card made by an older version or a hand-edited file cannot do it either."""
import tempfile
import unittest
from pathlib import Path

from agentboard import reports, runs
from agentboard.store import BoardError, Store, safe_id

BAD = ["../../evil", "a/b", "..", ".", "a b", "x;y", "a$(id)", "a\nb", "-rf", "a`b", "a|b", "", "x" * 65, "é", ".hidden"]
GOOD = ["a", "space-game-u-b5-systems-8", "UPPER_and-lower-9", "0day", "v1.2"]


class NewIds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def test_a_plain_word_is_accepted(self):
        for i in GOOD:
            self.assertTrue(safe_id(i), i)
            self.assertEqual(self.s.add("A card", status="todo", task_id=i)["id"], i)

    def test_anything_else_is_refused_by_add_and_start_and_nothing_is_made(self):
        for i in BAD:
            self.assertFalse(safe_id(i), repr(i))
            if not i:
                continue   # no id given: the board makes one from the title
            with self.assertRaises(BoardError, msg=repr(i)):
                self.s.add("A card", status="todo", task_id=i)
            with self.assertRaises(BoardError, msg=repr(i)):
                self.s.start("A card", "AGENT-1", task_id=i)
        self.assertEqual(self.s.load(), [])

    def test_the_id_the_board_makes_from_a_title_is_always_a_plain_word(self):
        for title in ("../../evil; $(id)", "ÜBER   weird!!! title", "--help", "日本語"):
            self.assertTrue(safe_id(self.s.add(title, status="todo")["id"]), title)


class OldIdsCannotReachOutside(unittest.TestCase):
    """A card that already has such an id (an older version, a hand-edited tasks.json): nothing builds a path from it."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = Store(self.root / ".agentboard")
        self.s.add("A card", status="todo", task_id="ok")
        with self.s.transaction() as tasks:   # the way an older version, or a hand edit, left one behind
            tasks[0]["id"] = "../../evil"

    def test_no_report_is_written_outside_the_reports_folder(self):
        (self.s.dir / "reports").mkdir(parents=True, exist_ok=True)
        (self.s.dir / "reports" / "...").mkdir()   # the folder name the temp file's path happened to need: it must not be what stops this
        with self.assertRaises(BoardError):
            reports.write_report(self.s, "../../evil")
        self.assertEqual([p.name for p in self.root.iterdir() if p.name != ".agentboard"], [])

    def test_the_agents_own_report_file_is_not_read_from_outside(self):
        (self.root / "secret.md").write_text("not for a report")
        self.assertEqual(reports.extras_md(self.s.dir, "../../secret"), "")

    def test_a_run_makes_no_folder_for_it(self):
        with self.assertRaises(BoardError):
            runs.run_dir(self.s.dir, "../../evil", "20261115-000000")
        self.assertFalse((self.root / "evil").exists())


if __name__ == "__main__":
    unittest.main()
