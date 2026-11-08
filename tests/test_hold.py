"""An agent reports only on the card it holds (overnight-rel-agent-protocol-3): update, review and ask from a session whose name is
another agent's are refused with the fix. The owner, ORCH, a session with no name (the server, a plain shell) and a card with no holder
are let through. A throwaway board; nothing reaches a real one."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import BoardError, Store


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(root / "proj" / ".agentboard")
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.s.start("Export pipeline", "AGENT-3", None)
        self.s.add("step one", parent_id="export-pipeline", task_id="s1")
        self.s.add("Nobody's card", task_id="open")
        self.s.claim("open", "AGENT-7")
        with self.s.transaction() as tasks:   # a Doing card with no holder (what a hand edit or an old board can leave)
            for t in tasks:
                if t["id"] == "open":
                    t.pop("agent", None)

    def run_cli(self, *argv, name=None):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_NAME": name} if name else {}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, env):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_the_holder_any_case_orch_the_owner_and_a_nameless_caller_may_report(self):
        for by in ("AGENT-3", "agent-3", "ORCH", "orch", self.s.owner, "you", None):
            self.s.update("export-pipeline", None, f"line from {by}", by=by)
            self.s.update("s1", 10, "a step", by=by)
            self.s.ask("export-pipeline", "which?", by=by)
            self.s.update("export-pipeline", None, "back", by=by)
        self.s.review("export-pipeline", "done", by="Agent-3")
        self.assertTrue(self.s.get(self.s.load(), "export-pipeline")["review"])

    def test_another_agent_is_refused_with_the_fix_on_the_card_and_its_subtasks(self):
        for call in (lambda: self.s.update("export-pipeline", None, "mine now", by="AGENT-9"),
                     lambda: self.s.update("s1", 50, "half", by="AGENT-9"),          # the subtask has no holder of its own: it answers to the parent's
                     lambda: self.s.ask("export-pipeline", "which?", by="AGENT-9"),
                     lambda: self.s.review("export-pipeline", "done", by="AGENT-9")):
            with self.assertRaises(BoardError) as cm:
                call()
            msg = str(cm.exception)
            self.assertIn("is held by AGENT-3, not AGENT-9: claim it first", msg)
            self.assertIn("`agentboard watchdog` releases it", msg)
        t = self.s.get(self.s.load(), "export-pipeline")
        self.assertEqual((t["status_text"], t.get("needs_input"), t.get("review")), ("Started by AGENT-3", None, None))   # nothing changed

    def test_the_instructions_and_the_orch_prompt_say_the_rule_and_the_refusal_names_the_column(self):
        from agentboard import prompt
        self.assertIn("You may only update, ask or review the card you hold: the board reads your session's name from AGENTBOARD_NAME", cli.INSTRUCTIONS)
        self.assertIn("ORCH and the owner are the exceptions", cli.INSTRUCTIONS)
        self.assertIn("agents may only report on the card they hold; you and {owner} may on any", prompt.ORCH_TEMPLATE)
        self.s.review("export-pipeline", "done", by="AGENT-3")
        with self.assertRaises(BoardError) as cm:
            self.s.update("export-pipeline", None, "a line", by="AGENT-9")
        self.assertIn("while AGENT-3 holds it in Doing that is refused", str(cm.exception))   # a card in review is still in the Doing column
        self.s.update("export-pipeline", None, "closing", status="done", by="AGENT-3")
        with self.assertRaises(BoardError) as cm:
            self.s.ask("export-pipeline", "which?", by="AGENT-9")
        self.assertIn("while AGENT-3 holds it in Done that is refused", str(cm.exception))

    def test_a_card_with_no_holder_is_open_to_any_name(self):
        self.s.update("open", 30, "picked up", by="AGENT-9")
        self.assertEqual(self.s.get(self.s.load(), "open")["progress"], 30)

    def test_the_cli_passes_the_sessions_name(self):
        code, out, err = self.run_cli("update", "s1", "40", "half way", name="AGENT-9")
        self.assertIn("is held by AGENT-3, not AGENT-9", str(code))
        code, out, err = self.run_cli("update", "s1", "40", "half way", name="AGENT-3")
        self.assertIsNone(code)
        code, out, err = self.run_cli("ask", "export-pipeline", "which?")   # no name: a plain shell, the owner's hand
        self.assertIsNone(code)
        code, out, err = self.run_cli("review", "export-pipeline", "done", name="ORCH")
        self.assertIsNone(code)
