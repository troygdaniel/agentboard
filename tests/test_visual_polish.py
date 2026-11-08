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


def _luminance(color):
    h = color.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def _ratio(a, b):
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + .05) / (y + .05)


def _tokens(block):
    return dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})(?![0-9a-fA-F])", block))


class TheReportPagesKeepTheirContrast(unittest.TestCase):
    """The server-rendered pages (a card's report, the reports list, the summary) carry their own tokens. Mark done was white on mint, 2.22:1, in dark."""

    def setUp(self):
        from agentboard import reports
        css = reports.CSS
        self.light = _tokens(re.search(r"^:root\{color-scheme:light dark;([^}]*)\}", css, re.M).group(1))
        self.dark = _tokens(re.search(r"prefers-color-scheme:dark\)\{:root:not\(\[data-theme=\"light\"\]\)\{([^}]*)\}", css).group(1))
        self.dark_forced = _tokens(re.search(r"^:root\[data-theme=\"dark\"\]\{color-scheme:dark;([^}]*)\}", css, re.M).group(1))
        self.css = css

    def test_the_dark_theme_is_defined_the_same_way_twice(self):
        self.assertEqual(self.dark, self.dark_forced)

    def test_mark_done_text_clears_4_5_on_its_green_in_both_themes(self):
        for name, t in (("light", self.light), ("dark", self.dark)):
            self.assertGreaterEqual(_ratio(t["on-ok"], t["ok"]), 4.5, name)
        self.assertIn("button.go{background:var(--ok);color:var(--on-ok)", self.css)

    def test_links_muted_text_and_the_state_chip_clear_4_5_in_both_themes(self):
        for name, t in (("light", self.light), ("dark", self.dark)):
            for fg, bg in (("ac", "bg"), ("ac", "card"), ("mut", "bg"), ("mut", "card"), ("ok", "card"), ("err", "bg")):
                self.assertGreaterEqual(_ratio(t[fg], t[bg]), 4.5, f"{name}: --{fg} on --{bg}")

    def test_the_brand_link_is_a_24px_target(self):
        from agentboard import nav
        self.assertIn("min-height:24px", re.search(r"\.ab-brand\{([^}]*)\}", nav.CSS).group(1))


class TheBoardKeepsSmallControlsReachable(unittest.TestCase):
    def test_the_error_close_and_the_lane_names_are_24px_targets(self):
        self.assertIn("min-height: 24px", rule("#error button"))
        self.assertIn("min-width: 24px", rule("#error button"))
        self.assertIn("min-height: 24px", rule(".col.acol h2 .nm[data-thread]"))

    def test_the_go_ahead_and_hold_pills_mix_toward_the_text_for_contrast(self):
        for sel, tok in ((".qr-ch.ok", "--ok"), (".qr-ch.hold", "--warn")):
            self.assertIn(f"color: color-mix(in srgb, var({tok}) 78%, var(--text))", rule(sel))


class TheThreadHeadKeepsItsCardTitle(unittest.TestCase):
    def test_the_card_line_is_a_flex_row_and_the_title_shrinks_with_its_own_ellipsis(self):
        # as an inline button inside a line with text-overflow, a title too long for the line was dropped whole: "on ..." and nothing else at 390px
        self.assertIn("display: flex", rule(".th-on"))
        r = rule(".th-on .th-card")
        self.assertIn("text-overflow: ellipsis", r)
        self.assertIn("min-width: 0", r)
        self.assertIn('<span class="th-line th-on">${line2}</span>', HTML)


class ThePhoneHeader(unittest.TestCase):
    def test_it_is_three_rows_not_four(self):
        # at 390 wide the header was logo + tabs, Later alone, the counts, the icons alone: 185px. Later now shares a row with the icons
        # (the spacer between them pushes the icons right), and the counts take their own last line
        m = re.search(r"@media \(max-width: 600px\) \{\s*header \{([^}]*)\}\s*#summary, #filter-summary \{([^}]*)\}\s*\}", HTML)
        self.assertIsNotNone(m, "the phone header block")
        self.assertIn("order: 1", m.group(2))
        self.assertIn("flex: 1 0 100%", m.group(2))

    def test_the_wide_header_is_untouched(self):
        # above 900px the header never wraps and nothing in it moves on a poll (4 Nov): the phone rule must not leak up
        self.assertIn("@media (min-width: 901px) { header { flex-wrap: nowrap; } }", HTML)
        block = re.search(r"@media \(max-width: 600px\) \{\s*header \{[^}]*\}\s*#summary[^}]*\}\s*\}", HTML).group(0)
        self.assertNotIn("min-width", block)


if __name__ == "__main__":
    unittest.main()
