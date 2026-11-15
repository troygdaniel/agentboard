"""Esc leaves a text field (14 Nov, card agentboard-esc-leaves-text-field): the first Esc in a text field blurs it and keeps what was typed, so the board's
keys work again without the mouse; the next Esc closes the layer under it. One handler on the window, in the capture phase, ahead of every other Esc handler.

The page is not rendered here (a unit test cannot press a key in a browser): this pins the handler's shape and its place in the file. The real check, with real
key events in headless Chrome on a throwaway board (activeElement is the body, the text is still there, a shortcut now fires, the next Esc peels the layer), is
tests/qa/esc_field_check.mjs: `node tests/qa/esc_field_check.mjs`."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
HANDLER_AT = HTML.index("const escLeavesField = el =>")
HANDLER = HTML[HANDLER_AT: HTML.index("}, true);", HANDLER_AT) + len("}, true);")]


class EscLeavesFieldTests(unittest.TestCase):
    def test_it_is_one_window_handler_in_the_capture_phase(self):
        self.assertIn("window.addEventListener('keydown', e => {\n  if (e.key !== 'Escape' || tourIsOpen() || renameIsOpen()) return;", HANDLER)
        self.assertTrue(HANDLER.rstrip().endswith("}, true);"))

    def test_it_blurs_keeps_the_text_and_stops_the_press(self):
        self.assertIn("e.preventDefault(); e.stopImmediatePropagation(); el.blur();", HANDLER)
        self.assertNotIn(".value =", HANDLER)      # never touches what was typed
        self.assertNotIn("value = ''", HANDLER)

    def test_it_runs_before_every_other_window_capture_handler_for_keys(self):
        for marker in ("window.addEventListener('keydown', e => {   // on Now, the slash talks about the card in front of you; Esc closes the conversation",
                       "window.addEventListener('keydown', e => { if (e.key !== 'Tab' || !e.target.closest?.('#orch-line'))"):
            self.assertIn(marker, HTML)
            self.assertLess(HANDLER_AT, HTML.index(marker), marker)   # an earlier listener on the same target runs first: the talk box's own Esc would otherwise close the conversation in the same press

    def test_which_fields_leave_and_which_keep_their_own_esc(self):
        pred = HTML[HANDLER_AT: HTML.index("window.addEventListener('keydown'", HANDLER_AT)]
        self.assertIn("el.tagName === 'TEXTAREA' || el.isContentEditable", pred)
        self.assertIn("(el.tagName === 'INPUT' && !/^(checkbox|radio|range|button|submit|reset|file|image|color)$/.test(el.type))", pred)
        self.assertNotIn("SELECT", pred)                       # a select keeps its own Esc
        self.assertIn("el.id !== 'title' && el.id !== 'ed-field'", pred)   # the new-task field closes its sheet, the card editor cancels the edit
        self.assertIn("!(el.id === 'mix-search' && el.value)", pred)       # the settings search clears first while it has text

    def test_an_ime_composing_is_never_interrupted(self):
        self.assertIn("if (e.isComposing || e.keyCode === 229) { e.stopImmediatePropagation(); return; }", HANDLER)
        self.assertLess(HANDLER.index("e.isComposing"), HANDLER.index("el.blur()"))   # decided before anything is blurred
        self.assertNotRegex(HANDLER[HANDLER.index("e.isComposing"): HANDLER.index("el.blur()")].split("return; }")[0], r"preventDefault")   # the IME still gets its Esc

    def test_the_fields_that_keep_their_own_esc_still_have_it(self):
        self.assertIn("$('title').onkeydown = e => { if (e.key === 'Escape') { e.stopPropagation(); toggleAdd(false); $('title').blur(); } };", HTML)
        self.assertIn("if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); stopEdit(); }", HTML)
        self.assertIn("else if (e.key === 'Escape' && e.target.value) { e.preventDefault(); e.stopPropagation(); setSearch('');", HTML)

    def test_the_shortcuts_sheet_says_it(self):
        self.assertIn("<dd>Leave a text field (what you typed stays), then close the top layer: a sheet, a drawer, the card, the selection, then Load</dd>", HTML)

    def test_the_other_esc_handlers_are_still_there_for_the_second_press(self):
        self.assertIn("if (e.key === 'Escape' && talkCard && (!typing || e.target.closest?.('#talk')))", HTML)   # the next Esc closes the conversation
        self.assertIn("if ($('chat').classList.contains('open')) { closeChat(); return; }", HTML)              # and the drawer
        self.assertIn("if ($('later').classList.contains('open')) { closeLater(); return; }", HTML)


if __name__ == "__main__":
    unittest.main()
