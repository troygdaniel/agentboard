"""Mix: extra sound layers on top of the usual sound. Each has its own switch and level, saved in the browser, and is off
until chosen; the default sound (the cue table and the ambient bed) is exactly what it was."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
LAYERS = re.search(r"const LAYERS = \[(.*?)\n\];", PAGE, re.S).group(1)
IDS = re.findall(r"\{ id: '(\w+)', kind: '(amb|fx)'", LAYERS)


class SoundMixTests(unittest.TestCase):
    def test_there_are_layers_of_both_kinds_each_with_a_name_and_a_line_about_it(self):
        self.assertGreaterEqual(len(IDS), 6)
        self.assertEqual({k for _, k in IDS}, {"amb", "fx"})
        self.assertEqual(len({i for i, _ in IDS}), len(IDS))   # ids are unique: they key the saved settings
        self.assertEqual(len(re.findall(r"name: '[^']+', about: '[^']+'", LAYERS)), len(IDS))

    def test_every_layer_is_off_until_chosen_and_the_choice_is_saved_per_browser(self):
        # Touch (the UI sounds) is the one layer that starts on; every other layer is off until chosen, and a saved choice wins
        self.assertIn("const LAYER_ON = { touch: true };", PAGE)
        self.assertIn("const layerOn = id => { const m = mix[id]; return m && m.on != null ? !!m.on : !!LAYER_ON[id]; };", PAGE)
        self.assertIn("return v == null ? 1 : v;", PAGE)                  # a level that was never set is full, not silent
        self.assertIn("localStorage.setItem(MIX_KEY, JSON.stringify(mix))", PAGE)
        self.assertIn("const MIX_KEY = 'agentboard-mix';", PAGE)

    def test_the_mix_sheet_has_a_switch_a_level_and_a_hear_button_per_layer(self):
        self.assertIn('<div id="mix" role="dialog"', PAGE)
        row = re.search(r"const row = L => (.*?);\n", PAGE, re.S).group(1)
        for piece in ('type="checkbox"', 'data-mix="${L.id}"', 'type="range"', 'data-lvl="${L.id}"', 'data-hear="${L.id}"', "${L.about}"):
            self.assertIn(piece, row)
        self.assertIn("if (h) hearLayer(LAYERS.find(L => L.id === h.dataset.hear));", PAGE)

    def test_mix_opens_from_the_gear_and_escape_closes_it_first(self):
        self.assertIn('id="cfg-btn" aria-label="Settings"', PAGE)   # the sheet is Settings now (Nov 3), opened from the gear on every view
        self.assertIn("$('cfg-btn').onclick = () => toggleMix();", PAGE)
        self.assertNotIn("e.key === 'm'", PAGE)   # Nov 13: the gear opens it; the key went with the cut
        self.assertIn("if (mixIsOpen()) { toggleMix(false); return; }", PAGE)

    def test_the_default_sound_is_unchanged(self):
        # the cue table, note for note, and the two switches that were already there
        for line in (
            "open()   { const t = sndNow(); if (t == null) return; tone(587, t, .1, { vol: .028 }); tone(880, t + .09, .12, { vol: .026 }); tone(1175, t + .18, .3, { vol: .022, verb: 1.1 }); },",
            "ask()    { const t = sndNow(); if (t == null) return; tone(784, t, .16, { glide: 1175, vol: .045, verb: 1 }); tone(784, t + .24, .16, { glide: 1175, vol: .04, verb: 1.1 }); },",
            "done()   { const t = sndNow(); if (t == null) return; tone(1047, t, .12, { vol: .032 }); tone(1397, t + .1, .14, { vol: .03 }); tone(2093, t + .22, .4, { vol: .018, verb: 1.4 }); },",
            "try { sndOn = localStorage.getItem('agentboard-snd') !== 'off'; } catch (e) {}",
            "try { ambOn = localStorage.getItem('agentboard-amb') !== 'off'; } catch (e) {}",
            "const h1 = ctx.createOscillator(); h1.frequency.value = 55;",
        ):
            self.assertIn(line, PAGE)
        # the Echo bus is wired but silent until its layer is on; layers only ever follow a default cue, never replace it
        self.assertIn("echo = audio.createGain(); echo.gain.value = 0;", PAGE)
        self.assertIn("cue[k] = agent => { f(agent); fx(k, agent); };", PAGE)

    def test_ambient_layers_start_and_stop_with_the_ambient_bed(self):
        self.assertIn("scheduleBlip(); startLayers();", PAGE)
        self.assertRegex(PAGE, r"function stopAmb\(\) \{\n.*\n  stopLayers\(\);")
        self.assertIn("if (layerNodes[L.id] || L.kind !== 'amb' || !ambNodes) return;", PAGE)


if __name__ == "__main__":
    unittest.main()
