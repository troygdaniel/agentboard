"""Phone tap targets (sweep-ux, 15 Nov). At 390px the controls a finger uses on the Now card and in Settings were 16 to 23px tall; WCAG 2.5.8 asks for 24px, and a card behind the front
one is drawn at 75%, so they now ask for 32. A unit test cannot measure a layout, so this pins the one phone block; the real check, every one of them measured at 390px in headless Chrome
on a throwaway board, is tests/qa/tap_targets_check.mjs: `node tests/qa/tap_targets_check.mjs`."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class TapTargetTests(unittest.TestCase):
    def block(self):
        at = HTML.index("/* tap targets on a phone (sweep-ux)")
        start = HTML.index("@media (max-width: 700px) {", at)
        return HTML[start: HTML.index("\n  }\n", start)]

    def test_the_block_is_for_a_phone_only(self):
        self.assertIn("@media (max-width: 700px) {", self.block())

    def test_the_card_controls_and_the_settings_search_ask_for_32px(self):
        b = self.block()
        self.assertIn("body .who, body .you-h, body .qr-ch, body .subs-toggle { min-height: 32px; }", b)
        self.assertIn("body #mix-search { min-height: 32px; }", b)

    def test_the_settings_switches_are_24px(self):
        self.assertIn("body .mix-row > input[type=checkbox] { width: 24px; height: 24px; }", self.block())

    def test_they_beat_the_desktop_sizes_that_come_later_in_the_file(self):
        # the desktop rules (.qr-ch min-height 28px, .mix-row > input 16px) come after this block, so the phone rules carry "body" to win on specificity
        self.assertGreater(HTML.index(".qr-ch { border: 1px solid var(--line)"), HTML.index("/* tap targets on a phone (sweep-ux)"))
        self.assertIsNone(re.search(r"min-height: 32px; \}\s*\n\s*\.who", self.block()))


if __name__ == "__main__":
    unittest.main()
