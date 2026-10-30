"""One top bar: the same tabs on the summary page, the reports list and every card report, with the board's base path on each link."""
import unittest
from datetime import date

from agentboard import nav, reports, summary
from tests.test_reports import Base as _ReportsBase


class TabsTests(unittest.TestCase):
    def test_four_tabs_under_the_base_with_the_active_one_marked(self):
        h = nav.tabs("", "summary")
        for href in ('href="/"', 'href="/hud"', 'href="/summary"', 'href="/reports"'):
            self.assertIn(href, h)
        self.assertIn('class="tab on" href="/summary" aria-current=page', h)
        self.assertEqual(h.count("tab on"), 1)
        hb = nav.tabs("/b/work", "reports")
        for href in ('href="/b/work/"', 'href="/b/work/hud"', 'href="/b/work/summary"', 'href="/b/work/reports"'):
            self.assertIn(href, hb)
        self.assertIn('class="tab on" href="/b/work/reports"', hb)

    def test_the_bar_carries_the_brand_and_an_escaped_context_line(self):
        h = nav.top_bar("/b/x", "board", "Report: <b>bold</b>")
        self.assertIn('href="/b/x/"', h)
        self.assertIn("agentboard", h)
        self.assertIn("Report: &lt;b&gt;bold&lt;/b&gt;", h)
        self.assertNotIn("<b>bold</b>", h)
        self.assertNotIn("http", h)   # same-origin only


class PagesTests(_ReportsBase):
    def test_summary_report_and_list_pages_share_the_bar(self):
        cid = self.review()
        page = self.page()
        self.assertIn('class="ab-top"', page)
        self.assertIn('class="tab on" href="/reports"', page)
        self.assertIn("Report: Trim bundle size", page)
        self.assertLess(page.index("ab-top"), page.index("<main>"))
        lst = reports.index_html(self.s.dir, "/b/work")
        self.assertIn('class="tab on" href="/b/work/reports"', lst)
        self.assertIn('href="/b/work/"', lst)
        data = summary.collect(self.s.load(), [], "7d", today=date.today())
        data["project"] = ""
        sm = summary.build_html(data, "/b/work")
        self.assertIn('class="tab on" href="/b/work/summary"', sm)
        self.assertIn('href="/b/work/hud"', sm)
        self.assertNotIn('class="btn" href="/b/work/">Board', sm)   # the old lone Board button is gone; the bar has it
        self.assertEqual(cid, "trim-bundle-size")


if __name__ == "__main__":
    unittest.main()
