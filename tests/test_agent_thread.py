"""The agent thread (Nov 6): one conversation with one agent outside any card, opened from the open card's agent pill or a lane's
name on By agent; a message the owner sends there wakes `answer --wait`; the card's question shows inline, answered on the card."""
import contextlib
import io
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, nav, prompt
from agentboard.store import Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class ThreadStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def test_only_what_the_owner_said_to_that_name_counts(self):
        self.s.chat_send(self.s.owner, "to everyone", kind="user", to="all")
        self.s.chat_send(self.s.owner, "for alice", kind="user", to="alice")
        self.s.chat_send(self.s.owner, "plain line", kind="user")
        self.s.chat_send("bob", "status only")
        self.s.chat_send(self.s.owner, "for ALICE again", kind="user", to="ALICE")
        got = self.s.chat_thread_new("alice")
        self.assertEqual([m["text"] for m in got], ["for alice", "for ALICE again"])
        self.assertEqual([m["text"] for m in self.s.chat_thread_new("alice", after=got[0]["seq"])], ["for ALICE again"])
        self.assertEqual(self.s.chat_thread_new("nobody"), [])


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.start("Card", "alice")
        self.s.add("step", parent_id="card")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def later(self, fn, delay=0.4):
        t = threading.Timer(delay, fn)
        self.addCleanup(t.join)
        t.start()

    def run_answer(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(["answer", "card", "--wait", "--timeout", "4", "--interval", "0.1", *extra])
        return out.getvalue(), err.getvalue()

    def test_a_message_to_the_agent_on_the_board_wakes_the_wait_and_is_marked_read(self):
        self.later(lambda: self.s.chat_send(self.s.owner, "how is it going?", kind="user", to="alice"))
        out, err = self.run_answer()
        self.assertEqual(out.strip(), "how is it going?")
        self.assertIn("message from", err)
        self.assertIn("--to", err)   # how to answer: on the board, to the owner
        from agentboard import cursors
        self.assertEqual(cursors.pending(self.s.dir, "alice")["seq"], self.s.chat_list()[-1]["seq"])   # delivered: printed, not yet seen
        out, err = self.run_answer_without_wait()   # the session is back as alice: that confirms it, and it does not print again
        self.assertEqual(out, "")
        self.assertEqual(cursors.get(self.s.dir, "alice"), self.s.chat_list()[-1]["seq"])

    def run_answer_without_wait(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            cli.main(["answer", "card"])
        return out.getvalue(), err.getvalue()

    def test_a_line_to_everyone_or_to_another_agent_does_not_wake_it(self):
        self.s.chat_send(self.s.owner, "hello all", kind="user", to="all")
        self.s.chat_send(self.s.owner, "for bob", kind="user", to="bob")
        self.later(lambda: self.s.reply("card", "Go ahead"), 0.5)
        out, err = self.run_answer()
        self.assertEqual(out.strip(), "Go ahead")   # the card reply is what woke it

    def test_a_card_reply_still_comes_first(self):
        self.s.chat_send(self.s.owner, "ping", kind="user", to="alice")
        self.s.reply("card", "Yes")
        out, err = self.run_answer()
        self.assertEqual(out.strip(), "Yes")


class PromptTests(unittest.TestCase):
    def test_every_prompt_and_the_instructions_say_a_board_message_wakes_the_wait(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Plain", status="todo")
            s.start("Parent", "alice")
            s.add("Kid", parent_id="parent")
            env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
            env["AGENTBOARD_DIR"] = str(s.dir)
            with mock.patch.dict(os.environ, env, clear=True):
                for tid in ("plain", "parent", "kid"):
                    text, _ = prompt.build_prompt(Store.get(s.load(), tid), s.dir, tasks=s.load())
                    self.assertIn("writes to you on the board", text, tid)
                    self.assertIn('chat send "<one line>" --name "<your session name>" --to', text, tid)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.main(["instructions"])
                self.assertIn("writes to you on the board", out.getvalue())


class PanelMarkupTests(unittest.TestCase):
    def test_the_thread_is_a_side_surface_like_the_card_panel(self):
        self.assertIn('<aside id="thread" aria-label="Agent thread">', HTML)
        self.assertIn("#panel, #later, #chat, #thread {", HTML)
        self.assertIn("#panel.open, #later.open, #chat.open, #thread.open { transform: none; visibility: visible; }", HTML)
        self.assertIn("if (which !== 'thread') $('thread').classList.remove('open');", body("setSide"))
        self.assertIn("$('thread').classList.remove('open');", body("openPanel"))   # a card opens alone
        self.assertIn("if ($('thread').classList.contains('open')) { closeThread(); return; }", HTML)   # Esc
        self.assertIn("!e.target.closest('#thread, [data-thread], #toast, .card')", HTML)   # the outside click

    def test_the_ways_in_are_the_open_cards_pill_and_the_lanes_name(self):
        self.assertIn('<button class="agent-pill" type="button" data-thread="${esc(t.agent)}"', body("panelHtml"))
        self.assertIn('<button class="nm" type="button" data-thread="${esc(n)}"', HTML)
        self.assertIn("const b = e.target.closest('[data-thread]');", HTML)
        self.assertIn("if (b) { if (b.closest('#panel')) setPanelTab('chat'); else openThread(b.dataset.thread); return; }", HTML)
        card_fn = body("card")
        self.assertNotIn("data-thread", card_fn)   # the chip on a card keeps its job: the filter

    def test_the_thread_shows_the_agents_lines_the_owners_lines_to_it_and_its_open_question(self):
        self.assertIn("function inThread(m, name) { return (m.kind === 'user' && sameName(m.to, name)) || (sameName(m.sender, name) && toOwner(m)); }", HTML)
        tb = body("threadBodyHtml")
        self.assertIn("recentOf(chatMsgs.filter(m => inThread(m, name)), name)", tb)
        self.assertIn("tasks.filter(t => t.needs_input && sameName(t.agent, name))", tb)
        self.assertIn("${quickHtml(t, false)}", tb)   # the card's own chips, answered on the card
        self.assertIn("quickEvents($('thread-body'));", HTML)
        th = body("threadHeadHtml")
        for piece in ("agentState(cards)", "last update", "no card in Doing", "waiting on you", "up for review"):
            self.assertIn(piece, th)

    def test_sending_addresses_the_agent_and_the_thread_redraws_with_chat_and_board(self):
        self.assertIn("sendLine('thread-input', 'thread-goes', 'thread', () => threadName)", HTML)   # the thread's box: the agent reads it (chat-f8)
        self.assertIn("try { await api('/api/chat', body); i.value = ''; showError('');", HTML)        # cleared only once the board took it
        self.assertIn("renderThread();\n  renderPanelConv(); updatePanelDot();\n}", body("renderChat"))
        self.assertIn("renderThread();   // the head reads the cards", HTML)


if __name__ == "__main__":
    unittest.main()
