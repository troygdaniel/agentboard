"""Load uses the same simple tab-switch sound as Board and By agent (Nov 3): one swish per view change, never a chime on top."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class LoadSwitchSoundTests(unittest.TestCase):
    def test_opening_and_closing_load_play_the_tab_swish_and_nothing_else(self):
        self.assertIn("if (!SOLO) touch('swish');", body("openHud"))
        self.assertIn("  touch('swish');", body("closeHud"))
        self.assertNotIn("cue.open", body("openHud"))
        self.assertNotIn("cue.close", HTML)   # the chime is gone, not just unused

    def test_one_sound_per_switch_whichever_views_are_involved(self):
        go = body("goView")
        # Board or By agent to Load: openHud's swish is the only sound
        self.assertIn("if (i === 2) { if (!here) openHud(); return; }", go)
        # Load to Board or By agent: closeHud's swish is the only sound, so the in-place flip stays quiet when Load was open
        self.assertIn("if (agents !== BYAGENT) { if (!here) touch('swish'); setView(agents); }", go)
        self.assertIn("if (here) closeHud();", go)
        # Back and Forward: the same swish, only when the view actually changes
        pop = HTML[HTML.index("window.addEventListener('popstate'"):]
        pop = pop[:pop.index("});") + 3]
        self.assertIn("if (agents !== BYAGENT && !SOLO) touch('swish');", pop)
        self.assertIn("setView(agents, false);", pop)
        # setView itself never sounds: the callers decide, so nothing plays twice
        self.assertNotIn("touch(", body("setView"))

    def test_the_swish_is_the_touch_layers_tab_sound(self):
        self.assertIn("swish: t => hush(t, .1, { from: 700, to: 3200, v: 1, verb: .6 }),", HTML)

    def test_the_bed_is_not_touched_by_a_switch(self):
        for fn in ("openHud", "closeHud", "goView", "setView"):
            self.assertNotIn("stopAmb", body(fn), fn)
            self.assertNotIn("startAmb", body(fn), fn)


if __name__ == "__main__":
    unittest.main()
