"""Watch's pager on a short desktop window (sweep2-ux, 16 Nov). The Watch drew three rows of tiles whatever the window's height, with the page arrows and dots 26 px under the last row; the
ORCH line floats over the bottom 67 px of the window, so under about 810 px tall (a laptop) the pager sat behind it and the second page could not be seen or clicked. The page now takes as
many rows as fit above the line, and re-splits when the window is resized. A unit test cannot measure a layout, so this pins the shape of the rule; the real check, the pager hit-tested and
every tile measured against the line in headless Chrome at laptop and desktop sizes and after a resize, is tests/qa/watch_pager_check.mjs: `node tests/qa/watch_pager_check.mjs`."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class WatchPagerTests(unittest.TestCase):
    def rows(self):
        m = re.search(r"const watchFitRows = \(\) => \{.*?\};\n", HTML, re.S)
        self.assertIsNotNone(m, "watchFitRows is missing")
        return m.group(0)

    def test_a_page_is_columns_times_rows(self):
        self.assertIn("const watchPer = () => (innerWidth >= 1180 ? 3 : innerWidth >= 780 ? 2 : 1) * watchFitRows();", HTML)

    def test_the_old_fixed_sizes_are_gone(self):
        self.assertNotIn("innerWidth >= 1180 ? 9 : innerWidth >= 780 ? 6 : 3", HTML)

    def test_a_narrow_window_keeps_three_rows(self):
        # below 780 px the layout is the phone's: this fix is for desktop windows only
        self.assertIn("if (innerWidth < 780) return 3;", self.rows())

    def test_rows_run_from_one_to_three(self):
        self.assertIn("Math.max(1, Math.min(3, Math.floor((innerHeight - 111 - top) / 166)))", self.rows())

    def test_the_numbers_add_up(self):
        # a row is 150 px with a 16 px gap (166 each, the last without the gap); under the last row: 26 px to the pager, the pager's 30 px, and the line's 67 px of the window
        # (18 up, about 49 tall) with 4 px to spare: the pager's bottom is the grid's bottom + 56, so the window must hold the grid + 56 + 67 + 4 = grid + 127, i.e. rows * 166 - 16 + 127 = rows * 166 + 111
        self.assertIn("grid-auto-rows: 150px; gap: 16px", HTML)
        self.assertEqual(56 + 67 + 4 - 16, 111)
        self.assertIn("margin: 8px auto 0; overflow: hidden; padding: 6px 0 44px;", HTML)   # .w-pages: the 44 px under the grid that puts the pager 56 px below it

    def test_the_grid_start_is_measured_when_it_is_drawn(self):
        self.assertIn("document.querySelector('.deck.watch .w-page')", self.rows())
        self.assertIn("getBoundingClientRect().top + scrollY", self.rows())

    def test_a_resize_re_splits_the_pages(self):
        self.assertIn("per = (watchPerWas = watchPer())", HTML)
        self.assertIn("if (document.querySelector('.deck.watch') && watchPer() !== watchPerWas) render();", HTML)
        self.assertIn("addEventListener('resize', () => { clearTimeout(watchResizeT);", HTML)


if __name__ == "__main__":
    unittest.main()
