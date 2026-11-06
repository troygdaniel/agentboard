"""Thread scope and ORCH's terminal (Troy, Nov 6): a thread is what passed between the owner and one name, since the card it is on
now, older behind Show earlier; the ORCH drawer gets the same Terminal tab as the agents."""
import re
import tempfile
import unittest
from pathlib import Path

from agentboard import nav, prompt
from agentboard.store import BoardError, Store, _to_owner

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class OwnerWordsTests(unittest.TestCase):
    def test_the_owner_is_reached_by_name_or_by_the_words_a_prompt_uses(self):
        for to in ("Troy", "troy", "you", "the user", "User", "owner"):
            self.assertTrue(_to_owner(to, "Troy"), to)
        for to in ("all", "AGENT-2", "", None):
            self.assertFalse(_to_owner(to, "Troy"), to)

    def test_an_agent_answers_an_unnamed_owner_with_the_switch_off(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            self.assertEqual(s.owner, "you")
            m = s.chat_send("AGENT-1", "a grey tag beside the name", to="the user")
            self.assertEqual(m["to"], "the user")
            with self.assertRaises(BoardError):
                s.chat_send("AGENT-1", "for a peer", to="AGENT-2")


class ScopeMarkupTests(unittest.TestCase):
    def test_a_thread_is_what_passed_between_you_and_the_name(self):
        self.assertIn("const toOwner = m => { const t = String(m.to || '').toLowerCase(); return !!t && (t === String(OWNER).toLowerCase() || ['you', 'the user', 'user', 'owner'].includes(t)); };", HTML)
        self.assertIn("(sameName(m.sender, name) && toOwner(m))", body("inThread"))
        self.assertNotIn("sameName(m.sender, name) ||", body("inThread"))   # its status lines and mirrored messages stay out
        self.assertIn("(isOrch(m.sender) && toOwner(m))", body("inOrchThread"))

    def test_it_reads_since_the_current_card_else_a_day_with_older_behind_one_link(self):
        ts = body("threadSince")
        self.assertIn("(t.log || []).find(e => e.status === 'doing')?.at || t.created", ts)
        self.assertIn("24 * 3600 * 1000", ts)
        ro = body("recentOf")
        self.assertIn("if (earlierOpen.has(name)) return [msgs, 0];", ro)
        self.assertIn("String(m.at || '').replace('T', ' ') >= since", ro)
        self.assertIn('data-earlier="${esc(name)}">Show earlier · ${n}</button>', HTML)
        self.assertIn("earlierOpen.add(b.dataset.earlier); renderChat();", HTML)
        self.assertIn("earlierHtml('ORCH', older)", body("renderChat"))
        self.assertIn("earlierHtml(name, older)", body("threadBodyHtml"))


class OrchTerminalTests(unittest.TestCase):
    def test_the_drawer_has_the_same_two_tabs_and_its_own_foot(self):
        aside = re.search(r'<aside id="chat".*?</aside>', HTML, re.S).group(0)
        self.assertIn('id="ch-tab-term" aria-selected="false" data-th-tab="term">Terminal</button>', aside)
        self.assertIn('<div class="term-foot" id="chat-foot" hidden></div>', aside)
        self.assertIn("startTerm({ name: 'ORCH', aside: 'chat', body: 'chat-body', foot: 'chat-foot' })", body("setChatTab"))
        self.assertIn("(b.closest('#chat') ? setChatTab : setThreadTab)(b.dataset.thTab)", HTML)
        self.assertIn("#thread.term #thread-form, #chat.term #chat-form { display: none; }", HTML)

    def test_one_terminal_at_a_time_and_the_conversation_waits_under_it(self):
        self.assertIn("if (chatTab === 'term') { renderThread(); return; }", body("renderChat"))
        self.assertIn("if (termCtx && termCtx.aside !== which) stopTerm();", body("setSide"))
        self.assertIn("if (termCtx?.aside === 'chat') stopTerm();", body("closeChat"))
        self.assertIn("if (chatTab === 'term') setChatTab('chat');", body("openChat"))   # the drawer opens on the conversation
        self.assertIn("if (text === termRaw || termCtx !== c) return;", body("loadTerm", "async function"))   # a late answer for the other terminal is dropped

    def test_the_orch_prompt_says_to_name_itself_so_its_terminal_shows(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            text = prompt.build_orch_prompt(s.load(), s.dir)
        self.assertIn("me --name ORCH", text)
        self.assertIn("Terminal", text)


if __name__ == "__main__":
    unittest.main()
