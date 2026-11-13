"""The ? list's keys work while Load is open (Nov 3, widened Nov 4): Load's Todo and Doing cards are what the arrows walk, Alt+arrows
and the selection work there too, and the keys that need the board say so."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def fn(name):
    m = re.search(r"function " + name + r"\(.*?\n}\n", HTML, re.S)
    assert m, name
    return m.group(0)


def handler():
    h = HTML[HTML.index("document.addEventListener('keydown', e => {\n  if (e.metaKey"):]
    return h[: h.index("\n});")]


class WalkLoadTests(unittest.TestCase):
    def test_the_arrows_walk_loads_doing_cards_while_load_is_open(self):
        g = fn("cardsGrid")
        self.assertIn("if (hudIsOpen()) return [[...$('h-todo-wrap').querySelectorAll('.card')], [...$('h-cards-box').querySelectorAll('.card')]];", g)
        self.assertIn("$('board').querySelectorAll('.col')", g)   # and the board's columns otherwise

    def test_load_no_longer_returns_before_the_rest_of_the_list(self):
        h = handler()
        load = "if (hudIsOpen() && SOLO && 'nl'.includes(e.key)) return;"   # the pop-out window has no board: n and l stop there; ? and the arrows go on
        self.assertIn(load, h)
        for key in ("f", "h"):   # Nov 13: Load's own two keys are gone with the rest of the cut; its buttons and Esc remain
            self.assertNotIn(f"e.key === '{key}'", h)
        for call in ("toggleKeys()", "toggleAdd(true)", "$('later-btn').click()", "navigate(map[e.key])"):
            self.assertGreater(h.index(call), h.index(load), call)   # all of them come after the Load line

    def test_typing_still_ends_the_handler_before_any_of_it(self):
        h = handler()
        self.assertLess(h.index("if (typing) return;"), h.index("if (hudIsOpen() && SOLO && 'nl'.includes(e.key)) return;"))

    def test_load_without_a_doing_card_leaves_the_arrows_to_scroll_it(self):
        self.assertIn("if (hudIsOpen() && !cardsGrid().some(col => col.length)) return;", handler())

    def test_n_closes_load_to_show_the_field_the_board_owns(self):
        self.assertIn("if (e.key === 'n') { e.preventDefault(); if (hudIsOpen()) closeHud(); toggleAdd(true); return; }", handler())

    def test_the_selection_keys_and_alt_arrows_work_on_load_too(self):
        h = handler()
        self.assertIn("if (e.shiftKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); extendSelectionVertical(", h)
        self.assertNotIn("h !== $('board')", HTML)   # Alt+arrows move cards on Load and By agent as well
        self.assertIn("const keys = h === $('board') && !BYAGENT ? [...$('board').querySelectorAll('.col')].map(x => x.dataset.status) : ['todo', 'doing'];", HTML)


class EscTests(unittest.TestCase):
    def test_the_esc_that_closes_a_card_leaves_load_open(self):
        self.assertIn("closePanel(); e.tookPanel = true;\n});", HTML)
        h = handler()
        self.assertLess(h.index("if (e.tookPanel) return;"), h.index("if (hudIsOpen()) { closeHud(); return; }"))
        self.assertLess(HTML.index("e.tookPanel = true"), HTML.index("document.addEventListener('keydown', e => {\n  if (e.metaKey"))   # the card's own handler runs first


class SheetTests(unittest.TestCase):
    def test_the_list_says_which_keys_leave_or_skip_load(self):
        self.assertIn('<dd id="key-new">New task (leaves Load; not in the pop-out window, nor <kbd>l</kbd>)</dd>', HTML)
        self.assertIn('<dd id="key-alt">Move the card: ← → between columns (Todo, Doing, Done; on Load and By agent, Todo and Doing), ↑ ↓ within one</dd>', HTML)
        self.assertIn('<dd id="key-shiftarrows">Extend the selection</dd>', HTML)

    def test_the_keys_that_work_the_same_everywhere_carry_no_caveat(self):
        for text in ("<dd>Move between cards (on Load: Todo and Doing)</dd>", "<dd>Open card</dd>", '<dd id="key-copy">', '<dd id="key-done">', '<dd id="key-undo">'):
            self.assertIn(text, HTML)


if __name__ == "__main__":
    unittest.main()
