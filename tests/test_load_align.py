"""Load lines up with Board and By agent (Nov 3): the LIVE bar and its alert chips under the tabs are gone, so the Doing column
sits at the same height and left edge on all three views and the switch between them no longer jumps."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
HUD = HTML[HTML.index('<div id="hud" role="dialog"'):HTML.index('<div id="keys"')]


class LoadAlignTests(unittest.TestCase):
    def test_the_live_bar_and_its_chips_are_gone(self):
        for gone in ("h-bar", "h-live", "h-alerts", "h-chip", "LIVE", "OFFLINE", "renderTiles", "setHudLive", "hblink"):
            self.assertNotIn(gone, HTML, gone)
        self.assertIn('<div class="hud" id="hud-inner" tabindex="-1">\n    <button class="h-btn" id="h-full" aria-label="Toggle fullscreen (f)">Fullscreen</button>\n    <div class="h-grid">', HUD)
        self.assertIn("#h-full { display: none; }", HTML)

    def test_the_overlay_takes_the_boards_padding_so_the_doing_column_lands_in_the_same_place(self):
        wrap = re.search(r"\.wrap \{[^}]*padding: (\d+px \d+px \d+px);", HTML).group(1)
        self.assertEqual(wrap, "18px 28px 22px")
        self.assertIn("grid-template-rows: minmax(0, 1fr); padding: 18px 28px 22px;", HTML)          # .hud: one row, .wrap's padding
        self.assertIn("@media (max-width: 900px) { .hud { padding-left: 16px; padding-right: 16px; } }", HTML)
        self.assertIn("padding: 18px 16px 12px; font-size: 14px; }", HTML)                                   # a phone: the same 18px down, 16px in
        self.assertIn(".wrap { height: auto; min-height: 100vh; padding: 18px 16px 40px; }", HTML)   # the board's own 900px gutter, matched above
        self.assertIn("#hud { position: fixed; inset: 0; top: var(--hdr-b, 0px);", HTML)                # the board's header stays; Load starts under it

    def test_a_failed_hud_poll_leaves_the_header_chip_to_say_so(self):
        self.assertIn("} catch (e) { /* the header's Disconnected chip (setStatus, from the board's own poll) says so */ }", HTML)
        self.assertIn('<span class="status off" id="status" role="status" hidden>', HTML)


if __name__ == "__main__":
    unittest.main()
