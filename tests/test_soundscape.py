"""The soundscape, extended (Nov 4): new layers on top of the usual sound, each with its own switch and level, saved in the
browser and OFF until chosen. The cues, the bed, Touch, the volume limiter and the per-view switch sounds are not touched.
Chimes: small sounds for the small moments a render finds (a finished subtask, a % past 25/50/75, a column emptied, a count
changed) and the toast arriving; one per render, the most telling first, never on a first render or your own move."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
LAYERS = re.search(r"const LAYERS = \[(.*?)\n\];", PAGE, re.S).group(1)


def body(name):
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\n}\n", i) + 2]


def layer(id_):
    return LAYERS.split(f"id: '{id_}'")[1].split("\n  { id: '")[0]


class ChimesTests(unittest.TestCase):
    def test_chimes_is_one_fx_row_off_until_chosen_with_a_level_and_a_hear_button(self):
        self.assertIn("{ id: 'chimes', kind: 'fx', name: 'Chimes', about: '", LAYERS)
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1).strip(), "touch: true")   # Touch stays the only default-on layer
        self.assertIn("demo() {", layer("chimes"))
        self.assertNotIn("plain: true", layer("chimes"))                                          # a level slider and Hear it, like every sound row

    def test_every_chime_sits_under_the_quietest_cue_and_goes_through_the_shared_buses(self):
        vols = [float(v) for v in re.findall(r"vol: (\.\d+) \* lvl", layer("chimes"))]
        self.assertTrue(vols and max(vols) <= .015, vols)                                          # the update cue is .013; the tick .014 rides after the done cue
        self.assertNotIn("createOscillator", layer("chimes"))                                      # tone(): dry, reverb send, compressor, limiter
        self.assertIn("tone(p, t + .4, .05,", layer("chimes"))                                     # the subtask tick answers the done cue, not under it

    def test_one_chime_per_render_the_most_telling_first_and_never_on_a_first_render_or_your_own_move(self):
        self.assertIn("const CHIME_RANK = { sub: 0, milestone: 1, empty: 2, count: 3 };", PAGE)
        fl = body("flushChimes")
        self.assertIn("if (!q.length || firstRender) return;", fl)
        self.assertIn("const [kind, agent, n] = q.sort((a, b) => CHIME_RANK[a[0]] - CHIME_RANK[b[0]])[0];", fl)
        self.assertIn("if (kind === 'count' && Date.now() - cueAt < 300) return;", fl)             # a cue in the same breath said it
        self.assertIn("function chime(kind, agent, n) { if (!sndOn || !layerOn('chimes') || firstRender) return;", PAGE)
        self.assertIn("if (Date.now() - lastGestureAt > 1000) { if (emptied) chimeQ.push(['empty']); else if (rolled) chimeQ.push(['count']); }", body("livelyCounts"))
        self.assertIn("function fx(kind, agent) { cueAt = Date.now();", PAGE)

    def test_the_moments_are_found_where_the_cards_are_drawn(self):
        self.assertIn("Math.floor((t.progress || 0) / 25) > Math.floor(lastPct.get(t.id) / 25)) chimeQ.push(['milestone', t.agent, Math.floor((t.progress || 0) / 25)]);", body("card"))
        self.assertIn("if (kjust) chimeQ.push(['sub', k.agent || t.agent]);", body("subsBlock"))
        self.assertIn("  chime('toast');\n", body("toast"))
        self.assertIn("  flushChimes();\n  firstRender = false;", body("render"))
        self.assertIn("const colKey = col => (col.closest('#hud') ? 'hud:' : '') + col.dataset.status;", PAGE)   # the board's Doing and Load's pane are two columns


if __name__ == "__main__":
    unittest.main()


class AmbientAndBalanceTests(unittest.TestCase):
    def test_deep_space_and_tide_are_ambient_layers_off_until_chosen(self):
        for id_, name in (("space", "Deep space"), ("tide", "Tide")):
            self.assertIn(f"{{ id: '{id_}', kind: 'amb', name: '{name}', about: '", LAYERS)
            self.assertIn("start(ctx, out", layer(id_))                                           # they ride the bed's gain like Rain and Wind
            self.assertNotIn(id_, re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1))
        self.assertIn("end: () => clearTimeout(timer)", layer("space"))                            # the pings stop with the layer
        self.assertIn("vol: .006 * lv()", layer("space"))                                            # the ping follows the row's level and stays far under a cue

    def test_duck_the_bed_dips_the_bed_under_every_cue_and_only_the_bed(self):
        d = layer("duck")
        self.assertIn("{ id: 'duck', kind: 'fx', name: 'Duck the bed', about: '", LAYERS)
        self.assertIn("fx(kind, agent, lvl) {", d)                                                 # fx(): after every cue, never after a Touch sound
        self.assertIn("if (!ambNodes || !audio) return;", d)
        self.assertIn("g.linearRampToValueAtTime(Math.max(.15, 1 - .7 * lvl), t + .06); g.linearRampToValueAtTime(1, t + 1.6);", d)
        self.assertIn("const g = ambNodes.gain.gain", d)                                            # the bed's own gain, which every ambient layer also feeds
        self.assertNotIn("master", d)                                                              # the cues, the volume and the limiter are untouched


class FutureSoundTests(unittest.TestCase):
    def test_future_sound_is_its_own_row_off_until_chosen_and_silent_while_the_look_is_off(self):
        self.assertIn("{ id: 'futsnd', kind: 'fx', name: 'Future sound', about: '", LAYERS)
        self.assertIn("function futSound(kind) { if (sndOn && layerOn('futsnd') && layerOn('future')) LAYERS.find(L => L.id === 'futsnd').play(kind, layerLvl('futsnd')); }", PAGE)
        self.assertIn("demo() { this.play('boot', layerLvl('futsnd')); } },", layer("futsnd"))
        for kind in ("'boot'", "'scan'", "'open'", "'close'"):
            self.assertIn(f"kind === {kind}", layer("futsnd"))

    def test_it_follows_its_own_level_through_the_shared_buses(self):
        self.assertIn("lvl } = {}) {", body("hush"))
        self.assertIn("lvl != null ? v * TV * lvl : v * TV * layerLvl('touch')", body("hush"))   # Touch's level stays Touch's
        self.assertEqual(layer("futsnd").count("lvl })"), 4)                                   # every hush in the layer passes its own
        self.assertNotIn("createOscillator", layer("futsnd"))

    def test_the_boot_sweep_waits_for_the_first_gesture_and_the_hooks_sit_beside_touch(self):
        self.assertIn("const wakeBoot = () => { if (sndOn && Date.now() - T0 < 20000 && document.body.classList.contains('future-full')) setTimeout(() => futSound('boot'), 60); };", PAGE)
        self.assertIn("document.addEventListener(ev, wakeBoot, { once: true, capture: true })", PAGE)
        self.assertNotIn("futSound", body("futBoot"))
        self.assertIn("futSound('scan');", body("futScan"))
        self.assertIn("futSound('open');", body("openPanel"))
        self.assertIn("futSound('close');", body("closePanel"))
