"""Touch: a thin layer of UI sounds for what your hands do on the board (focus, open, drag, switch, toggle, select), on top of
the produced cue space and through the same buses. Quiet, short, one per gesture, never on a poll; one Mix row, on by default."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
TOUCH = re.search(r"const TOUCH = \{(.*?)\n\};", PAGE, re.S).group(1)
CUES = re.search(r"const cue = \{(.*?)\n\};", PAGE, re.S).group(1)
LAYERS = re.search(r"const LAYERS = \[(.*?)\n\];", PAGE, re.S).group(1)


def body(name):
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\nfunction ", i + 10)]


class TouchSoundTests(unittest.TestCase):
    def test_every_touch_sound_is_at_most_40_percent_of_the_quietest_cue_and_20_to_120_ms(self):
        quietest = min(float(v) for v in re.findall(r"vol: (\.\d+)", CUES))
        self.assertEqual(quietest, .013)                                        # the update cue
        self.assertIn("const TV = .005;", PAGE)
        self.assertLessEqual(.005, .4 * quietest)
        # a tap's level is a share (<= 1) of the ceiling, scaled by the layer's level; nothing passes an absolute vol
        self.assertIn("function tap(f, t, dur, v, o = {}) { tone(f, t, dur, { atk: .003, verb: .35, ...o, vol: v * TV * (o.lvl ?? layerLvl('touch')) }); }", PAGE)
        self.assertNotIn("vol:", TOUCH)
        taps = re.findall(r"tap\([^,]+, [^,]+, (\.\d+), (\.?\d+(?:\.\d+)?)", TOUCH)
        self.assertGreaterEqual(len(taps), 14)
        for dur, share in taps:
            self.assertTrue(.02 <= float(dur) <= .12, (dur, share))
            self.assertTrue(0 < float(share) <= 1, (dur, share))
        for dur, opts in re.findall(r"hush\(t, (\.\d+), \{([^}]*)\}", TOUCH):
            self.assertTrue(.02 <= float(dur) <= .12, dur)
            for share in re.findall(r"v: (\.?\d+)", opts):
                self.assertLessEqual(float(share), 1)
        self.assertIn("v * TV * layerLvl('touch')", body("hush"))

    def test_touch_sounds_sit_in_the_same_produced_space_as_the_cues(self):
        # taps are tone(): the dry bus, the reverb send and the compressor behind both. The noise breath goes the same way.
        hush = body("hush")
        self.assertIn("g.connect(dry);", hush)
        self.assertIn("w.connect(send);", hush)
        self.assertIn("if (echo) g.connect(echo);", hush)                       # and answers the Echo layer like a cue
        self.assertIn("touchNoise = touchNoise || noiseBuf(ctx, .5, true);", hush)   # synthesized, no files
        # the attack option a 20 ms tick needs leaves the cues on their 20 ms default
        self.assertIn("function tone(freq, t0, dur, { type = 'sine', vol = .05, glide, verb = .6, pan = 0, atk = .02 } = {}) {", PAGE)
        self.assertIn("g.gain.linearRampToValueAtTime(vol, t0 + atk);", PAGE)

    def test_the_whole_set_is_one_mix_row_called_touch_on_by_default_with_its_own_level(self):
        self.assertIn("{ id: 'touch', kind: 'fx', ui: true, name: 'Touch', about: '", LAYERS)
        self.assertIn("const LAYER_ON = { touch: true };", PAGE)
        self.assertIn("return m && m.on != null ? !!m.on : !!LAYER_ON[id];", PAGE)   # on until switched off; a saved choice wins
        self.assertIn("if (!layerOn('touch')) return null;", body("touchAt"))
        self.assertIn('<h3>Touch (what your hands do, on every view)</h3><div id="mix-touch"></div>', PAGE)
        self.assertIn("$('mix-touch').innerHTML = LAYERS.filter(L => L.ui).map(row).join('');", PAGE)
        self.assertIn("LAYERS.filter(L => L.kind === 'fx' && !L.ui && !L.look)", PAGE)        # not twice in the sheet
        self.assertIn("layerOn(L.id) && !LAYER_ON[L.id]).length", PAGE)             # the Mix count stays the extras you chose
        self.assertIn("demo(ctx) {", LAYERS.split("id: 'touch'")[1])                 # a Hear button like every other row

    def test_sound_honours_only_the_snd_switch(self):
        self.assertIn("return sndNow();", body("touchAt"))                            # SND OFF and no context yet both end here
        self.assertNotIn("prefers-reduced-motion", PAGE.split("const TV = .005;")[1].split("// --- HUD ---")[0])
        self.assertNotIn("matchMedia", TOUCH)

    def test_nothing_plays_on_a_poll_or_a_re_render_and_one_gesture_gets_one_sound(self):
        self.assertIn("['pointerdown', 'keydown', 'click', 'input', 'change', 'submit', 'dragstart', 'drop'].forEach(ev => window.addEventListener(ev, () => {", PAGE)
        self.assertIn("gestureSeq++; gestureLive = true; lastGestureAt = Date.now(); setTimeout(() => { gestureLive = false; }, 0);", PAGE)
        self.assertIn("if (!after) { if (!gestureLive || touchSeq === gestureSeq) return null; touchSeq = gestureSeq; }", body("touchAt"))
        # nothing in the poll path or the renderer asks for a touch sound
        for fn in ("load", "render", "hudSounds", "checkAsks", "maybeAutoOpen", "renderSelection", "renderLater", "renderPanel", "hudLoad"):
            self.assertNotIn("touch(", body(fn), fn)
        # what lands after an await (a copy, a done, an undo, a failed save) is still the user's action, so it may play after the gesture is past
        self.assertIn("touch.after = (kind, ...args) => { const t = touchAt(true);", PAGE)
        self.assertEqual(sorted(set(re.findall(r"touch\.after\('(\w+)'", PAGE))), ["copy", "drop", "error", "toggle", "undo"])

    def test_the_existing_cues_and_the_bed_are_unchanged_and_never_doubled(self):
        for line in (
            "open()   { const t = sndNow(); if (t == null) return; tone(587, t, .1, { vol: .028 }); tone(880, t + .09, .12, { vol: .026 }); tone(1175, t + .18, .3, { vol: .022, verb: 1.1 }); },",
            "update(agent) { const t = sndNow(); if (t == null) return; tone(agentPitch(agent), t, .06, { vol: .013, verb: .9, pan: .15 }); },",
            "added()  { const t = sndNow(); if (t == null) return; tone(659, t, .05, { vol: .018, verb: .8 }); tone(988, t + .06, .07, { vol: .016, verb: .8 }); },",
            "const h1 = ctx.createOscillator(); h1.frequency.value = 55;",
            "const ng = ctx.createGain(); ng.gain.value = .02;",
        ):
            self.assertIn(line, PAGE)
        # Mark done keeps its done cue, adding a task its added cue: no touch sound on either click
        self.assertIn("if (md) { confirmDoneClick(md); move(md.dataset.done, 'done'); return; }", PAGE)
        self.assertNotIn("touch(", PAGE.split("$('add').onsubmit")[1].split("};")[0])
        self.assertNotIn("touch(", PAGE.split("$('later-body').addEventListener('submit'")[1].split("});")[0])
        # Load opens and closes with the same swish as a tab change, nothing on top; a card opened from Load does not add an open pair
        self.assertIn("closeHud(); openPanel(id, true);", PAGE)
        self.assertEqual(body("openHud").count("touch("), 1)
        self.assertEqual(body("closeHud").count("touch("), 1)
        # turning sound on already plays the open cue (or the added cue): only the off click is added
        self.assertIn("function toggleSound() { if (sndOn) touch('toggle', false); setSnd(!sndOn, true); if (sndOn) cue.added(); }", PAGE)
        self.assertIn("if (e.target.id === 'cfg-snd') { toggleSound(); return; }", PAGE)

    def test_what_gets_a_sound(self):
        # focus by keyboard only: a click focuses a card too, silently
        self.assertIn("document.addEventListener('focusin', e => { if (gestureKey && e.target.classList?.contains('card')) touch('focus'); });", PAGE)
        self.assertIn("focus: t => tap(1760, t, .02, .7),", TOUCH)
        # open and close a panel, in the card's voice; the close sounds before the focus goes back so the tick does not win
        self.assertIn("if (!quiet && (openId !== id || !$('panel').classList.contains('open'))) touch('open', agentOf(id));", body("openPanel"))
        self.assertIn("if (!quiet && openId) touch('close', agentOf(openId));", body("closePanel"))
        self.assertIn("if (which !== 'panel' && openId) closePanel(true, true);", body("setSide"))
        for kind in ("open", "close"):
            self.assertRegex(TOUCH, kind + r":\s+\(t, agent\) => \{ const p = agentPitch\(agent\) / 2;")
        # drag: a lift, then a settle pitched by the column, in the card's voice; back where it was: nothing
        self.assertIn("e.dataTransfer.setData('text/plain', dragging);\n    touch('lift');", PAGE)
        self.assertIn("if (!stayed) touch('drop', rule.status, c?.dataset.agent);", PAGE)
        self.assertIn("const stayed = c && c.closest('.col') === col && (b || null) === (next || null);", PAGE)
        self.assertIn("{ todo: 392, doing: 523, done: 659 }[status] || 523", TOUCH)
        self.assertIn("tap(agentPitch(agent), t + .05, .03, .5, { verb: .5, lvl }); },", TOUCH)
        # Alt+arrows: a click per step that moved something
        self.assertIn("  else return;   // at the edge: no move, no click\n  touch('step');", PAGE)
        # tab switch: one swish for a view change, from the tabs, [ ] and a alike; the view flips in place so it plays through
        self.assertIn("if (agents !== BYAGENT || need !== MEFIRST) { if (!here) touch('swish'); setView(agents, true, need); }", body("goView"))
        self.assertIn("if (e.key === 'a') { goView(BYAGENT ? 0 : 1); return; }", PAGE)
        # drawers and sheets slide in and out, from the button, the key, Escape and a click outside
        self.assertIn("function openLater() { setSide('later'); touch('slide', true);", PAGE)
        self.assertIn("function closeLater() { touch('slide', false);", PAGE)
        self.assertIn("setSide('chat'); touch('slide', true); $('chat').classList.add('open');", PAGE)
        self.assertIn("function closeChat() { touch('slide', false);", PAGE)
        self.assertIn("if (open !== mixIsOpen()) touch('slide', open);", body("toggleMix"))
        self.assertIn("if (open !== $('keys').classList.contains('on')) touch('slide', open);", body("toggleKeys"))
        self.assertEqual(PAGE.count("toggleKeys("), 6)   # the ? key, Escape, the backdrop click, the function itself, the header ? button and the tour closing the sheet
        self.assertIn("{ touch('slide', false); $('later').classList.remove('open'); }", PAGE)
        self.assertIn("{ touch('slide', false); $('chat').classList.remove('open'); }", PAGE)
        # toggles: two pitches, up for on, down for off (theme: light up, dark down, auto level)
        self.assertIn("on === true ? [660, 880] : on === false ? [880, 660] : [740, 740]", TOUCH)
        self.assertIn("touch('toggle', theme === 'light' ? true : theme === 'dark' ? false : null)", PAGE)
        self.assertIn("if (e.target.id === 'cfg-amb') { touch('toggle', e.target.checked); setAmb(e.target.checked); return; }", PAGE)
        self.assertIn("await setNotif(want); if (notifOn === want) touch.after('toggle', want);", PAGE)
        # the filter: nothing per keystroke, a tick when the match count changes
        self.assertIn("$('filter').oninput = () => { const was = shownCards(); render(); if (shownCards() !== was) touch('match'); };", PAGE)
        # copy: a confirm blip once the clipboard has it; with warnings the message's tone speaks instead
        self.assertEqual(PAGE.count("touch.after('copy')"), 3)   # the one prompt-copy path (card button, panel button, c key), ORCH, the little copy buttons
        self.assertIn("if (d.warnings.length) showError(d.warnings.join(' · ')); else touch.after('copy');", PAGE)
        # select: a semitone up per card, in the card's voice; down when one leaves or the selection clears
        self.assertIn("select: (t, n, agent, added) => { const f = agentPitch(agent) / 2 * Math.pow(2, Math.min(n, 12) / 12);", TOUCH)
        self.assertIn("touch('select', selected.size, agentOf(id), added);", body("toggleSelect"))
        self.assertIn("touch('select', selected.size, agentOf(id), selected.size >= had);", body("selectRangeTo"))
        self.assertIn("touch('select', selected.size, col[ri].dataset.agent, selected.size >= had);   // the select is the sound of this step, before the focus moves\n  focusCard(col[ri]);", PAGE)
        self.assertIn("touch('select', 0, null, false); renderSelection(); }", body("clearSelection"))
        # errors: one low tone for a new message or a dropped connection, not again on every poll
        self.assertIn("if (msg && (msg !== errShown || Date.now() - errAt > 500)) { touch.after('error'); errAt = Date.now(); }", body("showError"))
        self.assertEqual(PAGE.count("showError('That task no longer exists.')"), 1)   # the one message a poll can raise closes the panel with it: once
        self.assertIn("if (statusOk && !ok) touch.after('error');", body("setStatus"))
        self.assertIn("error: t => tap(196, t, .12, 1, { type: 'triangle', atk: .01, verb: .3 }),", TOUCH)


if __name__ == "__main__":
    unittest.main()
