"""Board and By agent switch in place (Nov 3): one page drawn two ways, no reload, so the sound never skips. Load already worked that way."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class SeamlessViewsTests(unittest.TestCase):
    def test_the_view_is_a_variable_the_page_flips_in_place(self):
        self.assertIn("let BYAGENT = location.pathname", HTML)
        self.assertIn("function setView(agents, push = true, need = false) {", HTML)   # Needs you is By agent drawn another way: a second flag, the same flip
        self.assertIn("applyView(); renderKeepingCardFocus();", HTML)          # a redraw, not a navigation

    def test_nothing_reloads_the_page_to_change_view(self):
        self.assertNotIn("location.href = BASE + (agents", HTML)
        self.assertNotIn("location.href = BASE + (BYAGENT", HTML)
        self.assertNotIn("e.key === 'a'", HTML)   # Nov 13: the lanes have no key and no tab
        self.assertIn("if (agents !== BYAGENT || need !== MEFIRST) { if (!here) touch('swish'); setView(agents, true, need); }", HTML)   # goView: the tabs, 1 2 3, [ ] and a
        self.assertIn("  if (here) closeHud();", body("goView"))

    def test_the_address_bar_and_back_follow_the_view(self):
        self.assertIn("history.pushState({ view: need ? (nowWatch ? 'watch' : 'need') : agents ? 'agents' : 'board' }, '', BASE + (need ? (nowWatch ? '/watch' : '/need') : agents ? '/agents' : '/') + location.hash);", HTML)
        self.assertIn("window.addEventListener('popstate', () => {", HTML)
        self.assertIn("  nowWatch = watch; setView(agents, false, need);\n});", HTML)

    def test_a_direct_visit_still_lands_on_the_right_view(self):
        self.assertIn("applyView();\nif (BYAGENT) document.title = APP + ' · by agent';", HTML)
        self.assertIn("function applyView() { document.body.classList.toggle('byagent', BYAGENT); litTab(); stripSync(); }", HTML)


if __name__ == "__main__":
    unittest.main()
