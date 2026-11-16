"""Focus goes into a layer when it opens (sweep-ux, 15 Nov): the Later drawer, Settings and the Keys sheet. A unit test cannot press a key in a browser, so this pins the
shape of the three fixes; the real check, with real key events in headless Chrome on a throwaway board, is tests/qa/focus_on_open_check.mjs (`node tests/qa/focus_on_open_check.mjs`).

Why each one: the Later drawer asked for its field while it was still visibility:hidden (the first frame of its slide in), and a focus() on a hidden element does nothing;
Settings focused its tab and then redrew the tab list (the Security and Backup tabs arrive once the board's settings are read), which threw the focused tab away; the Keys sheet
never asked. Each left the keyboard on the page behind the layer."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body_of(start):
    """The text of the function (or block) that begins with `start`, up to its first line that starts with a closing brace."""
    at = HTML.index(start)
    return HTML[at: HTML.index("\n}", at) + 2]


class FocusOnOpenTests(unittest.TestCase):
    def test_a_layer_asks_for_focus_after_it_has_shown_and_only_while_it_is_open(self):
        helper = HTML[HTML.index("function focusWhenShown("): HTML.index("function openLater()")]
        self.assertIn("setTimeout(", helper)                  # a timer: a background tab pauses frames, not timers
        self.assertNotIn("requestAnimationFrame", helper)
        self.assertIn("stillOpen", helper)                    # the layer may have been closed in the meantime
        self.assertIn("el.isConnected", helper)

    def test_the_later_drawer_does_not_focus_its_field_in_the_same_breath_as_it_opens(self):
        line = HTML[HTML.index("function openLater()"): HTML.index("\n", HTML.index("function openLater()"))]
        self.assertIn("focusWhenShown($('later-input')", line)
        self.assertNotIn("$('later-input')?.focus()", line)

    def test_the_settings_tab_list_redraw_hands_focus_back_to_the_tab(self):
        at = HTML.index("const hadFocus = $('mix-tabs').contains(document.activeElement);")
        self.assertLess(at, HTML.index("$('mix-tabs').innerHTML = vis.map("))     # read before the tabs are replaced
        after = HTML[at: HTML.index("\n}", at)]
        self.assertEqual(len(re.findall(r"focus: hadFocus", after)), 2)           # both ways the tab is selected again
        self.assertIn("if (o.focus) b.focus({ preventScroll: true })", HTML)      # selectSettingsTab is what gives it back

    def test_the_keys_sheet_takes_focus_on_its_close_button_and_gives_it_back_to_help(self):
        keys = body_of("function toggleKeys(on)")
        self.assertIn("focusWhenShown($('keys-close')", keys)
        self.assertIn("else if (hadFocus) $('help-btn').focus();", keys)
        self.assertIn("const hadFocus = $('keys').contains(document.activeElement);", keys)


if __name__ == "__main__":
    unittest.main()
