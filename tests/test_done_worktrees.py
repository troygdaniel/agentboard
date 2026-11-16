"""agentboard done lists the card's worktree and branch, whether it is merged, and the merged worktrees that could go (card retro-done-shows-worktrees).
Every case is a real scratch repo with real `git worktree add` folders. The list is all it is: each case checks the folders and branches are still there."""
import contextlib
import io
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, lockdown, reports, worktrees
from agentboard.store import Store


def git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "proj"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "first")
        self.s = Store(self.repo / ".agentboard")

    def worktree(self, folder, branch):
        path = self.root / folder
        git(self.repo, "worktree", "add", "-q", "-b", branch, str(path), "main")
        return path

    def card(self, cid, agent, status="doing"):
        self.s.add(f"Card {cid}", status=status, task_id=cid)
        self.s.claim(cid, agent)

    def done(self, cid, *extra, store=None):
        out, err = io.StringIO(), io.StringIO()
        s = store or self.s
        env = {"AGENTBOARD_DIR": str(s.dir)}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(["done", cid, *extra])
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):    # BoardError leaves as SystemExit("agentboard: ...")
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def branches(self):
        return set(git(self.repo, "branch", "--format=%(refname:short)").split())

    def status(self, cid):
        return Store.get(self.s.load(), cid)["status"]


class OwnWorktree(Base):
    def test_a_merged_clean_worktree_is_named_and_the_command_is_offered_but_not_run(self):
        wt = self.worktree("proj-AGENT-1", "feature-one")
        self.card("c1", "AGENT-1")
        code, out, _ = self.done("c1")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "c1: done")
        self.assertIn(f"this card's worktree: {wt} (branch feature-one)", out)
        self.assertIn("merged into main and clean", out)
        self.assertIn(f"git worktree remove {wt}", out)
        self.assertTrue(wt.is_dir())                          # a list, never a removal
        self.assertIn("feature-one", self.branches())

    def test_a_worktree_with_commits_main_lacks_says_how_many_and_offers_no_command(self):
        wt = self.worktree("proj-AGENT-1", "feature-one")
        git(wt, "commit", "-q", "--allow-empty", "-m", "work")
        git(wt, "commit", "-q", "--allow-empty", "-m", "more work")
        self.card("c1", "AGENT-1")
        _, out, _ = self.done("c1")
        self.assertIn("NOT merged into main: 2 commits ahead; keep it", out)
        self.assertNotIn("git worktree remove", out)
        self.assertTrue(wt.is_dir())

    def test_one_commit_ahead_reads_in_the_singular(self):
        wt = self.worktree("proj-AGENT-1", "feature-one")
        git(wt, "commit", "-q", "--allow-empty", "-m", "work")
        self.card("c1", "AGENT-1")
        self.assertIn("1 commit ahead", self.done("c1")[1])

    def test_a_merged_worktree_with_uncommitted_changes_is_kept(self):
        wt = self.worktree("proj-AGENT-1", "feature-one")
        (wt / "scratch.txt").write_text("not saved\n")
        self.card("c1", "AGENT-1")
        _, out, _ = self.done("c1")
        self.assertIn("merged into main, but it has uncommitted changes", out)
        self.assertNotIn("git worktree remove", out)

    def test_a_locked_worktree_is_kept_and_says_so(self):
        wt = self.worktree("proj-AGENT-1", "feature-one")
        git(self.repo, "worktree", "lock", str(wt))
        self.card("c1", "AGENT-1")
        _, out, _ = self.done("c1")
        self.assertIn("but locked", out)
        self.assertNotIn(f"git worktree remove {wt}", out)

    def test_the_card_id_in_the_branch_finds_the_worktree_even_without_the_agents_name(self):
        wt = self.worktree("scratch-folder", "work-on-c1")
        self.card("c1", "AGENT-1")
        self.assertIn(f"this card's worktree: {wt}", self.done("c1")[1])

    def test_a_card_with_no_worktree_says_there_is_none(self):
        self.worktree("proj-AGENT-2", "other")
        self.card("c1", "AGENT-1")
        self.assertIn("no worktree found for this card (AGENT-1)", self.done("c1")[1])

    def test_the_owners_name_is_matched_whole_so_agent_14_is_not_agent_1(self):
        self.worktree("proj-AGENT-14", "fourteen")
        self.card("c1", "AGENT-1")
        _, out, _ = self.done("c1")
        self.assertIn("no worktree found for this card", out)
        self.assertNotIn("this card's worktree", out)


class OtherWorktrees(Base):
    def test_merged_clean_worktrees_of_idle_agents_are_listed_and_the_others_are_counted(self):
        idle = self.worktree("proj-AGENT-2", "idle-two")
        busy = self.worktree("proj-AGENT-3", "busy-three")
        ahead = self.worktree("proj-AGENT-4", "ahead-four")
        git(ahead, "commit", "-q", "--allow-empty", "-m", "work")
        locked = self.worktree("proj-AGENT-5", "locked-five")
        git(self.repo, "worktree", "lock", str(locked))
        self.card("c1", "AGENT-1")
        self.card("c3", "AGENT-3")          # AGENT-3 holds an open card: its folder is in use however merged it looks
        _, out, _ = self.done("c1")
        self.assertIn(f"git worktree remove {idle}   # branch idle-two", out)
        for kept in (busy, ahead, locked):
            self.assertNotIn(f"git worktree remove {kept}", out)
        self.assertIn("3 other worktrees not listed", out)
        for d in (idle, busy, ahead, locked):
            self.assertTrue(d.is_dir())
        self.assertEqual(self.branches(), {"main", "idle-two", "busy-three", "ahead-four", "locked-five"})

    def test_an_agent_whose_open_card_is_the_one_being_closed_does_not_keep_its_own_folder_busy(self):
        wt = self.worktree("proj-AGENT-1", "mine")
        self.card("c1", "AGENT-1")
        self.assertIn(f"git worktree remove {wt}", self.done("c1")[1])

    def test_the_list_stops_at_the_cap_and_counts_the_rest(self):
        for i in range(4):
            self.worktree(f"proj-AGENT-{10 + i}", f"b{i}")
        self.card("c1", "AGENT-1")
        with mock.patch.object(worktrees, "MAX_SHOWN", 2):
            _, out, _ = self.done("c1")
        self.assertEqual(out.count("git worktree remove"), 2)
        self.assertIn("and 2 more", out)

    def test_a_path_with_a_space_is_quoted_so_the_line_can_be_pasted(self):
        wt = self.worktree("my tree-AGENT-9", "spaced")
        self.card("c1", "AGENT-1")
        _, out, _ = self.done("c1")
        self.assertIn("git worktree remove " + shlex.quote(str(wt)), out)

    def test_a_worktree_whose_folder_is_gone_is_skipped(self):
        wt = self.worktree("proj-AGENT-2", "gone")
        os.rename(wt, self.root / "moved-away")
        self.card("c1", "AGENT-1")
        _, out, _ = self.done("c1")
        self.assertNotIn("proj-AGENT-2", out)


class QuietCases(Base):
    def test_outside_a_git_repository_done_is_exactly_what_it_was(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        s = Store(plain / ".agentboard")
        s.add("Card", status="doing", task_id="c1")
        s.claim("c1", "AGENT-1")
        code, out, err = self.done("c1", store=s)
        self.assertEqual((code, out, err), (0, "c1: done\n", ""))

    def test_a_repo_with_no_linked_worktree_prints_nothing_extra(self):
        self.card("c1", "AGENT-1")
        self.assertEqual(self.done("c1")[1], "c1: done\n")

    def test_the_lockdown_asks_git_nothing(self):
        self.worktree("proj-AGENT-1", "feature-one")
        self.card("c1", "AGENT-1")
        real = reports.subprocess.Popen
        started = []

        def spy(argv, *a, **k):   # the report written on done reads git too (`rev-parse`, existing and documented); the worktree list must not
            started.append(list(argv))
            return real(argv, *a, **k)
        with mock.patch.dict(os.environ, {lockdown.ENV: "1"}), mock.patch.object(reports.subprocess, "Popen", spy):
            code, out, _ = self.done("c1")
        self.assertEqual((code, out), (0, "c1: done\n"))
        self.assertFalse([a for a in started if "worktree" in a or "rev-list" in a or "status" in a], started)

    def test_a_subtask_has_no_worktree_of_its_own(self):
        self.worktree("proj-AGENT-1", "feature-one")
        self.card("c1", "AGENT-1")
        self.s.add("Step", parent_id="c1", task_id="c1-step")
        self.assertEqual(self.done("c1-step")[1], "c1-step: done\n")

    def test_a_failure_in_the_list_never_stops_the_close(self):
        self.card("c1", "AGENT-1")
        with mock.patch.object(worktrees, "report", side_effect=RuntimeError("boom")):
            code, out, _ = self.done("c1")
        self.assertEqual((code, out), (0, "c1: done\n"))
        self.assertEqual(self.status("c1"), "done")


class RepoFlag(Base):
    def test_repo_lists_another_repos_worktrees_when_the_board_is_not_in_one(self):
        wt = self.worktree("proj-AGENT-1", "feature-one")
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        s = Store(plain / ".agentboard")
        s.add("Card", status="doing", task_id="c1")
        s.claim("c1", "AGENT-1")
        code, out, _ = self.done("c1", "--repo", str(self.repo), store=s)
        self.assertEqual(code, 0)
        self.assertIn(f"git worktree remove {wt}", out)

    def test_a_repo_that_is_not_a_folder_is_refused_before_the_card_is_closed(self):
        self.card("c1", "AGENT-1")
        code, _, err = self.done("c1", "--repo", "relative/path")
        self.assertNotEqual(code, 0)
        self.assertIn("--repo", err)
        self.assertEqual(self.status("c1"), "doing")


class ReadsOnly(Base):
    def test_every_git_call_is_a_read_that_takes_no_optional_lock(self):
        self.worktree("proj-AGENT-1", "one")
        self.worktree("proj-AGENT-2", "two")
        self.card("c1", "AGENT-1")
        calls, inside = [], []
        real_git, real_report = reports._git, worktrees.report

        def spy(args, cwd):
            if inside:                      # only what the worktree list asks: the report written on done runs its own git (`rev-parse`, `log`)
                calls.append(list(args))
            return real_git(args, cwd)

        def report(*a, **k):
            inside.append(1)
            try:
                return real_report(*a, **k)
            finally:
                inside.pop()
        with mock.patch.object(reports, "_git", spy), mock.patch.object(worktrees, "report", report):
            self.done("c1")
        self.assertTrue(calls)
        for args in calls:
            self.assertEqual(args[0], "--no-optional-locks", args)
            self.assertIn(args[1], ("worktree", "rev-list", "status"), args)
            if args[1] == "worktree":
                self.assertEqual(args[2:], ["list", "--porcelain"])
            if args[1] == "status":
                self.assertEqual(args[2:], ["--porcelain"])


class Parse(unittest.TestCase):
    def test_the_porcelain_listing_reads_branch_detached_locked_and_prunable(self):
        text = ("worktree /r/main\nHEAD " + "a" * 40 + "\nbranch refs/heads/main\n\n"
                "worktree /r/one\nHEAD " + "b" * 40 + "\nbranch refs/heads/feature/x\nlocked because\n\n"
                "worktree /r/two\nHEAD " + "c" * 40 + "\ndetached\nprunable gitdir file points to non-existent location\n")
        a, b, c = worktrees.parse(text)
        self.assertEqual((a["path"], a["branch"], a["locked"]), ("/r/main", "main", False))
        self.assertEqual((b["branch"], b["locked"], b["prunable"]), ("feature/x", True, False))
        self.assertEqual((c["branch"], c["prunable"]), (None, True))

    def test_nothing_in_gives_nothing_out(self):
        self.assertEqual(worktrees.parse(""), [])
        self.assertEqual(worktrees.parse(None), [])


if __name__ == "__main__":
    unittest.main()
