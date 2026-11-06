"""The Terminal tab (Nov 6): the agent panel's second tab shows the session's transcript from /api/transcript, read only, as it scrolls."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class TerminalTabTests(unittest.TestCase):
    def test_the_panel_has_two_tabs_and_opens_on_the_conversation(self):
        aside = re.search(r'<aside id="thread".*?</aside>', HTML, re.S).group(0)
        self.assertIn('role="tablist"', aside)
        self.assertIn('data-th-tab="chat">Conversation</button>', aside)
        self.assertIn('data-th-tab="term">Terminal</button>', aside)
        self.assertIn('<div class="term-foot" id="term-foot" hidden></div>', aside)
        self.assertIn("if (!same) setThreadTab('chat'); else renderThread();", body("openThread"))

    def test_the_terminal_polls_the_route_only_while_it_is_showing(self):
        lt = body("loadTerm", "async function")
        self.assertIn("if (!c || !c.name || !$(c.aside).classList.contains('open') || !$(c.aside).classList.contains('term')) return;", lt)
        self.assertIn("fetch('/api/transcript?agent=' + encodeURIComponent(c.name), { cache: 'no-store' })", lt)
        self.assertIn("if (text === termRaw || termCtx !== c) return;", lt)   # no redraw when nothing changed, or when the terminal moved on
        st = body("setThreadTab")
        self.assertIn("startTerm({ name: threadName, aside: 'thread', body: 'thread-body', foot: 'term-foot' })", st)
        self.assertIn("function stopTerm() { clearInterval(termTimer); termTimer = null;", HTML)
        self.assertIn("termTimer = setInterval(loadTerm, TERM_POLL_MS); }", body("startTerm"))
        self.assertIn("if (termCtx?.aside === 'thread') stopTerm(); }", body("closeThread"))
        self.assertIn("if (threadTab === 'term') return;", body("renderThread"))   # the conversation's redraw never touches the well

    def test_lines_draw_by_kind_in_a_dark_mono_well_and_it_fails_soft(self):
        tl = body("termLineHtml")
        self.assertIn("e.kind === 'tool' ? '● '", tl)
        self.assertIn('<div class="term-line ${esc(e.kind)}">', tl)
        self.assertIn("${esc(e.text)}", tl)
        th = body("termHtml")
        self.assertIn("No transcript for ${esc(termCtx?.name || '')} yet", th)
        self.assertIn("registers its transcript when it next claims or starts a card", th)
        self.assertIn(".term-well { flex: 1; min-height: 0; border-radius: 12px; background: #0f1722; color: #d6e9ff; font: var(--fs-sm)/1.6 ui-monospace, Menlo, monospace;", HTML)
        self.assertIn(".term-line.tool { color: #7f95ad; }", HTML)

    def test_it_is_read_only(self):
        self.assertIn("#thread.term #thread-form, #chat.term #chat-form { display: none; }", HTML)
        self.assertIn("read only, the same session as the window on your desk", body("termFoot"))
        self.assertNotIn("/api/terminal", HTML)   # nothing posts to the session


if __name__ == "__main__":
    unittest.main()
