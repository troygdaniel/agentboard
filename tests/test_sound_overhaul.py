"""The sound overhaul (Nov 12): more layers, a better balance and the settings and UI around them. Every new sound or look is off until
chosen, today's sound (Classic) stays the default, and the cues, the volume limiter and the per-view switch sounds are not touched.
This file grows with each step: layers (Stage, Humanize, Day bookends), then balance (a Cues level and a live output meter), Quiet hours and Scenes."""
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
        self.assertIn("cueMul = cueLvl;", PAGE)
        self.assertIn("try { f(agent); } finally { panNow = 0; cueMul = 1; quietPass = false; } }; });", PAGE)
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


class QuietHours(unittest.TestCase):
    def test_it_is_off_until_chosen_and_the_default_window_is_the_usual_night(self):
        self.assertIn("let quiet = { on: false, from: '22:00', to: '07:00', until: 0, skip: 0 }", PAGE)
        self.assertIn("if (!quiet.on || now < quiet.skip) return false;", body("quietActive"))
        self.assertIn("return a === b ? false : a < b ? (m >= a && m < b) : (m >= a || m < b);", body("quietActive"))   # a window across midnight is the usual one
        self.assertIn("const d = new Date(now), m =", body("quietActive"))                                             # one clock for the whole decision

    def test_only_a_valid_time_is_kept(self):
        self.assertIn("const HHMM = /^([01]\\d|2[0-3]):[0-5]\\d$/;", PAGE)
        self.assertIn("if (!HHMM.test(quiet.from)) quiet.from = '22:00';", PAGE)
        self.assertIn("if (HHMM.test(e.target.value)) { quiet[k] = e.target.value;", PAGE)                            # a half-typed time input is empty: ignored

    def test_every_sound_goes_through_the_gate_and_only_an_ask_passes_it_softly_and_rarely(self):
        self.assertIn("function sndNow() { if (!sndOn) return null; if (quietNow() && !quietPass) return null;", PAGE)
        self.assertIn("if (k === 'ask' && quietActive() && Date.now() >= hearUntil) { if (Date.now() - quietAskAt < 15 * 60000) return; quietAskAt = Date.now(); quietPass = true; cueMul *= .3; }", PAGE)
        self.assertIn("try { f(agent); } finally { panNow = 0; cueMul = 1; quietPass = false; } }; });", PAGE)
        self.assertIn("const quietNow = () => Date.now() >= hearUntil && quietActive();", PAGE)                        # Hear it is let through for a few seconds
        self.assertIn("hearUntil = Date.now() + 7000;", body("hearLayer"))

    def test_the_bed_leaves_and_returns_with_the_window_and_notifications_go_silent(self):
        self.assertIn("if (quietActive()) return;   // Quiet hours: no bed until the window ends", body("startAmb"))
        q = body("quietTick")
        self.assertIn("if (q !== wasQuiet) { wasQuiet = q; if (q) stopAmb(); else startAmb(); }", q)
        self.assertIn("setInterval(quietTick, 20000);", PAGE)
        self.assertIn("silent: !sndOn || quietActive() });", PAGE)

    def test_the_chip_and_the_settings_rows(self):
        self.assertIn('<button class="status quiet" id="quiet-chip" type="button" hidden></button>', PAGE)
        self.assertIn("$('quiet-chip').addEventListener('click', endQuiet);", PAGE)
        e = body("endQuiet")
        self.assertIn("if (quiet.until && Date.now() < quiet.until) quiet.until = 0; else quiet.skip = nextAt(quiet.to);", e)   # a hand-started window ends; a scheduled one is skipped
        r = body("renderQuiet")
        self.assertIn('<label for="cfg-quiet-on">Quiet hours</label>', r)
        self.assertIn("<label>Quiet until morning</label>", r)                                                       # labels: Settings search indexes them
        self.assertIn('<h3>Quiet hours</h3><div id="cfg-quiet"></div>\n  <h3>Sound</h3><div id="cfg-sound"></div>\n  <h3>Touch', PAGE)


class Scenes(unittest.TestCase):
    def test_four_scenes_and_classic_is_todays_sound(self):
        self.assertEqual(re.findall(r"\{ id: '(\w+)', name: '([^']+)', about:", PAGE[PAGE.index("const SCENES = ["):PAGE.index("const soundLayers")]),
                         [("classic", "Classic"), ("focus", "Focus"), ("control", "Control room"), ("night", "Night")])
        self.assertIn("{ id: 'classic', name: 'Classic', about: \"today's sound: the cues, Touch and the ambient bed, nothing extra\", amb: true, cues: 1, layers: { touch: 1 } }", PAGE)
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1).strip(), "touch: true")       # so a fresh browser already reads as Classic

    def test_a_scene_never_touches_volume_quiet_hours_or_the_looks(self):
        a = body("applyScene")
        self.assertIn("soundLayers().forEach(L =>", a)
        self.assertIn("const soundLayers = () => LAYERS.filter(L => !L.look);", PAGE)                    # Calm, Lively, From the future and Motion are looks
        for word in ("setVol", "quiet", "vol "):
            self.assertNotIn(word, a)
        self.assertIn("setCues(sc.cues); setAmb(sc.amb);", a)

    def test_an_unnamed_layer_is_off_and_the_current_scene_is_found_by_comparing_everything(self):
        self.assertIn("mix[L.id] = { on: want != null, lvl: want != null ? want : layerLvl(L.id) };", body("applyScene"))   # off, but its own level is kept for later
        n = body("sceneNow")
        self.assertIn("ambOn === sc.amb && Math.abs(cueLvl - sc.cues) < .02", n)
        self.assertIn("want == null ? !layerOn(L.id) : layerOn(L.id) && Math.abs(layerLvl(L.id) - want) < .03", n)

    def test_the_picker_sits_above_quiet_hours_and_sound_and_follows_every_change(self):
        self.assertIn('<h3>Scenes</h3><div id="cfg-scenes"></div>\n  <h3>Quiet hours</h3><div id="cfg-quiet"></div>\n  <h3>Sound</h3><div id="cfg-sound"></div>\n  <h3>Touch', PAGE)
        self.assertIn("$('mix').addEventListener('input', () => setTimeout(refreshScenes, 0));", PAGE)       # after the handler that takes the change
        self.assertIn("aria-pressed=\"${cur === sc.id}\"", body("scenesHtml"))
        self.assertIn("Your own mix", body("scenesHtml"))
        self.assertIn("<label>Scene: ${SCENES.map(x => x.name).join(', ')}</label>", body("scenesHtml"))    # Settings search finds a scene by name
        self.assertIn("applyScene(SCENES.find(x => x.id === sc.dataset.scene)); touch('toggle', true); cue.added();", PAGE)


if __name__ == "__main__":
    unittest.main()
