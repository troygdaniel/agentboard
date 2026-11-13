"""Every shortcut works on every view (4 Nov): the arrows walk Load's Todo and Doing and never crash on a card outside the grid,
focus survives a poll in the pane it was in (and on a control inside a card), Alt+arrows move cards on Load and By agent and
never while typing, the selection paints wherever the card is shown with its bar floating above Load, Esc peels one layer at
a time (a field, a sheet, the card, the selection, then Load), a switch or slider is not typing, the pop-out keeps the keys
that make sense there, and the shortcuts sheet says what the handlers do."""
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


class ArrowsTests(unittest.TestCase):
    def test_loads_grid_is_todo_then_doing(self):
        self.assertIn("if (hudIsOpen()) return [[...$('h-todo-wrap').querySelectorAll('.card')], [...$('h-cards-box').querySelectorAll('.card')]];", fn("cardsGrid"))
        self.assertIn("if (hudIsOpen() && !cardsGrid().some(col => col.length)) return;", handler())

    def test_a_card_outside_the_grid_starts_the_walk_instead_of_crashing(self):
        nav_ = fn("navigate")
        self.assertIn("let ci = cur ? grid.findIndex(col => col.includes(cur)) : -1;", nav_)
        self.assertIn("if (ci < 0) { const first = grid.find(col => col.length); return focusCard(first?.[0]); }", nav_)


class FocusTests(unittest.TestCase):
    def test_focus_comes_back_to_the_same_control_in_the_same_pane(self):
        self.assertIn("const focusBack = focusSnapshot();", HTML)
        self.assertIn("  focusRestore(focusBack);", HTML)
        self.assertIn("function renderKeepingCardFocus() { render(); }", HTML)
        snap = fn("focusSnapshot")
        self.assertIn("const card = el.closest('.card'), home = homeOf(el);", snap)
        self.assertIn("return { home: home.id, id, sel };", snap)
        self.assertIn("const homeOf = el => el?.closest?.('#board, #h-cards-box, #h-todo-wrap') || null;", HTML)
        self.assertNotIn("$('board').querySelector(`.card[data-id=\"${CSS.escape(focusId)}\"]`)", HTML)   # the board-only lookup is gone


class MoveAndSelectTests(unittest.TestCase):
    def test_alt_arrows_move_on_load_and_by_agent_and_not_while_typing(self):
        self.assertIn("if (!c || !e.altKey || !e.key.startsWith('Arrow') || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;", HTML)
        self.assertIn("const keys = h === $('board') && !BYAGENT ? [...$('board').querySelectorAll('.col')].map(x => x.dataset.status) : ['todo', 'doing'];", HTML)
        self.assertNotIn("|| BYAGENT || h !== $('board')", HTML)

    def test_the_selection_paints_everywhere_and_its_bar_floats_above_load(self):
        self.assertIn("CARD_HOMES.forEach(h => h.querySelectorAll('.card').forEach(c => c.classList.toggle('selected', selected.has(c.dataset.id))));", fn("renderSelection"))
        self.assertRegex(HTML, r"#bulkbar \{[^}]*position: fixed;[^}]*z-index: 35;")
        self.assertIn("body:has(#bulkbar.open) #toast { bottom: 84px; }", HTML)
        self.assertIn("if (e.shiftKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); extendSelectionVertical(", handler())


class EscAndTypingTests(unittest.TestCase):
    def test_esc_peels_one_layer_at_a_time(self):
        h = handler()
        order = [h.index(x) for x in ("if (e.tookPanel) return;", "toggleKeys(false)", "toggleMix(false)", "closeLater()", "closeChat()", "clearSelection()", "closeHud()")]
        self.assertEqual(order, sorted(order))   # a selection clears before Load closes
        card = HTML[HTML.index("document.addEventListener('keydown', e => {   // Esc on an open card"):]
        card = card[: card.index("\n});")]
        self.assertIn("if ($('keys').classList.contains('on') || mixIsOpen() || tourIsOpen()) return;", card)              # a sheet over the card closes first
        self.assertIn("if (el && el.closest('#p-body') && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) { el.blur(); e.tookPanel = true; return; }", card)
        self.assertIn("if (e.key === 'Escape') { e.stopPropagation(); toggleAdd(false); $('title').blur(); }", HTML)

    def test_a_switch_or_slider_is_not_typing(self):
        self.assertIn("(el.tagName === 'INPUT' && !/^(checkbox|radio|range|button|submit)$/.test(el.type))", fn("isTyping"))
        self.assertIn("const typing = isTyping();", handler())

    def test_c_and_d_aim_the_same_way_and_never_at_a_telemetry_row(self):
        self.assertIn("return c && !c.classList.contains('h-row') ? c.dataset.id : null;", fn("aimedCard"))

    def test_the_pop_out_keeps_the_keys_that_make_sense_there(self):
        self.assertIn("if (hudIsOpen() && SOLO && 'nl'.includes(e.key)) return;", handler())   # Nov 13: a went with the lanes' key

    def test_opening_a_card_closes_both_drawers(self):
        self.assertIn("$('later').classList.remove('open'); $('chat').classList.remove('open');", fn("openPanel"))


class SheetTests(unittest.TestCase):
    def test_the_sheet_matches_the_handlers(self):
        for text in ("<dd>Move between cards (on Load: Todo and Doing)</dd>", "<kbd>Enter</kbd> / <kbd>Space</kbd></dt><dd>Open card</dd>",
                     '<dd id="key-alt">Move the card: ← → between columns (Todo, Doing, Done; on Load and By agent, Todo and Doing), ↑ ↓ within one</dd>',
                     '<dd id="key-shiftarrows">Extend the selection</dd>', "<dd>Close the top layer: a sheet, a drawer, a field, the card, the selection, then Load</dd>",
                     "<kbd>⌘/Ctrl</kbd> + <kbd>Enter</kbd></dt><dd>Send the reply you are typing on the open card"):
            self.assertIn(text, HTML, text)
        self.assertNotIn("(Board only)", HTML)
        self.assertNotIn("(not on Load)", HTML)


if __name__ == "__main__":
    unittest.main()
