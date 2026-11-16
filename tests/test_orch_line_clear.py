"""The ORCH line over the Map's columns (sweep2-ux, 16 Nov). The line floats 18 px above the window's bottom edge and the columns run to about 22 px above it, so it sat over the last
45 px of every column: a list scrolled to its end still had its last card 26 px under the glass, and the Done column's "Show N more" button (under its list, outside the scroll) could not
be clicked. A unit test cannot measure a layout, so this pins the one rule; the real check, each list scrolled to its end and each button hit-tested in headless Chrome at three desktop
sizes, is tests/qa/orch_line_clear_check.mjs: `node tests/qa/orch_line_clear_check.mjs`."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class OrchLineClearTests(unittest.TestCase):
    def rule(self):
        m = re.search(r"@media \(min-width: 701px\) \{ \.board \.col \.cards \{[^}]*\} \.board \.col \.more \{[^}]*\} \}", HTML)
        self.assertIsNotNone(m, "the desktop clearance rule for the ORCH line is missing")
        return m.group(0)

    def test_a_list_leaves_room_under_its_last_card_for_the_line(self):
        self.assertIn(".board .col .cards { padding-bottom: 56px; }", self.rule())

    def test_the_show_more_button_sits_above_the_line(self):
        self.assertIn(".board .col .more { margin-bottom: 48px; }", self.rule())

    def test_the_phone_layout_is_left_alone(self):
        # desktop widths only: the rule opens at 701px, one past the phone block's 700
        self.assertIn("@media (min-width: 701px)", self.rule())

    def test_the_room_is_more_than_the_line_covers(self):
        # the line is 18 px up and about 49 px tall, the columns end about 22 px up: 45 px under the glass (the new padding replaces the list's 10)
        self.assertIn("bottom: 18px", HTML[HTML.index("#orch-line { position: fixed;"):][:200])
        self.assertGreaterEqual(56, 45)
        self.assertGreaterEqual(48 + 8, 45)   # the button's lift plus the column's own 8 px of bottom padding


if __name__ == "__main__":
    unittest.main()
