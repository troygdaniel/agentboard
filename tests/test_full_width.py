"""The board uses the whole window (Nov 3): no page-width cap on Board, By agent or Load; the cards fill their columns."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def rule(selector):
    m = re.search(r"^\s*" + re.escape(selector) + r" \{([^}]*)\}", HTML, re.M)
    assert m, selector
    return m.group(1)


class FullWidthTests(unittest.TestCase):
    def test_the_page_has_no_width_cap(self):
        wrap = rule(".wrap")
        self.assertIn("width: 100%", wrap)
        self.assertNotIn("max-width", wrap)
        self.assertNotIn("margin: 0 auto", wrap)          # centring is what moved the top nav on a wide screen
        self.assertNotIn("min(100%, 1800px)", HTML)

    def test_the_hud_is_not_capped_either(self):
        self.assertNotIn("max-width: 1", rule(".hud"))
        self.assertIn("max-width: none", rule(".hud"))

    def test_cards_fill_their_column_however_wide(self):
        self.assertNotIn("--card-max", HTML)               # a card is as wide as its column on the Board and on By agent (Troy, Nov 3)
        self.assertNotIn(".col:not(.todo) .cards >", HTML)

    def test_the_load_text_column_stops_growing_on_ultrawide(self):
        self.assertIn("@media (min-width: 1800px) { .h-one { --cols: 40px minmax(0, 760px) 100px minmax(200px, 1fr); } }", HTML)


if __name__ == "__main__":
    unittest.main()
