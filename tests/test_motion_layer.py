"""Motion (Nov 3): one Mix layer, off until chosen, that pairs a look with a sound: an agent's card that changed column lands at
the end of its glide with the Touch settle in the agent's voice; the check draws itself in when a card reaches Done; the view
crossfades for the swish. Off, nothing on the page changes; on, the current sound stays as it is and these ride on top."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
LAYERS = re.search(r"const LAYERS = \[(.*?)\n\];", PAGE, re.S).group(1)


def body(name):
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\n}\n", i) + 2]


class MotionLayerTests(unittest.TestCase):
    def test_motion_is_one_mix_row_off_until_chosen_with_a_level_and_a_hear_button(self):
        self.assertIn("{ id: 'motion', kind: 'fx', name: 'Motion', about: '", LAYERS)
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1).strip(), "touch: true")   # Touch is the only default-on layer
        entry = LAYERS.split("id: 'motion'")[1]
        self.assertIn("apply(lvl) { document.body.classList.toggle('motion', lvl > 0); }", entry)
        self.assertIn("demo(ctx) {", entry)
        self.assertIn("TOUCH.drop(t, 'doing', 'AGENT-2', lvl); TOUCH.drop(t + .7, 'done', 'AGENT-2', lvl);", entry)
        # the look follows the saved switch from the first paint, not only once the audio context exists
        self.assertIn("LAYERS.forEach(L => { if (L.apply) L.apply(layerOn(L.id) ? layerLvl(L.id) : 0); });", PAGE)

    def test_a_card_that_changed_column_lands_with_a_settle_unless_you_moved_it(self):
        r = body("render")
        self.assertIn("beforeCol.set(c.dataset.id, c.closest('.col')?.dataset.status)", r)
        self.assertIn("if (layerOn('motion') && Date.now() - lastGestureAt > 1000) beforeCol.forEach((was, id) => {", r)
        self.assertIn("if (c && was !== undefined && c.closest('.col')?.dataset.status !== was) landed(c);", r)
        land = body("landed")
        self.assertIn("TOUCH.drop(t, status, agent, layerLvl('motion'))", land)        # the Touch settle, at Motion's own level
        self.assertIn("if (t != null && layerOn('motion'))", land)                     # SND off or the layer off: nothing
        self.assertIn("}, RM ? 0 : 380);", land)                                        # at the end of the 420 ms glide
        self.assertIn("lastGestureAt = Date.now();", PAGE)

    def test_the_settle_stays_under_the_touch_ceiling(self):
        self.assertIn("vol: v * TV * (o.lvl ?? layerLvl('touch'))", PAGE)             # another layer's level, the same ceiling
        self.assertIn("drop:  (t, status, agent, lvl) =>", PAGE)

    def test_the_check_draws_and_the_view_crossfades_only_with_motion_on(self):
        self.assertIn("body.motion .card.flash.done .check path { stroke-dasharray: 14; stroke-dashoffset: 14; animation: checkdraw .45s .25s ease-out forwards; }", PAGE)
        self.assertIn("if (layerOn('motion') && !RM) $('board').animate([{ opacity: .3 }, { opacity: 1 }], { duration: 220, easing: 'ease-out' });", body("setView"))
        self.assertNotIn("touch(", body("setView"))                                     # the swish comes from goView, as before


if __name__ == "__main__":
    unittest.main()
