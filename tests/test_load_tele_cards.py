"""Load's Agents column (Nov 4): Board cards (pill, age, hour bar) for every agent, the Queue card, the Board's type; nothing the Doing
card says is repeated. Board: a pill hover dims only other agents' cards, and the Show-only hint is the page's own, above the pill."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
CSS = HTML[HTML.index("<style>"):HTML.index("</style>")]


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class AgentsColumnTests(unittest.TestCase):
    def test_the_column_is_a_board_column_with_board_cards(self):
        self.assertIn('<section class="col h-one" aria-label="Agents">\n        <h2>Agents <span class="cnt" id="h-tele-n">0</span><span class="ln-wait" id="ln-wait"></span></h2>\n        <div class="cards h-scroll" id="h-tele"></div>', HTML)
        r = body("renderGrid")
        self.assertIn('const card = a => `<div class="card h-row" data-agent="${hh(a.name)}"><div class="top"><span class="who"><span class="av" aria-hidden="true">${hh(nodeGlyph(a.name))}</span><span class="nm">${hh(a.name)}</span></span><span class="when h-since"></span></div><div class="ln-track"></div></div>`;', r)
        self.assertIn(':is(.col.doing, .col.acol, .h-one) .card:not(.done) {', CSS)   # the Doing tint, border and glow by state
        self.assertIn("r.className = `card h-row ${a.state} ${CARD_STATE[a.state] || ''}`", r)
        for gone in ("h-name", "h-status", "h-ask", "h-recent", "h-card", "h-prgw", "KIND_WORD", "stepsHtml(ask.what"):   # nothing the Doing card says
            self.assertNotIn(gone, r, gone)
        self.assertNotIn("font: 16px/1.45 ui-monospace", CSS)   # the HUD panel no longer sets its own mono face (kbd and code keep theirs)
        self.assertIn('    font: var(--fs-base)/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; font-variant-numeric: tabular-nums;', CSS)   # .hud in the board\'s type

    def test_every_agent_shows_and_the_queue_is_the_last_card(self):
        r = body("renderGrid")
        self.assertIn("const agents = teleOrder(d.agents);", r)
        self.assertNotIn("idle = agents.filter", r)
        self.assertIn('+ `<div class="card h-q" data-status="queue"><div class="top"><span class="nm" id="h-qlab">Queue</span></div><div class="ln-track" id="h-qtrack" title="unclaimed cards in Todo over the hour"></div></div>`;', r)
        self.assertIn("if (ql) ql.textContent = `Queue · ${q.length ? q[q.length - 1] : 0} waiting`;", r)
        self.assertIn(".h-q .ln-track { display: flex; align-items: flex-end; gap: 2px; padding: 0 1px; }", CSS)
        self.assertIn(".h-foot { flex: none; display: flex; flex-wrap: wrap; justify-content: space-between;", CSS)
        self.assertIn(".h-foot .ln-ticks span, .h-foot .ln-ticks span:last-child { position: static; transform: none; }", CSS)

    def test_the_age_and_the_bar_carry_the_state(self):
        r = body("renderGrid")
        self.assertIn("since.classList.toggle('stale', a.state === 'quiet' || a.state === 'abandoned');", r)
        self.assertIn("av.classList.toggle('live', a.state === 'working');", r)
        self.assertIn("const { sg, title } = loadTrack(d, a, win, start, end), tr = r.querySelector('.ln-track');", r)
        self.assertIn("const r = e.target.closest('.h-row.attn[data-id]'); if (!r) return;", HTML)   # a card that needs a person still opens on click


class BoardHoverTests(unittest.TestCase):
    def test_a_pill_hover_dims_only_other_agents_cards(self):
        self.assertIn("boardEl.querySelectorAll('.card').forEach(c => { c.classList.toggle('hl', c.dataset.agent === n); c.classList.toggle('dim', !!c.dataset.agent && c.dataset.agent !== n); });", HTML)
        self.assertIn("boardEl.querySelectorAll('.card.hl, .card.dim').forEach(c => c.classList.remove('hl', 'dim'));", HTML)
        self.assertIn(".board.hl .card.dim { opacity: .4; }", CSS)
        self.assertNotIn(".board.hl .card:not(.hl) { opacity: .4; }", CSS)

    def test_the_show_only_hint_is_the_pages_own_above_the_pill(self):
        self.assertIn('<button class="who" data-agent="${esc(t.agent)}" data-tip="Show only ${esc(t.agent)}" aria-label="Show only ${esc(t.agent)}">', HTML)
        self.assertNotIn('title="Show only ${esc(t.agent)}"', HTML)
        self.assertIn(".who[data-tip]::after { content: attr(data-tip); position: absolute; left: 0; bottom: calc(100% + 6px);", CSS)
        self.assertIn(".who[data-tip]:hover::after, .who[data-tip]:focus-visible::after { opacity: 1; }", CSS)


if __name__ == "__main__":
    unittest.main()
