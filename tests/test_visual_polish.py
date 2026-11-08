"""Overnight visual polish, round 2 (7 Nov). Each rule here came from a measured audit of a throwaway board in both themes at 1280 and 390
wide (see docs/overnight/overnight-ux-visual-polish.md): contrast, tap targets, accessible names, reduced motion, alignment."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def rule(selector):
    """The declaration text of the first rule whose selector list is exactly `selector`."""
    m = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    return m.group(1) if m else None


class TheAudit(unittest.TestCase):
    def test_a_layer_switch_never_shares_an_id_with_its_section(self):
        # the Touch layer's checkbox was id="mix-touch", the id of the section holding it: its label pointed at the section, so the switch had no name
        self.assertNotIn('id="mix-${L.id}"', HTML)
        self.assertIn('<input type="checkbox" id="lyr-${L.id}"', HTML)
        self.assertIn('<label for="lyr-${L.id}">', HTML)
        for section in ("mix-touch", "mix-amb", "mix-fx", "mix-look"):
            self.assertEqual(HTML.count(f'id="{section}"'), 1, section)

    def test_the_avatar_glow_stops_under_reduced_motion(self):
        # `.top .who .av.live` out-ranked the `.av.live` rule in the reduced-motion block, so five infinite glows kept running
        block = re.search(r"@media \(prefers-reduced-motion: reduce\) \{ \.bar b, \.card \{ transition: none; \}[^\n]*", HTML).group(0)
        self.assertIn(".top .who .av.live", block)
        self.assertIn(".p-who .agent-pill .av.live", block)
        self.assertIn("animation: avglow 3s ease-in-out infinite", HTML)   # the animation the block must beat

    def test_the_todo_copy_button_keeps_its_contrast(self):
        # opacity .75 took Copy prompt to 3.35:1 in the dark theme; the muted colour alone clears 4.5:1. It must be set to 1, not dropped:
        # the base .copy rule is opacity 0 (hover-only), and without the override the todo foot loses its button
        r = rule('.card[data-status="todo"] .copy')
        self.assertIn("opacity: 1", r)
        self.assertNotIn(".75", r)
        self.assertIn("opacity: 0", rule(".copy") or "")

    def test_the_header_counts_are_24px_targets(self):
        r = rule("#summary .sum-link")
        self.assertIn("display: inline-block", r)
        self.assertIn("line-height: 24px", r)

    def test_checkboxes_and_sliders_use_the_page_ink_and_a_real_target(self):
        self.assertIn("accent-color: var(--accent)", rule("input[type=checkbox], input[type=range]"))
        self.assertIn("height: 24px", rule(".mix-row input[type=range]"))
        self.assertIn("width: 16px; height: 16px", rule(".mix-row > input[type=checkbox]"))

    def test_every_settings_row_starts_its_name_at_the_same_place(self):
        # a fixed first column: Volume sat 13px left of Sound because its spacer was narrower than a checkbox
        self.assertIn("grid-template-columns: 18px 1fr 72px auto", rule(".mix-row"))
        self.assertIn("grid-template-columns: 18px 1fr 160px auto", rule(".mix-row.cfg-vol"))
        self.assertNotIn(".mix-row.lv > span:first-child { width", HTML)


if __name__ == "__main__":
    unittest.main()
