"""`agentboard init` keeps task data out of git: it adds .agentboard/ to the project's .gitignore."""
import os
import tempfile
import unittest
from pathlib import Path

from agentboard import cli


class InitGitignoreTests(unittest.TestCase):
    def run_init(self, root):
        cwd = os.getcwd()
        os.chdir(root)
        try:
            cli.cmd_init(None)
        finally:
            os.chdir(cwd)

    def test_creates_gitignore_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_init(d)
            self.assertEqual((Path(d) / ".gitignore").read_text().splitlines()[-1], ".agentboard/")
            self.assertTrue((Path(d) / ".agentboard" / "tasks.json").exists())

    def test_appends_once_and_respects_an_existing_entry(self):
        with tempfile.TemporaryDirectory() as d:
            gi = Path(d) / ".gitignore"
            gi.write_text("node_modules/\n")
            self.run_init(d)
            self.run_init(d)
            text = gi.read_text()
            self.assertEqual(text.count(".agentboard/"), 1)
            self.assertTrue(text.startswith("node_modules/\n"))
        with tempfile.TemporaryDirectory() as d:
            gi = Path(d) / ".gitignore"
            gi.write_text("/.agentboard\n")
            self.run_init(d)
            self.assertEqual(gi.read_text(), "/.agentignore\n".replace("ignore", "board"))


if __name__ == "__main__":
    unittest.main()
