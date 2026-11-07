"""transcript.read() opens the very Path it checked (sec-transcript-open-resolved, Nov 7). Before, allowed() expanded and resolved the
registered path but tail_text() opened the original string, so a path starting with ~ passed the check and then open() looked for a literal
"~" folder under the server's working directory: a check-then-use gap, harmless then, closed now."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import transcript


def entry(text):
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n"


class ResolvedPathTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.cwd = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.addCleanup(self.cwd.cleanup)
        real = Path(self.home.name) / ".claude" / "projects" / "p"
        real.mkdir(parents=True)
        (real / "abc.jsonl").write_text(entry("from the home folder"))
        decoy = Path(self.cwd.name) / "~" / ".claude" / "projects" / "p"   # a literal "~" folder where the server happens to run
        decoy.mkdir(parents=True)
        (decoy / "abc.jsonl").write_text(entry("from the working directory"))
        self.old_cwd = os.getcwd()
        os.chdir(self.cwd.name)
        self.addCleanup(os.chdir, self.old_cwd)
        p = mock.patch.dict(os.environ, {"HOME": self.home.name})
        p.start()
        self.addCleanup(p.stop)

    def test_a_tilde_path_is_read_from_the_home_folder_never_the_working_directory(self):
        out = transcript.read("~/.claude/projects/p/abc.jsonl")
        self.assertFalse(out.get("missing"), out)
        self.assertEqual([l["text"] for l in out["lines"]], ["from the home folder"])
        self.assertEqual(out["file"], "abc.jsonl")

    def test_the_check_and_the_open_see_the_same_file(self):
        real = transcript.resolved("~/.claude/projects/p/abc.jsonl")
        self.assertEqual(real, (Path(self.home.name) / ".claude" / "projects" / "p" / "abc.jsonl").resolve())
        self.assertTrue(transcript.allowed("~/.claude/projects/p/abc.jsonl"))

    def test_a_relative_or_outside_path_is_still_refused(self):
        for bad in ("~/.claude/projects/p/abc.txt", "abc.jsonl", "p/abc.jsonl", "/etc/hosts", "~/.claude/other/x.jsonl", "~/../x.jsonl"):
            self.assertIsNone(transcript.resolved(bad), bad)
            self.assertEqual(transcript.read(bad)["why"], "outside ~/.claude/projects", bad)

    def test_a_symlink_that_leaves_the_folder_is_refused_and_one_inside_is_read(self):
        root = Path(self.home.name) / ".claude" / "projects" / "p"
        outside = Path(self.home.name) / "outside.jsonl"
        outside.write_text(entry("outside"))
        (root / "link-out.jsonl").symlink_to(outside)
        (root / "link-in.jsonl").symlink_to(root / "abc.jsonl")
        self.assertEqual(transcript.read("~/.claude/projects/p/link-out.jsonl")["why"], "outside ~/.claude/projects")
        self.assertEqual([l["text"] for l in transcript.read("~/.claude/projects/p/link-in.jsonl")["lines"]], ["from the home folder"])


if __name__ == "__main__":
    unittest.main()
