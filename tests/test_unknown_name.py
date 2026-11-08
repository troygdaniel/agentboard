"""A line to a name nobody has (chat-f5, loss path 9, repro R6): AGENT-33, "Agent 3" or "agent3 " used to be accepted without a word.
It still posts (a new session may not have spoken yet), but the line is marked, the sender is told and offered the closest known name,
and the board shows "no such name yet". A throwaway board; nothing reaches a real one."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, listeners
from agentboard.store import Store, _closest_name

from tests.test_reports import HttpTests as _Http


class Base(unittest.TestCase):
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
        self.s.start("Harden webhook retries", "AGENT-3", None)      # a card holder
        self.s.set_chat_agents(True)
        self.s.chat_send("AGENT-1", "a status line")                 # a chat sender
        listeners.register(self.s.dir, "AGENT-2", "inbox", pid=1)    # a listener

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()


class UnknownNameTests(Base):
    def test_typos_post_marked_with_the_closest_name_and_real_names_do_not(self):
        for typo, close in (("AGENT-33", "AGENT-3"), ("Agent 3", "AGENT-3"), ("agent3 ", "AGENT-3"), ("Bob", None)):
            m = self.s.chat_send("R6", "hello?", to=typo)
            self.assertTrue(m.get("to_unknown"), typo)
            self.assertEqual(m.get("closest"), close, typo)
        for real in ("AGENT-3", "agent-3", "AGENT-1", "AGENT-2", "agent-2", "ORCH", "orch", self.s.owner, "the user", "all", "ALL"):
            m = self.s.chat_send("R6", "hello?", to=real)
            self.assertNotIn("to_unknown", m, real)
            self.assertNotIn("closest", m, real)
        self.assertEqual(_closest_name("AGENT-33", ["AGENT-1", "AGENT-3", "ORCH"]), "AGENT-3")
        self.assertIsNone(_closest_name("Zebra", ["AGENT-1", "AGENT-3", "ORCH"]))

    def test_the_sender_is_told_in_the_terminal_and_the_line_still_posts(self):
        code, out, err = self.run_cli("chat", "send", "hello?", "--name", "R6", "--to", "AGENT-33")
        self.assertEqual(code, None)
        self.assertIn("-> AGENT-33", out)
        self.assertEqual(err.strip(), "(nobody named AGENT-33 has spoken or is listening; did you mean AGENT-3?)")
        code, out, err = self.run_cli("chat", "send", "hello?", "--name", "R6", "--to", "Bob")
        self.assertEqual(err.strip(), "(nobody named Bob has spoken or is listening)")
        code, out, err = self.run_cli("chat", "send", "hello?", "--name", "R6", "--to", "AGENT-3")
        self.assertEqual(err, "")
        self.assertTrue(self.s.chat_list()[-3]["to_unknown"] and "to_unknown" not in self.s.chat_list()[-1])

    def test_the_owners_own_typo_from_the_board_is_marked_too(self):
        m = self.s.chat_send(self.s.owner, "@AGENT-33 can you look?", kind="user", to="AGENT-33")
        self.assertEqual((m["to_unknown"], m["closest"]), (True, "AGENT-3"))

    def test_the_page_shows_no_such_name_yet(self):
        page = (Path(cli.__file__).parent / "static" / "index.html").read_text()
        self.assertIn("m.to_unknown ? `<span class=\"chip noname\"", page)
        self.assertIn("no such name yet</span>", page)
        self.assertIn("Did you mean ${esc(m.closest)}?", page)
        self.assertIn(".chip.noname {", page)


class OverHttp(_Http):
    def test_the_boards_composer_line_to_a_typo_comes_back_marked(self):
        self.s.start("Harden webhook retries", "AGENT-3", None)
        d = self.post("/api/chat", {"text": "@AGENT-33 can you look?"})
        self.assertEqual((d["to"], d["to_unknown"], d["closest"]), ("AGENT-33", True, "AGENT-3"))
        d = self.post("/api/chat", {"text": "@AGENT-3 can you look?"})
        self.assertNotIn("to_unknown", d)
