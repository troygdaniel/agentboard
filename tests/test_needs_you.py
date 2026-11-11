"""Needs you (Nov 11): the third tab. By agent drawn another way, so the cards and lanes are the ones the other two tabs show: the agents
waiting on the owner first, the rest off the board and grey in the gauge strip. These read the page and the server; the motion itself
(lanes sliding at one size, a lane lifting over the others) is checked in a browser."""
import re
import unittest
from pathlib import Path

from agentboard import cli, nav
from tests.test_reports import HttpTests as _Http

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def body(name):
    return re.search(rf"function {name}\(.*?\n\}}", PAGE, re.S).group(0)


class RouteTests(_Http):
    def test_need_serves_the_board_page_like_the_other_two_views(self):
        for path in ("/", "/agents", "/need"):
            status, page, headers = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(b'id="tab-need"', page, path)
            self.assertIn("Content-Security-Policy", headers, path)

    def test_the_shared_bar_links_to_it(self):
        self.assertIn(("need", "Needs you", "/need"), nav.TABS)
        self.assertEqual(len(nav.TABS), 3)


class ViewTests(unittest.TestCase):
    def test_it_is_by_agent_drawn_another_way_not_another_page(self):
        self.assertIn("let MEFIRST = location.pathname.replace(/\\/+$/, '').endsWith('/need'); if (MEFIRST) BYAGENT = true;", PAGE)
        self.assertEqual(len(re.findall(r"function byAgentHtml\(", PAGE)), 1)   # one builder for the lanes of both tabs
        self.assertNotIn("function needHtml", PAGE)

    def test_one_two_three_open_the_three_tabs_and_the_ring_has_three_views(self):
        self.assertIn("if ((e.key === '1' || e.key === '2' || e.key === '3') && !SOLO && !e.altKey) { e.preventDefault(); goView(+e.key - 1); return; }", PAGE)
        self.assertIn("const curView = () => MEFIRST ? 2 : BYAGENT ? 1 : 0;", PAGE)
        go = body("goView")
        self.assertIn("agents = i >= 1, need = i === 2", go)
        self.assertIn("<kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></dt><dd>Board, By agent, Needs you</dd>", PAGE)

    def test_back_and_forward_follow_the_address(self):
        sv = body("setView")
        self.assertIn("need ? '/need' : agents ? '/agents' : '/'", sv)
        self.assertIn("need = path.endsWith('/need'), agents = need || path.endsWith('/agents')", PAGE)

    def test_agents_waiting_come_first_and_an_answered_card_is_no_longer_yours(self):
        lanes = body("byAgentHtml")
        self.assertIn("t.needs_input ? 0 : t.review ? 1 : 2", lanes)          # asks, then sign-offs, then the rest
        self.assertIn("sentTo(t) ? 2 :", lanes)                               # answered and not yet read: it has left your pile
        self.assertIn("const isBack = n => MEFIRST && laneW(n) === 2 && !lanePeek.has(n);", lanes)
        self.assertIn("shownL.map(agentCol)", lanes)                          # a lane that needs nothing from you is not drawn
        self.assertIn("repeat(${shownL.length}, ${laneWpx}px)", lanes)        # ...and the ones drawn keep By agent's exact width

    def test_the_rule_says_what_how_long_and_what_it_holds(self):
        lanes = body("byAgentHtml")
        self.assertIn("wOf(c) ? 'sign off' : 'answer'", lanes)
        self.assertIn("wOf(c) ? 'frees' : 'holds'", lanes)                    # an ask holds its Todo cards until the card is done; a sign-off frees them
        self.assertIn('class="holds-btn"', lanes)
        self.assertNotIn("if (!MEFIRST || laneW(n) === 2) return '';", lanes)  # By agent shows the same rule, so it stays put across the flip

    def test_lanes_that_stay_slide_at_one_size_and_lanes_that_leave_fade_where_they_stood(self):
        r = body("render")
        self.assertIn("drawBoard.apply(this, arguments)", r)
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)').matches) return out;", r)   # no motion under reduced motion
        self.assertIn("position:fixed", r)                                    # the leaving lane is held where it stood while it fades
        self.assertIn("composite: 'add'", r)                                  # the lift rides on the slide: one curve, no stop at the top
        self.assertNotIn("scaleX", r)                                         # a lane never changes width in flight

    def test_the_gauges_are_the_map_and_the_hidden_agents_go_grey(self):
        g = body("gaugesSync")
        self.assertIn("MEFIRST && laneAway.has(g.dataset.agent)", g)
        self.assertIn(".ls-g.away{filter:grayscale(1);opacity:.38}", PAGE)
        self.assertIn("else if (MEFIRST && laneAway.has(who)) { lanePeek.add(who); render(); }", PAGE)   # a grey gauge brings its lane in
        self.assertIn("if (!BYAGENT) goView(1);", PAGE)                       # from the Board a gauge takes you to the lane

    def test_a_card_lights_what_it_holds_and_a_held_card_lights_its_blocker(self):
        paint = body("linkPaint")
        self.assertIn("held.length ? held : up ? [up] : []", paint)
        self.assertIn("if (!key || key === linkKey) return;", body("linkOn"))  # staying on the same card restarts nothing
        self.assertIn("tb.scrollTo({ top: todoTop", body("linkOff"))          # Todo goes back to where it was

    def test_one_accent_and_nothing_from_outside(self):
        self.assertIn(":root{--need:#e8590c}", PAGE)
        self.assertEqual(PAGE.count("#e8590c"), 1)                            # every other use goes through the variable
        self.assertNotIn("cdnjs", PAGE)
        self.assertNotIn("three.min.js", PAGE)


if __name__ == "__main__":
    unittest.main()
