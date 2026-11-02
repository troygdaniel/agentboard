"""Troy's picks from the UX pass (Nov 2): readable idle rows, a pinned Queue row, bigger click areas, no repeated Unassigned, 4.5:1 small labels, "overall" not a sigma."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class LoadTests(unittest.TestCase):
    def test_idle_rows_are_quiet_by_colour_not_by_stacked_opacity(self):
        self.assertIn(".h-row.idle { opacity: .92; filter: saturate(.4); }", PAGE)
        self.assertIn(".h-row.idle .h-name { color: var(--hdim); }", PAGE)
        self.assertIn(".h-row.idle .h-status { opacity: 1; color: var(--hdim); }", PAGE)
        self.assertNotIn(".h-row.idle .h-recent { opacity: .6; }", PAGE)   # .55 x .55 left the status at 30%
        self.assertNotIn(".h-row.idle .h-card { opacity: .7; }", PAGE)

    def test_the_queue_row_is_pinned_to_the_bottom_of_the_scrolling_list(self):
        self.assertIn("position: sticky; bottom: 0; z-index: 2; background: var(--hbg); }", PAGE)


class BoardTests(unittest.TestCase):
    def test_small_controls_get_a_bigger_click_area_without_moving_anything(self):
        self.assertIn(".subs-toggle, .clear-done, .report-link { position: relative; }", PAGE)
        self.assertIn(".subs-toggle::after { content: ''; position: absolute; inset: -6px 0; }", PAGE)
        self.assertIn(".clear-done::after, .report-link::after { content: ''; position: absolute; inset: -4px -2px; }", PAGE)

    def test_the_later_drawer_does_not_repeat_unassigned(self):
        self.assertIn("#later .unas { display: none; }", PAGE)
        self.assertIn(".card[data-status=\"todo\"] .unas { padding-left: 28px; }", PAGE)   # Todo cards on the board still say it

    def test_small_labels_are_mixed_toward_the_text_colour(self):
        self.assertIn("color: color-mix(in srgb, var(--tc, var(--muted)) 78%, var(--text));", PAGE)
        self.assertIn("color: color-mix(in srgb, var(--st, var(--muted)) 78%, var(--text));", PAGE)
        self.assertNotIn("color: var(--muted); opacity: .8; font-variant-numeric", PAGE)   # the day-group count

    def test_a_parents_percent_says_overall_not_sigma(self):
        self.assertNotIn("\\03A3", PAGE)
        self.assertNotIn("'Σ '", PAGE)
        self.assertIn(".pct.computed::after { content: ' overall';", PAGE)
        self.assertIn("<small> overall</small>", PAGE)


if __name__ == "__main__":
    unittest.main()
