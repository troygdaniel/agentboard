"""reports.git_info reads a run record from tasks.json, which may be copied or hand-edited: git must never see a value that is an option.
A base like --output=/path made `git log` write a file; now anything odd gives {} and writes nothing."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentboard import reports


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()


class GitRangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "work")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "first")
        self.c1 = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "second")
        self.c2 = git(self.repo, "rev-parse", "HEAD")
        self.board = self.repo / ".agentboard"
        self.board.mkdir()
        self.task = {"id": "t", "created": "2000-01-01T00:00:00", "log": []}

    def run_rec(self, **wt):
        return {"worktree": {"repo": str(self.repo), "base": self.c1, "branch": "work", **wt}}

    def files_here(self):
        return sorted(p.name for p in self.root.iterdir())

    def test_a_real_run_record_still_lists_its_commits(self):
        info = reports.git_info(self.board, self.task, self.run_rec())
        self.assertEqual([(s, subj) for s, subj in info["commits"]], [(self.c2, "second")])

    def test_the_card_open_window_still_lists_commits_without_a_run(self):
        info = reports.git_info(self.board, self.task, None)
        self.assertEqual([subj for _s, subj in info["commits"]], ["second", "first"])

    def test_a_base_that_is_an_option_gives_nothing_and_writes_no_file(self):
        before = self.files_here()
        for base in (f"--output={self.root}/PWNED", "-n", "--all", "HEAD", "main", self.c1[:12], self.c1.upper(), self.c1 + "\n--all"):
            self.assertEqual(reports.git_info(self.board, self.task, self.run_rec(base=base)), {}, repr(base))
        self.assertEqual(self.files_here(), before)
        self.assertFalse(list(self.root.glob("PWNED*")))

    def test_a_branch_that_is_an_option_or_not_a_branch_name_gives_nothing(self):
        before = self.files_here()
        for branch in ("-x", f"--output={self.root}/PWNED", "a..b", "a b", "x/", "x.lock", "a//b", "a\nb", "x~1", "x^", "x:y", "x?"):
            self.assertEqual(reports.git_info(self.board, self.task, self.run_rec(branch=branch)), {}, repr(branch))
        self.assertEqual(self.files_here(), before)

    def test_a_bad_repo_path_gives_nothing(self):
        for repo in ("relative/path", str(self.root / "nowhere"), str(self.root / "repo" / ".agentboard" / "x"), "--output=x"):
            self.assertEqual(reports.git_info(self.board, self.task, self.run_rec(repo=repo)), {}, repr(repo))

    def test_a_bad_claim_time_gives_nothing_and_writes_no_file(self):
        before = self.files_here()
        for stamp in (f"--output={self.root}/PWNED", "yesterday", "2000-01-01T00:00:00 --all", ""):
            task = {"id": "t", "created": stamp, "log": []}
            self.assertEqual(reports.git_info(self.board, task, None), {}, repr(stamp))
        self.assertEqual(self.files_here(), before)


if __name__ == "__main__":
    unittest.main()
