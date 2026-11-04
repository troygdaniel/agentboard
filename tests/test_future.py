"""Look > From the future (Nov 4): Off / Subtle / Full, off until chosen, reversible in one click. Subtle is a still look
(holographic panels with corner brackets, a scanline veil at 8%, monospace column heads); Full adds a light along the live
columns' top edge, a header readout, pointer parallax, a tilt on a hovered card, a boot on a page load and a scan on a view
change. Nothing is hidden, nothing new polls the server, and reduced motion stops every movement."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
LAYERS = re.search(r"const LAYERS = \[(.*?)\n\];", PAGE, re.S).group(1)
CSS = PAGE[PAGE.index("/* ===== Look > From the future"):PAGE.index("</style>")]


def body(name):
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\n}\n", i) + 2]


class FutureTests(unittest.TestCase):
    def test_a_look_row_with_three_levels_off_until_chosen(self):
        self.assertIn("{ id: 'future', kind: 'fx', look: true, levels: ['Off', 'Subtle', 'Full'], name: 'From the future', about: '", LAYERS)
        self.assertIn("apply(lvl) { document.body.classList.toggle('future', lvl > 0); document.body.classList.toggle('future-full', lvl >= 1); futureRuntime(lvl >= 1); } },", LAYERS)
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1).strip(), "touch: true")
        self.assertIn("const levelAt = L => !layerOn(L.id) ? 0 : layerLvl(L.id) >= 1 ? 2 : 1;", body("renderMix"))
        self.assertIn('data-level="${L.id}" data-val="${i / (L.levels.length - 1)}" aria-pressed="${levelAt(L) === i}"', body("renderMix"))
        self.assertIn("const id = lv.dataset.level, val = +lv.dataset.val; mix[id] = { on: val > 0, lvl: val > 0 ? val : (mix[id]?.lvl ?? 1) };", PAGE)   # Off keeps the level you had, for the way back

    def test_every_rule_sits_under_the_body_classes_and_hides_nothing(self):
        # every selector starts with the body class, or is one of the look's own elements (.fut-ro, #boot, #scan); a wrapped
        # declaration (a line that starts inside a rule) is skipped as such
        rules = [l.strip() for l in CSS[CSS.index("*/") + 2:].splitlines() if l.strip() and not l.strip().startswith(("@keyframes", "@media", "}", "body.future", ".fut-ro", "#boot", ".boot-box", "#scan", "/*")) and " { " in l and not l.startswith("    ")]
        self.assertEqual(rules, [], rules)
        for line in CSS.splitlines():
            if "display: none" in line:
                self.assertTrue(line.strip().startswith((".fut-ro {", "#boot {", "#scan {")), line)   # nothing of the board's is hidden
        self.assertIn("body.future::after { content: ''; position: fixed; inset: 0; z-index: 70; pointer-events: none; opacity: .08;", CSS)
        self.assertIn("#boot { position: fixed; inset: 0; z-index: 66; display: none; place-items: end center; padding-bottom: 36px; pointer-events: none; }", CSS)
        self.assertIn(".fut-ro { display: none; flex: 0 20 auto; min-width: 0;", CSS)   # the readout gives way before the header's counts do

    def test_full_is_the_moving_half_and_reduced_motion_stops_all_of_it(self):
        for piece in ("body.future-full :is(.col.doing, .col.acol) h2::before", "body.future-full::before", "body.future-full .card:hover", "#boot.on", "#scan.on"):
            self.assertIn(piece, CSS)
        rm = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("body.future-full :is(.col.doing, .col.acol) h2::before, .fut-ro::after, #boot, #boot.out, .boot-box, .boot-box div, #boot #scan { animation: none; }", rm)
        self.assertIn("body.future-full::before { transform: none; }", rm)
        self.assertIn("body.future-full .card:hover { transform: translateY(-2px); }", rm)
        self.assertIn("if (!futBooted && !RM && Date.now() - T0 < 3000) futBoot();", body("futureRuntime"))
        self.assertIn("if (!document.body.classList.contains('future-full') || RM) return;", body("futScan"))
        self.assertIn("if (!document.body.classList.contains('future-full') || RM || futRaf) return;", PAGE)   # the parallax: one frame at a time, Full only

    def test_the_runtime_is_light_and_stops_with_the_level(self):
        rt = body("futureRuntime")
        self.assertIn("clearInterval(futTimer); futTimer = null;", rt)
        self.assertIn("if (!full) { ro.textContent = ''; document.documentElement.style.removeProperty('--px'); document.documentElement.style.removeProperty('--py'); return; }", rt)
        self.assertIn("tickRo(); futTimer = setInterval(tickRo, 1000);", rt)
        self.assertNotIn("fetch(", rt)                                                                        # the readout reads the board's own poll
        self.assertIn("const working = tasks.filter(t => t.status === 'doing' && !isKid(t)).length", rt)       # the header's number
        self.assertIn("['pointerdown', 'keydown'].forEach(ev => document.addEventListener(ev, end, { once: true, capture: true }));", body("futBoot"))
        self.assertIn("litTab(); futScan();", body("openHud"))
        self.assertIn("litTab(); futScan();", body("closeHud"))
        self.assertIn("renderKeepingCardFocus(); futScan();", body("setView"))


if __name__ == "__main__":
    unittest.main()
