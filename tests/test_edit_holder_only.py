"""`agentboard edit` replaces the title or description of a card another agent holds only if you hold it (card finding-edit-lets-any-agent-replace-the,
found in sweep-func-cli). update, ask, review, release, move and rm already answer to store._must_hold: the holder, ORCH, the owner and a shell with no
agent name pass, any other agent is refused and told whom to ask. edit now does the same for --title, --description and --description-file.
--append and --append-file stay open to every agent: edit was built so agents can annotate each other's cards, and a note added is not a card
rewritten. A card nobody holds may be edited by anyone, as before."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class EditHolderOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.held = self.s.add("A card AG-1 holds", "The brief.", "todo", [])
        self.free = self.s.add("A card nobody holds", "Free.", "todo", [])
        self.run_cli("AG-1", "claim", self.held["id"], "--name", "AG-1")

    def run_cli(self, name, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir)}
        if name:
            env["AGENTBOARD_NAME"] = name
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def card(self, t):
        return Store.get(self.s.load(), t["id"])

    def test_another_agent_cannot_replace_the_title_or_description(self):
        for argv in (["--title", "hijacked"], ["--description", "rewritten"], ["--title", "hijacked", "--append", "and a note"]):
            code, _, err = self.run_cli("AG-2", "edit", self.held["id"], *argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("held by AG-1", err, argv)
        t = self.card(self.held)
        self.assertEqual((t["title"], t["description"]), ("A card AG-1 holds", "The brief."))

    def test_another_agent_may_still_append_a_note(self):
        code, _, err = self.run_cli("AG-2", "edit", self.held["id"], "--append", "AG-2: the API changed, see card x")
        self.assertEqual(code, 0, err)
        t = self.card(self.held)
        self.assertEqual(t["title"], "A card AG-1 holds")
        self.assertTrue(t["description"].endswith("AG-2: the API changed, see card x"), t["description"])

    def test_the_holder_orch_and_the_owner_edit_it(self):   # (edit has always needed a name, so there is no nameless shell here)
        for i, name in enumerate(["AG-1", "ORCH", self.s.owner]):
            code, _, err = self.run_cli(name, "edit", self.held["id"], "--title", f"title {i}", "--description", f"text {i}")
            self.assertEqual(code, 0, (name, err))
            self.assertEqual((self.card(self.held)["title"], self.card(self.held)["description"]), (f"title {i}", f"text {i}"))

    def test_a_card_nobody_holds_is_open_to_any_agent(self):
        code, _, err = self.run_cli("AG-2", "edit", self.free["id"], "--title", "renamed by AG-2")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.card(self.free)["title"], "renamed by AG-2")


if __name__ == "__main__":
    unittest.main()
