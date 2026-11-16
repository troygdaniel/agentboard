"""The header fits the window (sweep-ux, 15 Nov). With a configuration applied and night mode on, the header carries two chips beside Later and the icons; above 900px it never
wrapped, so at 1280px the Help and Settings buttons sat past the edge of the window and the page scrolled sideways (and at 900 to 1075px even a header with no chips did the same).

A unit test cannot lay a page out, so this pins the three rules that make it fit; the real check, the page walked from 1600px to 760px in headless Chrome with both chips showing and
every visible header control measured against the window, is tests/qa/header_fit_check.mjs: `node tests/qa/header_fit_check.mjs`."""
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class HeaderFitsTests(unittest.TestCase):
    def test_the_header_wraps_until_there_is_room_for_one_line(self):
        self.assertIn("@media (min-width: 1200px) { header { flex-wrap: nowrap; } }", HTML)
        self.assertNotIn("@media (min-width: 901px) { header { flex-wrap: nowrap; } }", HTML)

    def test_the_live_chip_keeps_its_age_for_a_wide_window_and_for_a_slow_or_down_connection(self):
        self.assertIn("@media (max-width: 1399px) { .ab-conn:not(.slow):not(.down) .t { display: none; } }", HTML)

    def test_the_night_chip_is_compact_until_the_wide_window_where_the_configuration_chip_gets_its_words(self):
        self.assertIn(".ab-night .nu, .ab-night .nw { display: none; }", HTML)
        self.assertIn("@media (min-width: 1560px) { .ab-night .nu, .ab-night .nw { display: inline; } }", HTML)
        self.assertIn("@media (min-width: 1560px) { .ab-cfg .cl, .ab-cfg .cw { display: inline; } .ab-cfg .cn { display: none; } }", HTML)   # the same bound
        self.assertIn('<span>${n}<span class="nw"> queued</span></span><span class="nu">until ', HTML)   # the count stays, its word and the end time are the parts that go


if __name__ == "__main__":
    unittest.main()
