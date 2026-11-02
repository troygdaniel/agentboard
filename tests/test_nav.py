"""One top bar: the same tabs on the summary page, the reports list and every card report, with the board's base path on each link.
Summary and Reports are not tabs: their links sit in the board's Done column."""
import re
import unittest
from datetime import date
from pathlib import Path

from agentboard import nav, reports, summary
from tests.test_reports import Base as _ReportsBase
from tests.test_reports import HttpTests as _Http


class TabsTests(unittest.TestCase):
    def test_three_tabs_under_the_base_with_the_active_one_marked(self):
        h = nav.tabs("", "agents")
        for href in ('href="/"', 'href="/agents"', 'href="/hud"'):
            self.assertIn(href, h)
        self.assertIn('class="tab on" href="/agents" aria-current=page', h)
        self.assertEqual(h.count("tab on"), 1)
        hb = nav.tabs("/b/work", "hud")
        for href in ('href="/b/work/"', 'href="/b/work/agents"', 'href="/b/work/hud"'):
            self.assertIn(href, hb)
        self.assertIn('class="tab on" href="/b/work/hud"', hb)

    def test_summary_and_reports_are_not_tabs(self):
        for active in ("summary", "reports"):
            h = nav.tabs("", active)
            self.assertNotIn("/summary", h)
            self.assertNotIn("/reports", h)
            self.assertNotIn("tab on", h)   # nothing is lit on those pages

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
    server-rendered bar (nav.py) and in the board's header (index.html), which Load shows too. The positions themselves are checked in a browser."""
    def setUp(self):
        self.html = STATIC.read_text()

    def test_the_page_has_one_tab_row_and_it_lists_the_three_tabs_in_order(self):
        rows = re.findall(r'<nav class="ab-tabs" aria-label="Pages">(.*?)</nav>', self.html)
        self.assertEqual(len(rows), 1)   # the board's header only: Load has no bar of its own, so it cannot differ
        self.assertEqual(re.findall(r'class="tab[^"]*"[^>]*>([^<]+)</a>', rows[0]), ["Board", "By agent", "Load"])
        self.assertEqual(re.findall(r">([^<]+)</a>", nav.tabs("", "board")), ["Board", "By agent", "Load"])

    def test_the_done_column_carries_summary_then_reports_then_clear(self):
        done = re.search(r"const clr = k === 'done' \? (.*?) : '';", self.html).group(1)
        self.assertEqual(re.findall(r'href="\$\{\(window\.AB_BASE \|\| \'\'\)\}(/\w+)"', done), ["/summary", "/reports"])
        self.assertLess(done.index(">Summary</a>"), done.index(">Reports</a>"))
        self.assertLess(done.index(">Reports</a>"), done.index('id="clear-done"'))

    def test_every_bar_gives_the_brand_the_same_slot(self):
        slot = "flex: 0 0 106px"
        self.assertIn("flex:0 0 106px", nav.CSS)
        self.assertEqual(self.html.count(slot), 1)   # h1 in the board's header; Load shows that header, not a copy

    def test_load_shows_the_boards_own_header_instead_of_drawing_another(self):
        hud = self.html[self.html.index('<div id="hud"'):]
        hud = hud[:hud.index('<div class="h-grid">')]
        self.assertNotIn("ab-tabs", hud)
        self.assertNotIn("h-brand", hud)
        self.assertIn("#hud { position: fixed; inset: 0; top: var(--hdr-b, 0px);", self.html)   # the overlay starts under the header
        self.assertIn("document.querySelector('header').getBoundingClientRect().bottom", self.html)
        self.assertIn("body.solo .wrap > :not(header)", self.html)   # the pop-out keeps the header too
        self.assertIn("body:has(#hud.open) :is(#panel, #later, #chat) { z-index: 32; }", self.html)   # Later and Chat open over Load

    def test_the_header_tab_lights_the_view_you_are_on(self):
        self.assertIn("const on = hudIsOpen() ? 'hud-btn' : BYAGENT ? 'tab-agents' : 'tab-board';", self.html)
        self.assertIn("goView(i)", self.html)

    def test_the_later_and_todo_buttons_share_one_width(self):
        self.assertIn("#later-btn { min-width: 96px; }", self.html)   # ORCH sits after it and must not move between Board and By agent

    def test_the_lit_tab_never_changes_weight(self):
        self.assertNotIn("font-weight:600", nav.CSS.split(".ab-tabs .tab.on")[1].split("}")[0])
        on = re.search(r"\.ab-tabs \.tab\.on \{([^}]*)\}", self.html).group(1)
        self.assertNotIn("font-weight", on)


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
        self.assertNotIn("tab on", page)   # a card report is not one of the tabs
        self.assertIn("Report: Trim bundle size", page)
        self.assertLess(page.index("ab-top"), page.index("<main>"))
        lst = reports.index_html(self.s.dir, "/b/work")
        self.assertNotIn("tab on", lst)
        self.assertNotIn('href="/b/work/summary"', lst)
        self.assertIn('href="/b/work/"', lst)
        data = summary.collect(self.s.load(), [], "7d", today=date.today())
        data["project"] = ""
        sm = summary.build_html(data, "/b/work")
        self.assertNotIn("tab on", sm)
        self.assertNotIn('href="/b/work/reports"', sm)
        self.assertIn('href="/b/work/hud"', sm)
        self.assertNotIn('class="btn" href="/b/work/">Board', sm)   # the old lone Board button is gone; the bar has it
        self.assertEqual(cid, "trim-bundle-size")


if __name__ == "__main__":
    unittest.main()
