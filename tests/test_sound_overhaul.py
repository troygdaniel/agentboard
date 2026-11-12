"""The sound overhaul (Nov 12): more layers, a better balance and the settings and UI around them. Every new sound or look is off until
chosen, today's sound (Classic) stays the default, and the cues, the volume limiter and the per-view switch sounds are not touched.
This file grows with each step: layers (Stage, Humanize, Day bookends), then balance (a Cues level and a live output meter)."""
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


class NewLayers(unittest.TestCase):
    def test_stage_humanize_and_day_bookends_are_fx_rows_off_until_chosen(self):
        for id_, name in (("stage", "Stage"), ("human", "Humanize"), ("daybook", "Day bookends")):
            self.assertIn(f"{{ id: '{id_}', kind: 'fx', name: '{name}', about: '", LAYERS)
            self.assertIn("demo(", layer(id_))                                                       # a Hear it button, like every sound row
            self.assertNotIn(id_, re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1))         # nothing new starts on
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1).strip(), "touch: true")

    def test_tone_is_neutral_unless_a_layer_or_a_wrapper_says_otherwise(self):
        t = body("tone")
        self.assertIn("const hu = humanAmt(), st = stageAmt();", t)
        self.assertIn("if (hu) {", t)                                                                # Humanize only when on
        self.assertIn("if (st && panNow) pan = panNow * st;", t)                                     # Stage moves only a sound that asked for a place
        self.assertIn("let panNow = 0, cueMul = 1;", PAGE)                                           # both rest at neutral
        self.assertIn("function fx(kind, agent) { cueAt = Date.now(); panNow = 0; cueMul = 1;", PAGE)  # a layer's own sound is not a cue

    def test_the_humanize_ranges_are_small(self):
        t = body("tone")
        self.assertIn("freq *= 1 + r() * .024 * hu;", t)                                             # about +/-1.2%
        self.assertIn("vol *= 1 + r() * .24 * hu;", t)                                               # +/-12%
        self.assertIn("t0 += Math.random() * .008 * hu;", t)                                         # a few ms, never early

    def test_the_stage_places_cues_and_drops_and_the_default_cue_wrapper_is_untouched(self):
        self.assertIn("Object.keys(cue).forEach(k => { const f = cue[k]; cue[k] = agent => { f(agent); fx(k, agent); }; });", PAGE)
        self.assertIn("const CUE_PAN = { start: -.35, added: -.2, review: .2, done: .45, quiet: .3 };", PAGE)
        self.assertIn("panNow = k === 'update' ? agentPan(agent) : (CUE_PAN[k] || 0);", PAGE)
        self.assertIn("const DROP_PAN = { todo: -.45, doing: 0, done: .45 };", PAGE)
        self.assertNotIn("ask:", re.search(r"const CUE_PAN = \{(.*?)\};", PAGE).group(1))             # an ask stays in the middle: it is for you

    def test_the_bookends_sound_when_end_of_day_is_sent_and_when_start_of_day_opens(self):
        self.assertIn("function dayBook(kind) { if (sndOn && layerOn('daybook'))", PAGE)
        self.assertIn("dayBook('dawn');", body("openSod"))
        self.assertIn("touch.after('copy'); dayBook('dusk'); loadChat();", PAGE)
        d = layer("daybook")
        self.assertIn("kind === 'dusk' ? [784, 659, 523, 392] : [392, 523, 659, 784, 1047]", d)
        vols = [float(v) for v in re.findall(r"\(kind === 'dusk' \? (\.\d+) : (\.\d+)\) \* lvl", d)[0]]
        self.assertTrue(max(vols) <= .02, vols)                                                      # under the quietest cue but the update one, by design soft


class Balance(unittest.TestCase):
    def test_cues_have_their_own_level_that_starts_at_todays(self):
        self.assertIn("let cueLvl = 1;", PAGE)
        self.assertIn("localStorage.getItem('agentboard-cues')", PAGE)
        self.assertIn("cueLvl = Math.min(1, Math.max(0, +v));", body("setCues"))                      # 0 to 100%, never above today's level: the volume does that
        self.assertIn("cueMul = cueLvl; try { f(agent); } finally { panNow = 0; cueMul = 1; } }; });", PAGE)
        self.assertIn("vol *= cueMul;", body("tone"))
        self.assertIn("panNow = 0; cueMul = 1;", re.search(r"function fx\(kind, agent\) \{.*", PAGE).group(0))   # a layer's own sound is never scaled by it

    def test_the_default_cue_wrapper_and_the_volume_chain_are_as_they_were(self):
        self.assertIn("Object.keys(cue).forEach(k => { const f = cue[k]; cue[k] = agent => { f(agent); fx(k, agent); }; });", PAGE)
        self.assertIn("master.connect(volDirect); volDirect.connect(audio.destination);", PAGE)
        self.assertIn("master.connect(volLimited); volLimited.connect(lim); lim.connect(ceil); ceil.connect(audio.destination);", PAGE)
        self.assertIn("meterNode = audio.createAnalyser(); meterNode.fftSize = 512; master.connect(meterNode);", PAGE)   # a tap on the bus, not a link in it

    def test_the_settings_rows_are_searchable_and_the_meter_is_cheap(self):
        r = body("renderMix")
        self.assertIn('<label for="cfg-cues">Cues</label>', r)
        self.assertIn("<label>Output</label>", r)                                                      # a label: Settings search indexes it
        f = body("meterFrame")
        self.assertIn("if (!mixIsOpen() || document.hidden) return;", f)                              # nothing runs while the sheet is shut or the tab hidden
        self.assertIn("if (el && !$('pane-sound').hidden) {", f)                                      # and nothing is read while another tab is showing
        self.assertIn("RM || $('pane-sound').hidden ? setTimeout(", f)                                # slower for reduced motion and a hidden pane
        self.assertIn("getFloatTimeDomainData", f)
        self.assertIn("startMeter(); } else stopDemo();", PAGE)
        self.assertIn("el.classList.toggle('hot', shown > -9); el.classList.toggle('lim', shown > -3);", f)


if __name__ == "__main__":
    unittest.main()
