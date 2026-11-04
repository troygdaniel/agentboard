"""Load lines up with the Board (Nov 3): its three columns use the Board's own tracks, so the telemetry sits exactly where Done
sits and the switch moves nothing; the telemetry re-flows by its own width; and Load follows the theme, on the page's own
background, instead of its own black."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
CSS = HTML[HTML.index("<style>"):HTML.index("</style>")]


class TracksTests(unittest.TestCase):
    def test_load_uses_the_boards_tracks_and_gap(self):
        board = re.search(r"'var\(--todo-w\)' : k === 'doing' \? '(minmax\(0, 1\.4fr\))' : '(minmax\(0, 1fr\))'", HTML)
        self.assertTrue(board)
        self.assertIn(f".h-grid {{ --todo-w: clamp(220px, 17vw, 270px); display: grid; grid-template-columns: var(--todo-w) {board.group(1)} {board.group(2)}; grid-template-rows: minmax(0, 1fr); gap: 18px;", CSS)
        self.assertIn(".board { --todo-w: clamp(220px, 17vw, 270px); display: grid; grid-template-columns: var(--tracks, repeat(3, minmax(0, 1fr))); gap: 18px;", CSS)
        self.assertIn("grid-template-rows: minmax(0, 1fr); padding: 18px 28px 22px;", CSS)   # .hud keeps .wrap's padding, so the edges match too

    def test_the_telemetry_reflows_by_its_own_width(self):
        self.assertIn(".h-one { container-type: inline-size; }", CSS)
        self.assertIn('@container (max-width: 760px) {\n    .h-one .h-head, .h-one .h-row, .h-one .h-foot { --cols: 40px minmax(0, 1fr) 90px; grid-template-areas: "av who since" "av load load"; }', CSS)
        self.assertIn("    .h-one .h-head .h-h2 { display: none; }", CSS)
        self.assertIn("@container (max-width: 480px) {\n    .h-one .h-head, .h-one .h-row, .h-one .h-foot { --cols: 32px minmax(0, 1fr) 64px; --gap: 10px; }", CSS)
        self.assertNotIn("@media (max-width: 1100px)", CSS)   # the window's width no longer decides it
        self.assertIn(".h-one .h-row { flex: 1 0 auto; min-height: 108px; }", CSS)


class ThemeTests(unittest.TestCase):
    def test_load_sits_on_the_pages_background_not_its_own_black(self):
        self.assertIn("#hud { position: fixed; inset: 0; top: var(--hdr-b, 0px); z-index: 30; display: none; padding: 0;\n    background:", CSS)
        self.assertIn("      radial-gradient(var(--dot) 1px, transparent 1px) 0 0 / 22px 22px,\n      var(--bg);\n    background-attachment: fixed; }", CSS)
        self.assertIn("    background: none; box-shadow: none;\n    display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); padding: 18px 28px 22px;", CSS)   # .hud
        for gone in ("backdrop-filter: blur(8px)", "#04070c", "repeating-linear-gradient(transparent 0 2px, rgba(0,0,0,.22) 2px 3px)", "radial-gradient(900px 520px at 50% -25%"):
            self.assertNotIn(gone, CSS, gone)
        self.assertEqual(CSS.count("rgba(14,25,38,.74)"), 2)   # only the dark --panel token itself (two theme blocks), no HUD copy of it
        # By agent's column rules stay on the board's columns: with body.byagent set, Load's Todo column (a .col too) was capped at 70vh on a phone
        self.assertIn("body.byagent .board .col { flex: 0 0 86%; min-width: 0; scroll-snap-align: start; max-height: 70vh; }", CSS)
        self.assertIn("body.byagent .board .col { min-width: 220px; }", CSS)
        self.assertIn("body.byagent .board .cards { overflow-y: auto; flex: 1; }", CSS)
        self.assertNotIn("body.byagent .col {", CSS)
        self.assertIn("body.solo #hud { padding: 0; background: var(--bg); }", CSS)

    def test_the_hud_tokens_come_from_the_page_so_both_themes_work(self):
        self.assertIn("    --hbg: var(--bg); --hline: var(--line); --htext: var(--text); --hdim: var(--muted);\n    --hcy: var(--info, #5ee7ff); --hok: var(--ok); --hwarn: var(--warn); --hbad: var(--err);\n    --c0: var(--run);", CSS)
        self.assertIn("--run: #ff9a3c; --warn: var(--hwarn); --ok: var(--hok); --err: var(--hbad); --neutral: #4b5f75; --info: var(--hcy);", CSS)   # dark maps onto the neons: unchanged
        self.assertIn("--run: #c2570c; --warn: #b45309; --ok: #15803d; --err: #b42318; --neutral: #a8a29e; --info: #1d4ed8;", CSS)                  # light: the board's set
        self.assertIn("background: var(--panel); box-shadow: inset 0 1px 0 var(--panel-hi), var(--panel-sh);   /* the Board's column panel", CSS)
        self.assertNotIn("rgba(110,190,255,.17)", CSS); self.assertNotIn("rgba(110,190,255,.14)", CSS)
        self.assertIn("? c : 'var(--hcy)'; }", HTML)   # hudColor's fallback
        self.assertNotIn('#h-cards, #h-todo-wrap {   /* #h-cards', CSS)   # the Todo and Doing columns follow the theme like the Board's


if __name__ == "__main__":
    unittest.main()
