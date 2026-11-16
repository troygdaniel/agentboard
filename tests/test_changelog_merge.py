"""CHANGELOG.md merges without a conflict when two branches each add an entry at the top of Unreleased (card retro-changelog-merge-union).
39 of the 53 agentboard merges that conflicted in 20 Oct to 15 Nov 2026 conflicted on this one file: every change adds a line at the same spot.
`.gitattributes` says `CHANGELOG.md merge=union`, so git keeps both sides' text. The test builds a scratch repo, merges two branches, and checks
that both entries survive whole; its control merges the same branches without the attribute and expects the conflict, so a pass means the line did it."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = """# Changelog

## Unreleased

### Older entry (Nov 1)
- what was wrong, what changed

## 0.3.0
- first release
"""
ENTRY_A = "### Entry A is true now (Nov 14)\n- A line one\n- A line two\n\n"
ENTRY_B = "### Entry B is true now (Nov 15)\n- B line one\n- B line two\n\n"


def git(repo, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=check)


def top_insert(text, entry):
    return text.replace("## Unreleased\n\n", "## Unreleased\n\n" + entry, 1)


class ChangelogMergeTests(unittest.TestCase):
    def repo(self, attributes):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        git(repo, "init", "-q", "-b", "main")
        (repo / "CHANGELOG.md").write_text(BASE)
        if attributes is not None:
            (repo / ".gitattributes").write_text(attributes)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        for name, entry in (("a", ENTRY_A), ("b", ENTRY_B)):
            git(repo, "checkout", "-q", "-b", name, "main")
            (repo / "CHANGELOG.md").write_text(top_insert(BASE, entry))
            git(repo, "commit", "-qam", name)
        git(repo, "checkout", "-q", "a")
        return repo

    def test_the_repo_sets_the_attribute(self):
        lines = [x.strip() for x in (ROOT / ".gitattributes").read_text().splitlines()]
        self.assertIn("CHANGELOG.md merge=union", lines)

    def test_two_branches_adding_an_entry_merge_cleanly_and_keep_both_whole(self):
        repo = self.repo((ROOT / ".gitattributes").read_text())
        done = git(repo, "merge", "--no-edit", "b", check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        text = (repo / "CHANGELOG.md").read_text()
        # each entry still reads as one block, not interleaved. The blank line between the two new entries can be lost (union keeps
        # lines, not paragraphs), so the check leaves off each entry's trailing blank line; a `###` heading still starts the next entry.
        self.assertIn(ENTRY_A.rstrip("\n"), text)
        self.assertIn(ENTRY_B.rstrip("\n"), text)
        self.assertIn("### Older entry (Nov 1)", text)
        self.assertNotIn("<<<<<<<", text)
        self.assertLess(text.index("## Unreleased"), min(text.index("Entry A"), text.index("Entry B")))   # both still sit under Unreleased
        self.assertLess(max(text.index("Entry A"), text.index("Entry B")), text.index("### Older entry"))

    def test_without_the_attribute_the_same_merge_conflicts(self):
        repo = self.repo(None)
        done = git(repo, "merge", "--no-edit", "b", check=False)
        self.assertNotEqual(done.returncode, 0)   # the control: the attribute is what makes the merge clean
        self.assertIn("<<<<<<<", (repo / "CHANGELOG.md").read_text())


if __name__ == "__main__":
    unittest.main()
