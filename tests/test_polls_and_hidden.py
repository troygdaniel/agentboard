"""Polls that stole, reset or wiped, and information that hid (4 Nov): only the board redraw waits for typing (the status pill,
the asks, the open card and the chat keep running), the open card is not rebuilt under a focused control or a text selection, the
minute tick waits while text is selected, the Later box is built once, the agent-pill highlight survives a redraw; clipped text
carries a title, the Report chip shows whenever a report exists, Done folds back with Show fewer, the Later drawer and its count
ignore the filter, By agent shows Doing cards that have no agent in an Unassigned lane."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def fn(name):
    m = re.search(r"function " + name + r"\(.*?\n}\n", HTML, re.S)
    assert m, name
    return m.group(0)


class PollTests(unittest.TestCase):
    def test_only_the_board_redraw_waits_for_typing(self):
        load = fn("load")
        self.assertIn("const hold = ae?.id === 'p-reply-text'", load)
        self.assertIn("if (!hold) {", load)
        self.assertNotIn("&& ae.value)) return;", load)                     # the early return that froze the status pill and the chat is gone
        for call in ("setStatus(true);", "checkAsks();", "maybeAutoOpen();", "refreshPanel();"):
            self.assertIn(call, load)
        self.assertIn("else if (minute !== tick && !selectionInside($('board'))) { tick = minute; changed = true; }", load)
        self.assertIn("function selectionInside(el) {", HTML)

    def test_the_open_card_is_not_rebuilt_under_your_hand(self):
        rp = fn("refreshPanel")
        self.assertIn("if (text === detailRaw && (inBody || selectionInside($('p-body')))) return;", rp)
        self.assertIn("if (text !== detailRaw && inBody && /^(SELECT|INPUT)$/.test(ae.tagName)) return;", rp)

    def test_the_later_box_is_built_once(self):
        rl = fn("renderLater")
        self.assertIn("if (!$('later-form')) body.innerHTML =", rl)
        self.assertIn("$('later-list').innerHTML = list.length ?", rl)
        self.assertNotIn("inp.value = typed", rl)

    def test_the_hovered_agent_survives_a_redraw(self):
        self.assertIn("let hoverAgent = null;", HTML)
        self.assertIn("hoverAgent = w.dataset.agent; applyHover();", HTML)
        self.assertIn("hoverAgent = null; applyHover();", HTML)
        self.assertIn("  renderSelection();\n  if (hoverAgent) applyHover();\n}", HTML)


class HiddenInfoTests(unittest.TestCase):
    def test_clipped_text_carries_its_full_text(self):
        self.assertIn('<span class="when ${abandoned ? \'abandoned\' : stale ? \'stale\' : \'\'}" title="${esc(whenText)}">${whenText}</span>', HTML)
        self.assertIn('const queued = todo ? `<span class="when" title="queued ${esc(a.text)}">', HTML)
        self.assertIn('<span class="name" title="${esc(k.title + (st ? \' · \' + st : \'\'))}">', HTML)
        self.assertIn("$('toast-text').textContent = text; $('toast-text').title = text;", HTML)
        self.assertIn('title="${esc(byId.get(m.card)?.title || m.card)}">${esc(byId.get(m.card)?.title || m.card)}</span>', HTML)
        self.assertIn('<span class="who" title="${hh(a.name)}">', HTML)

    def test_the_report_chip_shows_whenever_a_report_exists(self):
        self.assertIn("const reportLink = t.report ? `<a class=\"report-link\" ", HTML)
        self.assertNotIn("t.report && (asking || reviewing || done)", HTML)

    def test_done_folds_back(self):
        self.assertIn("if (showAllDone) more = `<button class=\"more\" id=\"more\">Show fewer</button>`;", HTML)
        self.assertIn("if (e.target.id === 'more') { showAllDone = !showAllDone; render(); $('more')?.focus({ preventScroll: true }); return; }", HTML)

    def test_the_later_drawer_ignores_the_filter(self):
        self.assertIn("const parked = top.filter(t => t.status === 'backlog');", HTML)
        self.assertIn("$('later-n').textContent = parked.length ? '(' + parked.length + ')' : '';", HTML)
        self.assertIn("renderLater(parked);", HTML)

    def test_by_agent_shows_doing_cards_with_no_agent(self):
        self.assertIn("if (doingBy.has('')) active.push('');", fn("byAgentHtml"))
        self.assertIn("${esc(n || 'Unassigned')}</span><span class=\"cnt\">", HTML)
        self.assertIn("function nodeGlyph(n) { if (!n) return '?';", HTML)


if __name__ == "__main__":
    unittest.main()
