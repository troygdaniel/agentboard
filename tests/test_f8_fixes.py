"""The nine lines AGENT-2 found where the live board and the terminal did not match docs/chat-words-design.md after chat-f8 (card
chat-f8-fixes-9-lines-the-live-board-and). One test per line; the strings are the contract. Throwaway boards, made-up names."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, server
from agentboard.store import BoardError, Store

HTML = (Path(server.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    i = HTML.index(f"function {fn}(")
    return HTML[i:HTML.index("\n}\n", i)]


class Terminal(unittest.TestCase):
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
        for n in range(1, 8):
            self.s.start(f"Card {n}", f"AGENT-{n}", None)   # seven agents on the board, so the names list is cut

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_1_an_unknown_name_posts_nothing_exits_1_and_names_the_closest_or_the_board(self):
        n = len(self.s.chat_list())
        code, out, err = self.run_cli("chat", "send", "hello?", "--name", "AGENT-1", "--to", "AGENT-33")
        self.assertEqual(str(code), "agentboard: Not sent: no one named AGENT-33. Closest: AGENT-3. Send again with --to AGENT-3.")
        code, out, err = self.run_cli("chat", "send", "hello?", "--name", "AGENT-1", "--to", "Bob")
        self.assertEqual(str(code), "agentboard: Not sent: no one named Bob. Names on this board: ORCH, AGENT-1, AGENT-2, AGENT-3, AGENT-4, AGENT-5, and 2 more.")
        self.assertEqual(len(self.s.chat_list()), n)

    def test_2_the_name_is_checked_before_the_switch(self):
        self.s.set_chat_agents(False)
        with self.assertRaises(BoardError) as cm:
            self.s.chat_send("AGENT-1", "hello?", to="AGENT-33")
        self.assertTrue(str(cm.exception).startswith("Not sent: no one named AGENT-33."))

    def test_3_agent_chat_off_agent_to_agent(self):
        self.s.set_chat_agents(False)
        with self.assertRaises(BoardError) as cm:
            self.s.chat_send("AGENT-1", "hello?", to="AGENT-2")
        self.assertEqual(str(cm.exception), "Not sent: agent chat is off, so agents post one-line status only. A line to the user still goes; "
                                            "to reach another agent, the owner runs: agentboard chat agents on")

    def test_4_over_the_limit_to_an_agent_is_refused_with_the_count_and_to_the_owner_is_cut_and_said(self):
        self.s.set_chat_agents(True)
        with self.assertRaises(BoardError) as cm:
            self.s.chat_send("AGENT-1", "x" * 410, to="AGENT-2")
        self.assertEqual(str(cm.exception), "Not sent: 410 characters, the limit is 300. Shorten it, or keep the rest in --detail.")
        code, out, err = self.run_cli("chat", "send", "word " * 80, "--name", "AGENT-1", "--to", "you")
        self.assertIsNone(code)
        self.assertEqual(err.strip(), "Sent, cut at 300 characters: the rest is in the detail.")
        code, out, err = self.run_cli("chat", "send", "short", "--name", "AGENT-1", "--to", "you")
        self.assertEqual(err, "")


class Board(unittest.TestCase):
    def test_5_nobody_listening(self):
        h = body("receiptHtml")
        self.assertIn("warn = orch ? `Nobody is listening for ORCH: it reads the board at its next check.` : `Nobody is listening for ${to}.`;", h)
        self.assertIn('data-nudge="${m.seq}"', h)   # the Nudge stays

    def test_6_listening_but_busy_is_muted(self):
        h = body("receiptHtml")
        self.assertIn("if (r.listening) return `<div class=\"cmsg-rcpt sent\"><span class=\"st\">sent</span>${twins}<span class=\"note\">${to} is listening but busy: it reads this when its step ends.</span></div>`;", h)
        self.assertIn(".cmsg-rcpt .nudged, .cmsg-rcpt .note { color: var(--muted); }", HTML)

    def test_7_after_the_nudge(self):
        self.assertIn("${orch ? 'nudged' : 'ORCH asked'} ${esc(ago(m.nudged).text)}${orch ? '' : ' to message it'}", body("receiptHtml"))

    def test_8_the_names_list_puts_orch_first_and_leaves_the_owner_out(self):
        self.assertIn("return ['ORCH', ...chatNames.filter(n => !isOrch(n) && !sameName(n, OWNER)", body("boardNames"))
        self.assertIn("const close = closestName(typed), names = boardNames();", body("whoReads"))
        self.assertIn("On this board: ${names.slice(0, NAME_CAP).join(', ')}${names.length > NAME_CAP ? ` and ${names.length - NAME_CAP} more` : ''}.", body("whoReads"))

    def test_9_an_exact_known_name_with_no_space_is_complete(self):
        w = body("whoReads")
        self.assertIn("if (!full) {   // still typing the name (an exact known name counts as complete, space or not)", w)
        self.assertNotIn("if (!full || !spaced)", w)
        self.assertIn("error: rest ? '' : `Add what to tell ${full} after the name.`", w)
