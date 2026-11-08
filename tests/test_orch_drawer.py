"""The ORCH drawer (Nov 6): the chat, read as a conversation with ORCH, slides out from the left over the Todo column; ORCH answers the
owner without the agent-talk switch; the ORCH prompt says to wait on its inbox."""
import re
import tempfile
import unittest
from pathlib import Path

from agentboard import nav, prompt
from agentboard.store import BoardError, Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class OwnerAddressingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def test_orch_answers_the_owner_with_the_switch_off(self):
        m = self.s.chat_send("ORCH", "Added to Todo, assigned GENERAL", to=self.s.owner)
        self.assertEqual(m["to"], self.s.owner)
        m = self.s.chat_send("ORCH", "same, any case", to=self.s.owner.upper())
        self.assertEqual(m["to"], self.s.owner.upper())

    def test_talk_between_agents_still_needs_the_switch(self):
        with self.assertRaises(BoardError):
            self.s.chat_send("ORCH", "take the HUD card", to="AGENT-2")
        with self.assertRaises(BoardError):
            self.s.chat_send("ORCH", "with detail", to=self.s.owner, detail="the technical part")   # detail is still talk

    def test_the_owner_reaches_orch_and_orch_reads_it_from_its_inbox(self):
        self.s.chat_send(self.s.owner, "add a card for the HUD legend", kind="user", to="ORCH")
        self.assertEqual([m["text"] for m in self.s.chat_inbox("ORCH")], ["add a card for the HUD legend"])


class DrawerMarkupTests(unittest.TestCase):
    def test_the_drawer_slides_from_the_left(self):
        css = re.search(r"\n  #chat \{[^}]*\}", HTML).group(0)   # the drawer's own rule, not the one it shares with #panel and #later
        for piece in ("left: 0", "right: auto", "transform: translateX(-100%)", "border-right: 1px solid var(--line)"):
            self.assertIn(piece, css)

    def test_the_head_is_the_back_arrow_and_orch_with_no_switches(self):
        aside = re.search(r'<aside id="chat".*?</aside>', HTML, re.S).group(0)
        self.assertIn('aria-label="ORCH"', aside)
        self.assertIn('id="chat-av"', aside)
        self.assertIn('id="chat-close"', aside)
        self.assertNotIn("<label", aside)   # Everyone and Agents talk left the drawer (Troy, Nov 6): the CLI keeps both
        self.assertIn("Tell ORCH what you want", aside)
        for gone in ("chat-all", "chat-sw", "chat-agents", "chatAll", "Agents talk"):
            self.assertNotIn(gone, HTML)

    def test_the_thread_is_what_passes_between_the_owner_and_orch(self):
        self.assertIn("function inOrchThread(m) { return m.via === 'board' || (m.kind === 'user' && (!m.to || m.to === 'all' || isOrch(m.to))) || (isOrch(m.sender) && toOwner(m)); }", HTML)
        self.assertIn("const chatShows = inOrchThread;", HTML)
        self.assertIn("recentOf(chatMsgs.filter(m => !chatHold.has(m.seq) && chatShows(m)), 'ORCH')", body("renderChat"))
        self.assertIn("m.seq > chatSeenSeq && chatShows(m)", HTML)   # the count is what the drawer would show

    def test_sending_addresses_orch_unless_an_at_name(self):
        self.assertIn("const to = text.startsWith('@') ? undefined : 'ORCH';", HTML)
        self.assertIn("api('/api/chat', to ? { text, to } : { text })", HTML)

    def test_the_button_is_caught_on_the_document_and_closing_returns_focus_to_it(self):
        self.assertIn("if (!e.target.closest('.orch-btn')) return;", HTML)
        self.assertIn("document.querySelector('.orch-btn')?.focus()", HTML)
        self.assertIn("!e.target.closest('#chat, .orch-btn, #toast')", HTML)   # a click on the button is not an outside click
        self.assertNotIn("$('chat-btn')", HTML)


class GetStartedTests(unittest.TestCase):
    def test_the_empty_board_shows_three_plain_steps_and_keeps_orch_as_an_option(self):
        w = re.search(r'<div id="welcome">.*?\n  </div>', HTML, re.S).group(0)
        self.assertIn("<h2>Get started</h2>", w)
        top, orch = w.split('<details class="orch-how">')
        steps = re.findall(r"<li>.*?</li>", top, re.S)
        self.assertEqual(len(steps), 3)                                           # add a task, connect an agent, watch it move: no ORCH needed
        self.assertIn('id="welcome-add"', steps[0])
        self.assertIn("<code", steps[1])
        self.assertIn("agentboard instructions", steps[1])
        self.assertIn("CLAUDE.md", steps[1])
        self.assertIn("AGENTS.md", steps[1])
        self.assertIn('id="welcome-demo"', top)                                   # sample cards without the terminal
        self.assertIn('id="welcome-tour"', top)
        self.assertNotIn("ORCH", top)                                             # the first screen needs no jargon
        osteps = re.findall(r"<li>.*?</li>", orch, re.S)                          # ORCH's own three steps, folded away
        self.assertEqual(len(osteps), 3)
        self.assertIn("<code>claude</code>", osteps[0])
        self.assertIn("<code>/rename ORCH</code>", osteps[1])
        self.assertIn('class="btn primary orch-copy"', osteps[2])
        self.assertIn("$('welcome').style.display = tasks.length ? 'none' : 'block';", HTML)   # shown only on a board with no cards

    def test_the_drawer_head_has_copy_prompt_and_the_header_does_not(self):
        aside = re.search(r'<aside id="chat".*?</aside>', HTML, re.S).group(0)
        self.assertIn('class="btn orch-copy"', aside)
        header = re.search(r"<header>.*?</header>", HTML, re.S).group(0)
        self.assertNotIn("orch", header.lower())

    def test_one_copy_handler_serves_every_button_and_respects_the_dispatch_setting(self):
        self.assertIn("const b = e.target.closest('.orch-copy');", HTML)
        self.assertEqual(HTML.count("fetch('/api/orch-prompt')"), 1)
        self.assertIn("b.textContent = 'Copy prompt';", HTML)
        self.assertIn("document.body.classList.toggle('no-dispatch', !c.dispatch);", HTML)
        self.assertIn("body.no-dispatch .orch-copy { display: none; }", HTML)


class MoveCommandTests(unittest.TestCase):
    def test_move_sends_a_card_to_later_and_back(self):
        import contextlib, io, os
        from unittest import mock
        from agentboard import cli
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Readme", status="todo")
            env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
            env["AGENTBOARD_DIR"] = str(s.dir)
            with mock.patch.dict(os.environ, env, clear=True):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.main(["move", "readme", "backlog"])
                self.assertEqual(out.getvalue().strip(), "readme: Later")
                self.assertEqual(Store.get(s.load(), "readme")["status"], "backlog")
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.main(["move", "readme", "todo"])
                self.assertEqual(Store.get(s.load(), "readme")["status"], "todo")


class OrchPromptTests(unittest.TestCase):
    def test_the_orch_prompt_says_to_wait_on_the_drawer_and_answer_there(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            text = prompt.build_orch_prompt(s.load(), s.dir)
        self.assertIn("chat inbox --name ORCH --wait 3600", text)
        self.assertIn('chat send "<one line>" --name ORCH --to', text)
        self.assertIn("talks to you on the board", text)


if __name__ == "__main__":
    unittest.main()
