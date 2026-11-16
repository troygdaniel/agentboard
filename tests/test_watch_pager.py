"""Watch's pager on a short desktop window (sweep2-ux, 16 Nov). The Watch drew three rows of 150 px tiles whatever the window's height, with the page arrows and dots 26 px under the last row;
the ORCH line floats over the bottom 67 px of the window, so under about 810 px tall (a laptop) the pager sat behind it and the second page could not be seen or clicked. The owner wants the
three by three kept, so the rows now shrink (150 px down to 120, from the window's height, in CSS); only when even 120 px rows will not fit does a page take two rows, or one. A unit test
cannot measure a layout, so this pins the shape of the rule; the real check, the pager hit-tested and every tile measured against the line in headless Chrome at laptop and desktop sizes and
after a resize, is tests/qa/watch_pager_check.mjs: `node tests/qa/watch_pager_check.mjs`."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class WatchPagerTests(unittest.TestCase):
    def rows(self):
        m = re.search(r"const watchFitRows = \(\) => \{.*?return 1; \};\n", HTML, re.S)
        self.assertIsNotNone(m, "watchFitRows is missing")
        return m.group(0)

    def css(self):
        at = HTML.index("/* a short desktop window (sweep2-ux): the rows shrink")
        return HTML[at: HTML.index("\n", HTML.index("@media (min-width: 780px) and (max-width: 1199px)", at))]

    def test_a_page_is_columns_times_rows(self):
        self.assertIn("const watchPer = () => (innerWidth >= 1180 ? 3 : innerWidth >= 780 ? 2 : 1) * watchFitRows();", HTML)

    def test_the_old_fixed_sizes_are_gone(self):
        self.assertNotIn("innerWidth >= 1180 ? 9 : innerWidth >= 780 ? 6 : 3", HTML)

    def test_the_row_height_is_a_variable_with_the_old_150px_as_its_default(self):
        self.assertIn("grid-auto-rows: var(--w-row, 150px); gap: 16px; align-content: start;", HTML)
        self.assertNotIn("grid-template-columns: repeat(3, minmax(0, 1fr)); grid-auto-rows: 150px;", HTML)

    def test_the_rows_shrink_from_150_to_120_by_the_windows_height_on_desktop_widths_only(self):
        c = self.css()
        self.assertIn("@media (min-width: 780px) { .w-pages { --w-rows: 3; --w-top: 200px; --w-row: clamp(120px, calc((100vh - var(--w-top) - 127px - (var(--w-rows) - 1) * 16px) / var(--w-rows)), 150px); } }", c)
        self.assertIn("@media (min-width: 780px) and (max-width: 1199px) { .w-pages { --w-top: 252px; } }", c)   # the header wraps under 1200 px

    def test_the_page_tells_the_css_how_many_rows(self):
        self.assertIn('<div class="w-pages" style="--w-rows:${watchFitRows()}">', HTML)

    def test_a_narrow_window_keeps_three_rows(self):
        # below 780 px the layout is the phone's: this fix is for desktop windows only
        self.assertIn("if (innerWidth < 780) return 3;", self.rows())

    def test_two_rows_or_one_only_when_120px_rows_will_not_fit(self):
        r = self.rows()
        self.assertIn("const WATCH_ROW_MIN = 120;", HTML)
        self.assertIn("for (let n = 3; n > 1; n--) if ((room - (n - 1) * 16) / n >= WATCH_ROW_MIN) return n;", r)

    def test_the_numbers_add_up(self):
        # under the last row: 26 px to the pager and the pager's 30 px (the pager's bottom is the grid's bottom + 56), then the line's 67 px of the window (18 up, about 49 tall), 4 px to spare:
        # the grid must end 56 + 67 + 4 = 127 px above the window's bottom, and begins 200 px down (252 when the header wraps)
        self.assertEqual(56 + 67 + 4, 127)
        self.assertIn("innerHeight - (innerWidth >= 1200 ? 200 : 252) - 127", self.rows())
        self.assertIn("margin: 8px auto 0; overflow: hidden; padding: 6px 0 44px;", HTML)   # .w-pages: the 44 px under the grid that puts the pager 56 px below it
        self.assertIn("gap: 16px; align-content: start;", HTML)

    def test_a_resize_re_splits_the_pages(self):
        self.assertIn("per = (watchPerWas = watchPer())", HTML)
        self.assertIn("if (document.querySelector('.deck.watch') && watchPer() !== watchPerWas) render();", HTML)
        self.assertIn("addEventListener('resize', () => { clearTimeout(watchResizeT);", HTML)


if __name__ == "__main__":
    unittest.main()
