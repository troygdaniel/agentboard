"""The right panel's ask and review boxes wear the colour of the card they belong to, so they are easy to find in the panel."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def rule(selector):
    return re.search(re.escape(selector) + r" \{([^}]*)\}", HTML).group(1)


class PanelColourTests(unittest.TestCase):
    def test_review_box_and_heading_use_the_review_cards_colour(self):
        card = re.search(r"\.card\.review \{ border-color: (var\(--\w+\));", HTML).group(1)
        self.assertEqual(card, "var(--ok)")
        self.assertIn(f"border-color: {card}", rule(".lat.rev"))
        self.assertIn(f"color: {card}", rule(".lat.rev .lat-h b"))
        self.assertIn(f"color: {card}", rule(".pill.revp"))   # the status pill was already the same colour

    def test_ask_box_keeps_the_needs_input_colour(self):
        self.assertIn("border-color: var(--err)", rule(".lat.ask"))
        self.assertIn("color: var(--err)", rule(".lat.ask .lat-h b"))

    def test_the_panel_marks_the_box_by_state(self):
        self.assertIn("""<div class="lat${t.needs_input ? ' ask' : rv ? ' rev' : ''}">""", HTML)


if __name__ == "__main__":
    unittest.main()
