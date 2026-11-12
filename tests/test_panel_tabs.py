"""The card panel's tabs (Troy, Nov 6): Summary / Conversation / Terminal under the title; the terminal's last question shows in
Conversation; a dot, a remembered tab, t to cycle, Jump to latest."""
import json
import re
import unittest
from pathlib import Path

from agentboard import nav, transcript

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class AskParsingTests(unittest.TestCase):
    def test_a_question_put_to_the_person_in_the_terminal_parses_with_its_options(self):
        line = json.dumps({"type": "assistant", "timestamp": "2026-11-06T02:00:00.000Z", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "AskUserQuestion", "input": {"questions": [
                {"question": "Name or number in the header?", "header": "Header", "options": [{"label": "Name"}, {"label": "Number only"}], "multiSelect": False}]}}]}})
        got = transcript.parse_line(line)
        self.assertEqual(got, [{"kind": "ask", "text": "Name or number in the header?", "options": ["Name", "Number only"], "at": "2026-11-06 02:00:00"}])
        plain = transcript.parse_line(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "input": {}}]}}))
        self.assertEqual(plain, [])   # a malformed one draws nothing, never a crash


class TabStripTests(unittest.TestCase):
    def test_the_strip_sits_under_the_title_and_agent_line_on_every_view_of_a_held_card(self):
        ph = body("panelHtml")
        self.assertIn("const tabs = panelTabsHtml(t);", ph)
        self.assertIn("const agentHead = tabs ? `<div class=\"th-head p-th\">${threadHeadHtml(t.agent)}</div>` : '';", ph)   # the compact head the side panel had (Nov 6 revision)
        self.assertIn("if (tabs && panelTab === 'chat') return `${agentHead}${tabs}<div id=\"p-conv\">${panelConvHtml(t)}</div>`;", ph)
        self.assertIn("if (tabs && panelTab === 'term') return `${agentHead}${tabs}<div id=\"p-term\"></div>`;", ph)
        self.assertIn("const headTop = tabs ? (panelEdit === 'title' ? titleHtml : agentHead) : `${titleHtml}${who}`;", ph)   # one head on every tab of a held card
        self.assertIn("return `${headTop}${tabs}${doneHtml(", ph)
        self.assertIn("return `${headTop}${tabs}${askC}${revC}${prog}${carried}${result}", ph)
        self.assertIn("const panelHasTabs = t => !!(t && t.agent && !t.parent_id);", HTML)   # subtasks and unheld cards: the plain view
        strip = body("panelTabsHtml")
        for piece in ("tab('summary', 'Summary')", "tab('chat', 'Conversation', panelTab !== 'chat' && convDot(t))", "tab('term', 'Terminal')", '<kbd>t</kbd> next tab'):
            self.assertIn(piece, strip)

    def test_where_a_card_opens_and_what_is_remembered(self):
        self.assertIn("function tabFor(t) { return !panelHasTabs(t) ? 'summary' : t.needs_input ? 'chat' : (t.review || t.status === 'done') ? 'summary' : rememberedTab(); }", HTML)
        self.assertIn("panelTab = tabFor(byId.get(id));", body("openPanel"))
        self.assertIn("localStorage.setItem('panelTab', tab)", body("setPanelTab"))
        self.assertIn("localStorage.getItem('panelTab')", body("rememberedTab"))

    def test_the_dot_means_new_to_you_and_clears_when_you_look(self):
        cd = body("convDot")
        self.assertIn("!!t.needs_input", cd)
        self.assertIn("m.seq > seen.seq && sameName(m.sender, t.agent) && toOwner(m)", cd)
        self.assertIn("termAsk.at > seen.ask", cd)
        self.assertIn("markConvSeen(t)", body("renderPanel"))
        self.assertIn("localStorage.setItem('convSeen', JSON.stringify(convSeen))", body("markConvSeen"))
        self.assertNotIn("touch(", body("updatePanelDot"))   # no sound, no popup

    def test_the_key_cycles_the_tabs_and_is_on_the_list(self):
        self.assertIn("if (e.key === 't' && openId && panelHasTabs(lastDetail)) { e.preventDefault(); setPanelTab(PANEL_TABS[(PANEL_TABS.indexOf(panelTab) + 1) % PANEL_TABS.length]); return; }", HTML)
        self.assertIn("<dt><kbd>t</kbd></dt><dd>Next tab of the open card: Summary, Conversation, Terminal</dd>", HTML)
        self.assertEqual(HTML.count("e.key === 't'"), 1)

    def test_the_pill_switches_the_tab_inside_the_panel(self):
        self.assertIn("if (b) { if (b.closest('#panel')) setPanelTab('chat'); else openThread(b.dataset.thread); return; }", HTML)


class ConversationTests(unittest.TestCase):
    def test_conversation_is_the_thread_plus_the_terminals_last_question(self):
        self.assertIn("function panelConvHtml(t) { return threadBodyHtml(t.agent) + termAskHtml(t.agent); }", HTML)
        na = body("noteAsk")
        self.assertIn("if (lines[i].kind === 'ask') { ask = lines[i]; break; }", na)
        self.assertIn("last.kind === 'text' && /\\?\\s*$/.test(last.text)", na)   # the agent's last line, when it is a question
        ta = body("termAskHtml")
        self.assertIn("Asked in its terminal", ta)
        self.assertIn('data-say="${esc(o)}"', ta)
        self.assertIn("answer in its window", ta)
        self.assertIn("api('/api/chat', { text: say.dataset.say, to: lastDetail.agent })", HTML)
        self.assertIn("sendLine('p-chat-input', 'p-chat-goes', 'card', () => lastDetail?.agent)", HTML)   # the card's box: the holder reads it (chat-f8)

    def test_the_question_is_read_from_the_terminal_already_drawn_or_polled_lightly(self):
        la = body("loadAsk", "async function")
        self.assertIn("if (termCtx?.aside === 'panel' && termRaw) { try { noteAsk(JSON.parse(termRaw)); }", la)
        self.assertIn("askTimer = setInterval(loadAsk, 5000)", body("openPanel"))
        self.assertIn("clearInterval(askTimer); askTimer = null; termAsk = null;", body("closePanel"))
        self.assertIn("if (c.aside === 'panel') noteAsk(d);", body("loadTerm", "async function"))


class TerminalInPanelTests(unittest.TestCase):
    def test_the_terminal_keeps_your_place_and_offers_jump_to_latest(self):
        lt = body("loadTerm", "async function")
        self.assertIn("const keep = had ? had.scrollTop : (termRestore?.top || 0);", lt)
        self.assertIn("if (w) { w.scrollTop = nearBottom ? w.scrollHeight : keep; if (j) j.hidden = nearBottom; }", lt)
        self.assertIn('<button type="button" class="btn term-jump" hidden>Jump to latest</button>', body("termHtml"))
        self.assertIn("if (oldWell) termRestore = { top: oldWell.scrollTop, nearBottom:", body("renderPanel"))
        self.assertIn("if (text === detailRaw && (minute === panelRefreshTick || panelTab !== 'summary')) return;", body("refreshPanel", "async function"))   # the minute tick never redraws the well

    def test_the_panel_starts_its_agents_terminal_and_stops_it_on_close(self):
        rp = body("renderPanel")
        self.assertIn("startTerm({ name: t.agent, aside: 'panel', body: 'p-term', foot: 'p-term-foot' })", rp)
        self.assertIn("if (termCtx?.aside === 'panel') stopTerm();", body("closePanel"))
        self.assertIn('<div class="term-foot" id="p-term-foot" hidden></div>', HTML)
        self.assertIn('<form id="p-chat-form" class="chat-form" hidden>', HTML)
        self.assertIn(".term-line.ask { color: #ffc857; margin: 8px 0; }", HTML)


if __name__ == "__main__":
    unittest.main()
