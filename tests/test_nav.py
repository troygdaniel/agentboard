"""One top bar: the same tabs on the summary page, the reports list and every card report, with the board's base path on each link."""
import re
import unittest
from datetime import date
from pathlib import Path

from agentboard import nav, reports, summary
from tests.test_reports import Base as _ReportsBase
from tests.test_reports import HttpTests as _Http


class TabsTests(unittest.TestCase):
    def test_five_tabs_under_the_base_with_the_active_one_marked(self):
        h = nav.tabs("", "summary")
        for href in ('href="/"', 'href="/agents"', 'href="/hud"', 'href="/summary"', 'href="/reports"'):
            self.assertIn(href, h)
        self.assertIn('class="tab on" href="/summary" aria-current=page', h)
        self.assertEqual(h.count("tab on"), 1)
        hb = nav.tabs("/b/work", "reports")
        for href in ('href="/b/work/"', 'href="/b/work/agents"', 'href="/b/work/hud"', 'href="/b/work/summary"', 'href="/b/work/reports"'):
            self.assertIn(href, hb)
        self.assertIn('class="tab on" href="/b/work/reports"', hb)

    def test_the_bar_carries_the_brand_and_an_escaped_context_line(self):
        h = nav.top_bar("/b/x", "board", "Report: <b>bold</b>")
        self.assertIn('href="/b/x/"', h)
        self.assertIn("agentboard", h)
        self.assertIn("Report: &lt;b&gt;bold&lt;/b&gt;", h)
        self.assertNotIn("<b>bold</b>", h)
        self.assertNotIn("http", h)   # same-origin only


STATIC = Path(nav.__file__).parent / "static" / "index.html"


class SameRowTests(unittest.TestCase):
    """The tab row must not move when a tab is clicked: the same order, one brand slot width, and no weight change on the lit tab, in the
    server-rendered bar (nav.py) and in the board's and the HUD's bars (index.html). The positions themselves are checked in a browser."""
    def setUp(self):
        self.html = STATIC.read_text()

    def test_board_and_hud_bars_list_the_four_tabs_in_the_same_order(self):
        rows = re.findall(r'<nav class="ab-tabs" aria-label="Pages">(.*?)</nav>', self.html)
        self.assertEqual(len(rows), 2)   # the board's header and the HUD bar
        for row in rows:
            self.assertEqual(re.findall(r'class="tab[^"]*"[^>]*>([^<]+)</a>', row), ["Board", "By agent", "HUD", "Summary", "Reports"])
        self.assertEqual(re.findall(r">([^<]+)</a>", nav.tabs("", "board")), ["Board", "By agent", "HUD", "Summary", "Reports"])

    def test_every_bar_gives_the_brand_the_same_slot(self):
        slot = "flex: 0 0 106px"
        self.assertIn("flex:0 0 106px", nav.CSS)
        self.assertEqual(self.html.count(slot), 2)   # h1 on the board, .h-brand on the HUD

    def test_the_lit_tab_never_changes_weight(self):
        self.assertNotIn("font-weight:600", nav.CSS.split(".ab-tabs .tab.on")[1].split("}")[0])
        on = re.search(r"\.ab-tabs \.tab\.on \{([^}]*)\}", self.html).group(1)
        self.assertNotIn("font-weight", on)

    def test_the_hud_tabs_keep_only_colours_and_the_shared_size(self):
        hud = re.search(r"\.hud \.ab-tabs \.tab \{([^}]*)\}", self.html).group(1)
        self.assertIn("font-size: 14px", hud)
        self.assertNotIn("min-height", hud)
        self.assertNotIn("padding", hud)


class AgentsRouteTests(_Http):
    def test_agents_serves_the_board_page(self):
        status, body, _ = self.get("/agents")
        self.assertEqual(status, 200)
        self.assertIn(b"By agent", body)
        self.assertIn(b'id="tab-agents"', body)


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
