"""Load shows the board's Doing cards on the left (Nov 3): the same cards, the same design, gliding across on open and close."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class LoadSameCardsTests(unittest.TestCase):
    def test_load_has_a_doing_column_on_the_left_in_the_boards_own_column_markup(self):
        grid = HTML[HTML.index('<div class="h-grid">'):HTML.index('<section class="hp h-one"')]
        self.assertIn('<section class="col doing" id="h-cards" aria-label="Doing"><h2>Doing <span class="cnt" id="h-cards-n">0</span></h2><div class="cards" id="h-cards-box"></div></section>', grid)
        # two columns: the cards, then the agent load; a narrow window stacks them, cards first
        self.assertIn(".h-grid { display: grid; grid-template-columns: minmax(260px, 1fr) minmax(0, 2.2fr);", HTML)
        self.assertIn("@media (max-width: 980px) { .h-grid { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); }", HTML)

    def test_the_pane_is_drawn_by_the_same_card_function_from_the_same_doing_list(self):
        r = body("render")
        self.assertIn("paneHtml = by.doing.length ? by.doing.map(card).join('')", r)
        self.assertIn("box.innerHTML = paneHtml;", r)
        self.assertIn("$('h-cards-n').textContent = by.doing.length;", r)
        self.assertIn("box.querySelectorAll('.card').forEach(c => { c.draggable = false; });", r)
        # subtasks stay folded on Load
        self.assertIn("const open = hudPane ? false : subsOpen.has(t.id) ? subsOpen.get(t.id) : t.status === 'doing';", HTML)
        self.assertIn("hudPane = true; paneHtml = ", r)

    def test_the_pane_takes_the_dark_tokens_and_the_boards_type_scale_whatever_the_theme(self):
        self.assertIn(':root[data-theme="dark"], #h-cards {', HTML)
        self.assertIn("#h-cards { --fs-xs: 11px; --fs-sm: 12px; --fs-md: 13px; --fs-base: 14px; --fs-lg: 15px; --fs-xl: 23px;", HTML)

    def test_cards_glide_between_the_board_and_load(self):
        o, c, r = body("openHud"), body("closeHud"), body("render")
        self.assertIn("$('board').querySelectorAll('.card[data-status=\"doing\"]').forEach(c => glideFrom.set(c.dataset.id, c.getBoundingClientRect()));", o)
        self.assertIn("$('h-cards-box').querySelectorAll('.card').forEach(c => glideFrom.set(c.dataset.id, c.getBoundingClientRect()));", c)
        self.assertIn("renderKeepingCardFocus();", o)
        self.assertIn("renderKeepingCardFocus();", c)
        self.assertIn("glideFrom.forEach((r, id) => before.set(id, r));", r)
        self.assertIn("const c = shown.querySelector(`.card[data-id=\"${CSS.escape(id)}\"]`); if (!c) return;", r)
        # no extra sound: open and close keep their one swish and nothing else
        self.assertEqual(o.count("touch("), 1)
        self.assertEqual(c.count("touch("), 1)
        self.assertNotIn("cue.", o); self.assertNotIn("cue.", c)

    def test_the_cards_controls_work_in_the_pane_as_on_the_board(self):
        self.assertIn("const CARD_HOMES = [$('board'), $('h-cards-box')];", HTML)
        self.assertIn("CARD_HOMES.forEach(h => h.addEventListener('submit'", HTML)
        self.assertIn("CARD_HOMES.forEach(h => h.addEventListener('click'", HTML)
        self.assertIn("CARD_HOMES.forEach(h => h.addEventListener('keydown'", HTML)
        self.assertIn("CARD_HOMES.forEach(quickEvents);", HTML)
        self.assertIn("|| BYAGENT || h !== $('board')) return;", HTML)   # Alt+arrows move cards on the board only


if __name__ == "__main__":
    unittest.main()
