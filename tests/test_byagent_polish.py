"""By agent as polished as the Board (Nov 3): the Doing treatment is by status (running, review, ask), so it is one rule for the
Board's Doing column and By agent's lanes alike: the status-tinted fill, the status border and shadow, the hover glow, the lit
column head. No new colour: the agent's colour stays the lane's top edge and the card's left stripe."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class ByAgentPolishTests(unittest.TestCase):
    def test_the_doing_card_treatment_is_one_rule_for_the_board_column_and_the_lanes(self):
        for rule in (
            ":is(.col.doing, .col.acol) .card:not(.done) {",            # fill, border, shadow
            ":is(.col.doing, .col.acol) .card:not(.done):hover {",      # the hover glow
            ":is(.col.doing, .col.acol) .card.ask:not(.done) { border-color: var(--err); }",
            ":is(.col.doing, .col.acol) .card.review:not(.done) { border-color: var(--ok); }",
            ":is(.col.doing, .col.acol) .card.abandoned:not(.done) { border-color: var(--err); }",
        ):
            self.assertIn(rule, PAGE)
        self.assertNotRegex(PAGE, r"\n  \.col\.doing \.card")          # nothing is Doing-only any more

    def test_a_lane_is_a_lit_column_like_doing(self):
        self.assertIn(".col.doing, .col.acol { border-color: color-mix(in srgb, var(--accent) 14%, var(--line)); }", PAGE)
        self.assertIn(".col.doing::before, .col.acol::before {", PAGE)
        self.assertIn(".col.acol { border-top: 2px solid var(--c, var(--neutral)); }", PAGE)   # the agent's colour stays where it was

    def test_the_tint_is_by_status_not_by_agent(self):
        block = PAGE.split(":is(.col.doing, .col.acol) .card:not(.done) {")[1].split("}")[0]
        self.assertIn("var(--st)", block)
        self.assertNotIn("var(--c)", block); self.assertNotIn("var(--c,", block)   # not the agent colour (var(--card-hi) is the highlight)


if __name__ == "__main__":
    unittest.main()
