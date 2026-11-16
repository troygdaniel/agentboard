"""`agentboard review` warns when the tree has uncommitted changes or the branch has nothing past main (retro rec 6, card
retro-review-warns-uncommitted): one plain line on stderr and the same words in the card's history; a warning only, never a block."""
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, treecheck
from agentboard.store import Store

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main"]


def git(tree, *args):
    subprocess.run([*GIT, "-C", str(tree), *args], check=True, capture_output=True)


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "work"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "a.txt").write_text("one\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-q", "-m", "first")
        env = mock.patch.dict(os.environ, {treecheck.ENV: "on"})   # the suite switches it off (tests/netguard.py)
        env.start()
        self.addCleanup(env.stop)

    def branch_with_a_commit(self, name="card"):
        git(self.repo, "checkout", "-q", "-b", name)
        (self.repo / "b.txt").write_text("two\n")
        git(self.repo, "add", "b.txt")
        git(self.repo, "commit", "-q", "-m", "work")


class Check(Tree):
    def test_a_committed_branch_past_main_says_nothing(self):
        self.branch_with_a_commit()
        self.assertIsNone(treecheck.check(self.repo))

    def test_uncommitted_changes_are_counted(self):
        self.branch_with_a_commit()
        (self.repo / "b.txt").write_text("changed\n")
        (self.repo / "new.txt").write_text("new\n")
        line = treecheck.check(self.repo)
        self.assertIn("2 uncommitted changes", line)
        self.assertNotIn("nothing past", line)

    def test_one_change_is_not_plural(self):
        self.branch_with_a_commit()
        (self.repo / "b.txt").write_text("changed\n")
        self.assertIn("1 uncommitted change in", treecheck.check(self.repo))

    def test_a_branch_with_nothing_past_main(self):
        git(self.repo, "checkout", "-q", "-b", "card")
        self.assertIn("branch card with nothing past main", treecheck.check(self.repo))

    def test_main_itself_has_nothing_past_main(self):
        self.assertIn("you are on main itself with nothing past main", treecheck.check(self.repo))

    def test_both_problems_make_one_line(self):
        git(self.repo, "checkout", "-q", "-b", "card")
        (self.repo / "a.txt").write_text("edited\n")
        line = treecheck.check(self.repo)
        self.assertEqual(line.count("\n"), 0)
        self.assertIn("1 uncommitted change", line)
        self.assertIn("nothing past main", line)

    def test_an_ignored_file_is_not_a_change(self):
        self.branch_with_a_commit()
        (self.repo / ".gitignore").write_text("out/\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore")
        (self.repo / "out").mkdir()
        (self.repo / "out" / "x.png").write_text("x")
        self.assertIsNone(treecheck.check(self.repo))

    def test_a_folder_that_is_not_a_repository_says_nothing(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertIsNone(treecheck.check(plain))

    def test_a_repository_without_main_or_master_says_nothing(self):
        git(self.repo, "branch", "-m", "trunk")
        self.assertIsNone(treecheck.check(self.repo))

    def test_master_counts_as_the_base(self):
        git(self.repo, "branch", "-m", "master")
        self.assertIn("nothing past master", treecheck.check(self.repo))

    def test_the_switch_turns_it_off(self):
        with mock.patch.dict(os.environ, {treecheck.ENV: "off"}):
            self.assertIsNone(treecheck.check(self.repo))

    def test_a_missing_git_says_nothing(self):
        with mock.patch("agentboard.treecheck.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(treecheck.check(self.repo))

    def test_a_slow_git_says_nothing(self):
        with mock.patch("agentboard.treecheck.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            self.assertIsNone(treecheck.check(self.repo))


class Review(Tree):
    def setUp(self):
        super().setUp()
        self.s = Store(self.root / ".agentboard")
        self.s.add("Card", status="todo", task_id="card")
        self.s.add("Step one", parent_id="card", task_id="s1")
        self.s.add("Step two", parent_id="card", task_id="s2")
        self.s.claim("card", "atlas")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def test_review_warns_on_stderr_and_in_the_history_but_still_goes_through(self):
        git(self.repo, "checkout", "-q", "-b", "card")
        (self.repo / "a.txt").write_text("edited\n")
        code, out, err = self.run_cli("review", "card", "done", "--next", "nothing", "--tree", str(self.repo))
        self.assertEqual(code, 0)
        self.assertIn("ready for review", out)
        self.assertTrue(err.startswith("warning: 1 uncommitted change in "), err)
        self.assertEqual(err.count("\n"), 1)
        t = Store.get(self.s.load(), "card")
        self.assertTrue(t["review"])
        self.assertTrue(any(e["text"].startswith("Review warning: 1 uncommitted change") for e in t["log"]), t["log"])

    def test_a_clean_branch_past_main_adds_nothing(self):
        self.branch_with_a_commit()
        code, out, err = self.run_cli("review", "card", "done", "--next", "nothing", "--tree", str(self.repo))
        self.assertEqual((code, err), (0, ""))
        self.assertFalse(any("Review warning" in e["text"] for e in Store.get(self.s.load(), "card")["log"]))

    def test_the_folder_you_run_in_is_the_default_tree(self):
        git(self.repo, "checkout", "-q", "-b", "card")
        old = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, old)
        _, _, err = self.run_cli("review", "card", "done", "--next", "nothing")
        self.assertIn("nothing past main", err)

    def test_a_subtask_review_is_not_checked(self):
        git(self.repo, "checkout", "-q", "-b", "card")
        _, _, err = self.run_cli("review", "s1", "done", "--tree", str(self.repo))
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
