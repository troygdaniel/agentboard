"""The right panel names the card's holder in the same pill as the board card (colour tint, solid disc), not plain text."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class PanelAgentPillTests(unittest.TestCase):
    def test_the_panel_holder_is_a_pill_carrying_the_agent_colour(self):
        self.assertRegex(PAGE, r'<div class="p-who"><span class="agent-pill" style="--c:\$\{colorOf\(t\)\}"><span class="av ')

    def test_the_pill_shares_the_board_pills_rules(self):
        # one selector list per rule, so the two pills cannot drift apart
        for sel in (".top .who, .p-who .agent-pill {",
                    ".top .who .av, .p-who .agent-pill .av {",
                    ".top .who .av.live, .p-who .agent-pill .av.live {"):
            self.assertGreaterEqual(PAGE.count(sel), 1, sel)

    def test_a_long_name_shrinks_the_pill_not_the_time(self):
        self.assertIn(".p-who .p-when { flex: none; white-space: nowrap; }", PAGE)
        self.assertIn('<span class="p-when">', PAGE)


if __name__ == "__main__":
    unittest.main()
