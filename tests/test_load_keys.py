"""The ? list's keys work while Load is open (Nov 3): Load's Doing cards are what the arrows walk, and the keys that need the board say so."""
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
        self.assertIn("if (hudIsOpen()) return [[...$('h-cards-box').querySelectorAll('.card')]];", g)
        self.assertIn("$('board').querySelectorAll('.col')", g)   # and the board's columns otherwise

    def test_load_no_longer_returns_before_the_rest_of_the_list(self):
        h = handler()
        load = h[h.index("if (hudIsOpen()) {\n    if (e.key === 'f')"):]
        load = load[: load.index("  }\n") + 4]
        self.assertIn("toggleHudFull(); return;", load)
        self.assertIn("closeHud(); return;", load)
        self.assertNotRegex(load, r"\n\s*return;\s*\n\s*}")   # the only bare return left in the branch is the pop-out's
        self.assertIn("if (SOLO) return;", load)               # the pop-out window keeps its short list: it has no board
        for call in ("toggleKeys()", "toggleAdd(true)", "startEdit('title')", "$('later-btn').click()", "goView(BYAGENT ? 0 : 1)", "navigate(map[e.key])"):
            self.assertGreater(h.index(call), h.index(load.strip()), call)   # all of them come after the Load branch

    def test_typing_still_ends_the_handler_before_any_of_it(self):
        h = handler()
        self.assertLess(h.index("if (typing) return;"), h.index("if (hudIsOpen()) {\n    if (e.key === 'f')"))

    def test_load_without_a_doing_card_leaves_the_arrows_to_scroll_it(self):
        self.assertIn("if (hudIsOpen() && !cardsGrid()[0].length) return;", handler())

    def test_n_closes_load_to_show_the_field_the_board_owns(self):
        self.assertIn("if (e.key === 'n') { e.preventDefault(); if (hudIsOpen()) closeHud(); toggleAdd(true); return; }", handler())

    def test_the_selection_keys_do_nothing_on_load(self):
        h = handler()
        self.assertRegex(h, r"if \(e\.shiftKey && \(e\.key === 'ArrowDown' \|\| e\.key === 'ArrowUp'\)\) \{\n\s+if \(hudIsOpen\(\)\) return;")
        self.assertIn("h !== $('board')", HTML)   # Alt+arrows stay on the board, as they were


class EscTests(unittest.TestCase):
    def test_the_esc_that_closes_a_card_leaves_load_open(self):
        self.assertIn("closePanel(); e.tookPanel = true; }", HTML)
        h = handler()
        self.assertLess(h.index("if (e.tookPanel) return;"), h.index("if (hudIsOpen()) { closeHud(); return; }"))
        self.assertLess(HTML.index("e.tookPanel = true"), HTML.index("document.addEventListener('keydown', e => {\n  if (e.metaKey"))   # the card's own handler runs first


class SheetTests(unittest.TestCase):
    def test_the_list_says_which_keys_leave_or_skip_load(self):
        self.assertIn('<dd id="key-new">New task (leaves Load)</dd>', HTML)
        self.assertIn('<dd id="key-alt">Move the card (Board only)</dd>', HTML)
        self.assertIn('<dd id="key-shiftarrows">Extend the selection (not on Load)</dd>', HTML)

    def test_the_keys_that_work_the_same_everywhere_carry_no_caveat(self):
        for text in ("<dd>Move between cards</dd>", "<dd>Next / previous card</dd>", "<dd>Open card</dd>", '<dd id="key-copy">', '<dd id="key-done">', '<dd id="key-undo">'):
            self.assertIn(text, HTML)


if __name__ == "__main__":
    unittest.main()
