"""By agent's Load strip (Nov 9): one gauge per agent for the last hour plus a trend line, above the lanes. Source checks on the page; the
look and the click-to-lane scroll were checked in a real browser (light, dark, 390 and 1440 wide)."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    m = re.search(r"(?:async )?function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class LoadStripTests(unittest.TestCase):
    def test_the_strip_sits_between_the_header_and_the_lanes_and_starts_hidden(self):
        self.assertIn('<section id="load-strip" hidden', HTML)
        self.assertLess(HTML.index('<section id="load-strip"'), HTML.index('<main class="board" id="board"'))

    def test_only_by_agent_with_load_shut_shows_it(self):
        self.assertIn("#load-strip[hidden], body:not(.byagent) #load-strip, body:has(#hud.open) #load-strip { display: none; }", HTML)
        sync = body("stripSync")
        self.assertIn("BYAGENT && !SOLO && !hudIsOpen()", sync)
        self.assertIn("clearInterval(stripTimer)", sync)   # off everywhere else: the poll stops with the view

    def test_every_change_of_view_re_syncs_it(self):
        self.assertIn("function applyView() { document.body.classList.toggle('byagent', BYAGENT); litTab(); stripSync(); }", HTML)
        for fn in ("openHud", "closeHud"):
            self.assertIn("stripSync();", body(fn), fn)

    def test_it_reads_only_the_load_feed_so_the_work_profile_stays_local(self):
        load = body("stripLoad")
        self.assertEqual(re.findall(r"fetch\(([^,)]*)", load), ["'/api/hud'"])
        strip_js = HTML[HTML.index("// ---- By agent: the Load strip"):HTML.index("// Load is the overlay under the board's own header")]
        self.assertNotIn("http://", strip_js)
        self.assertNotIn("https://", strip_js)

    def test_a_gauge_is_a_button_and_scrolls_to_that_agents_lane(self):
        self.assertIn('<button type="button" class="ls-g ', HTML)
        jump = body("stripJump")
        self.assertIn("c.dataset.status === 'agent:' + name", jump)
        self.assertIn("scrollIntoView", jump)
        self.assertIn("RM ? 'auto' : 'smooth'", jump)   # reduced motion: no smooth scroll

    def test_the_gauge_colours_are_the_lanes_state_colours(self):
        self.assertIn(".ls-g.working { --st: var(--run); }", HTML)
        self.assertIn(".ls-g.review { --st: var(--ok); }", HTML)
        self.assertIn("--st: var(--err); }", HTML)

    def test_the_figures_are_pure_and_the_trend_ends_at_now(self):
        figs = body("stripFigures")
        self.assertIn("STRIP_BUCKETS", figs)
        self.assertIn("s.a <= t && t <= s.b", figs)   # read at each slice's right edge: the last point is now

    def test_the_load_page_stays_reachable(self):
        self.assertIn('id="ls-more"', HTML)
        self.assertIn('id="hud-btn"', HTML)   # and the Load tab itself is untouched


if __name__ == "__main__":
    unittest.main()
