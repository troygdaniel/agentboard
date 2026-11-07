"""agentboard edit: an agent changes or appends to a card's description from the CLI, logged under its own name."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class CliEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Timed pull", "First paragraph.", status="doing", task_id="pull")
        self.s.claim("pull", "AGENT-1")

    def run_cli(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir), **(env or {})}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if "AGENTBOARD_NAME" not in env:
                os.environ.pop("AGENTBOARD_NAME", None)    # the caller's own shell must not leak in; patch.dict restores it
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def card(self):
        return Store.get(self.s.load(), "pull")

    def test_append_twice_keeps_the_old_text_and_logs_the_caller(self):
        self.assertEqual(self.run_cli("edit", "pull", "--append", "Line one.", "--name", "AGENT-4")[0], 0)
        self.assertEqual(self.run_cli("edit", "pull", "--append", "Line two.", "--name", "AGENT-4")[0], 0)
        t = self.card()
        self.assertEqual(t["description"], "First paragraph.\n\nLine one.\n\nLine two.")
        changes = [e for e in t["log"] if e["text"] == "Description changed"]
        self.assertEqual([e.get("by") for e in changes], ["AGENT-4", "AGENT-4"])

    def test_edit_never_changes_the_holder_or_the_column(self):
        self.run_cli("edit", "pull", "--append", "Note.", "--name", "AGENT-4")
        t = self.card()
        self.assertEqual((t["agent"], t["status"]), ("AGENT-1", "doing"))

    def test_append_file_and_description_file(self):
        f = Path(self.tmp.name) / "more.md"
        f.write_text("From a file.\n")
        self.assertEqual(self.run_cli("edit", "pull", "--append-file", str(f), "--name", "AGENT-4")[0], 0)
        self.assertEqual(self.card()["description"], "First paragraph.\n\nFrom a file.")
        self.assertEqual(self.run_cli("edit", "pull", "--description-file", str(f), "--name", "AGENT-4")[0], 0)
        self.assertEqual(self.card()["description"], "From a file.")

    def test_title_and_description_replace(self):
        code, out, _ = self.run_cli("edit", "pull", "--title", "Timed text pull", "--description", "New.", "--name", "AGENT-4")
        self.assertEqual(code, 0)
        self.assertIn("pull: edited", out)
        t = self.card()
        self.assertEqual((t["title"], t["description"]), ("Timed text pull", "New."))

    def test_name_comes_from_the_environment_too(self):
        self.run_cli("edit", "pull", "--append", "Via env.", env={"AGENTBOARD_NAME": "AGENT-2"})
        self.assertEqual(self.card()["log"][-1].get("by"), "AGENT-2")

    def test_refusals_change_nothing(self):
        before = self.card()["description"]
        self.assertNotEqual(self.run_cli("edit", "pull", "--append", "x")[0], 0)                      # no name
        self.assertNotEqual(self.run_cli("edit", "pull", "--name", "AGENT-4")[0], 0)                   # nothing to change
        self.assertNotEqual(self.run_cli("edit", "nope", "--append", "x", "--name", "AGENT-4")[0], 0)  # no such card
        self.assertNotEqual(self.run_cli("edit", "pull", "--append-file", "/no/such/file", "--name", "AGENT-4")[0], 0)
        self.assertEqual(self.card()["description"], before)


if __name__ == "__main__":
    unittest.main()
