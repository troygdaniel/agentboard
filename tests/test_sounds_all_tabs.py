"""The sounds play on every view (Nov 3): the ambient bed and the Mix layers are not tied to the Load overlay, and there is one bed at a time."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(name):
    i = HTML.index(f"function {name}(")
    return HTML[i:HTML.index("\nfunction ", i + 10)]


class SoundsOnEveryViewTests(unittest.TestCase):
    def test_the_bed_does_not_need_the_load_overlay(self):
        self.assertNotIn("hudIsOpen", body("startAmb"))
        self.assertNotIn("hudIsOpen", body("scheduleBlip"))        # the console chatter follows the bed, not the overlay
        self.assertNotIn("stopAmb", body("closeHud"))              # Load closing leaves the bed alone: it belongs to every view

    def test_a_fresh_page_waits_for_a_gesture_then_plays(self):
        self.assertIn("if (!force && !soundReady()) return;", HTML)
        self.assertIn("const wakeSound = () => { if (sndOn) { ac(); startAmb(true); } };", HTML)
        self.assertIn("['pointerdown', 'keydown'].forEach(ev => document.addEventListener(ev, wakeSound, { once: true, capture: true }));", HTML)

    def test_one_bed_at_a_time_across_pages_and_windows(self):
        self.assertIn("new BroadcastChannel('agentboard-bed')", HTML)
        self.assertIn("claimBed(); scheduleBlip(); startLayers();", HTML)       # starting a bed takes it, any other page hushes
        self.assertIn("if (e.data.claim && e.data.claim !== bedId) { bedYielded = true; stopAmb(); }", HTML)
        self.assertIn("addEventListener('pagehide'", HTML)                      # the page holding it hands it on when it closes

    def test_the_toggle_and_the_key_are_the_same_on_every_view(self):
        self.assertIn("setSnd(sndOn, true); setAmb(ambOn, true);", HTML)       # the buttons show the saved state at load, not only after Load opens
        self.assertIn("if (e.key === 's') { toggleSound(); return; }", HTML)   # one function behind the key and the Settings switch
        self.assertEqual(len(re.findall(r"e\.key === 's'", HTML)), 1)           # one handler, not one per view

    def test_who_is_working_has_one_rule_on_the_board_and_under_the_sound(self):
        self.assertEqual(HTML.count("function agentState("), 1)
        self.assertIn("const stateFor = n => agentState(doingBy.get(n) || []);", HTML)
        self.assertIn("if (!hudIsOpen()) lastWorking = workingAgents(tasks);", HTML)   # under Load the HUD feed says it, elsewhere the board

    def test_cues_have_one_source_per_view(self):
        self.assertIn("  if (hudIsOpen()) return;\n  const who = id =>", HTML)      # the board's own cues stop while Load is open, as before: nothing plays twice
        self.assertEqual(HTML.count("hudSounds(d);"), 1)


if __name__ == "__main__":
    unittest.main()
