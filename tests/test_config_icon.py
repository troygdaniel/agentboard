"""Settings (Nov 3): a gear on every view opens the sheet that was Mix, now with sound, ambient bed and volume; the header lost
the Filter field and the Live block (and, since 4 Nov, projects altogether); Load's bar lost Pop out, Close, Mix, SND and AMB."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
HEADER = HTML[HTML.index("<header>"):HTML.index("</header>")]
ICONS = re.search(r'<span class="hicons">(.*?)</span>\s*</header>', HTML, re.S).group(1)
HBAR = HTML[HTML.index('<div class="hud" id="hud-inner"'):HTML.index('<div class="h-grid">')]   # Load's own top, above its grid (Nov 3: the bar itself went; see test_load_align)


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class HeaderTests(unittest.TestCase):
    def test_the_header_lost_the_filters_and_the_live_block(self):
        self.assertNotIn('placeholder="Filter  /"', HEADER)
        self.assertNotIn('id="project-filter"', HEADER)   # projects are gone (4 Nov)
        self.assertIn('id="filter" aria-label="Filter tasks" hidden', HEADER)
        self.assertIn("#filter { display: none; }", HTML)
        self.assertNotIn("<span>Live</span>", HEADER)
        self.assertNotIn("<dt><kbd>/</kbd></dt>", HTML)                 # the / shortcut only served the field
        self.assertNotIn("e.key === '/'", HTML)

    def test_an_active_filter_still_shows_and_can_be_cleared(self):
        self.assertIn('<span class="summary" id="filter-summary" role="status"></span><button class="btn filter-clear" id="filter-clear" hidden aria-label="Clear the filter"', HEADER)
        self.assertIn("$('filter-clear').hidden = false;", body("render"))
        self.assertIn("$('filter-clear').hidden = true;", body("render"))
        self.assertIn("$('filter-clear').onclick = () => { $('filter').value = ''; flagFilter = null; render(); };", HTML)
        # the who chip and the attention counts still drive the hidden field
        self.assertIn("const f = $('filter'); f.value = f.value === w.dataset.agent ? '' : w.dataset.agent;", HTML)
        self.assertIn("function toggleFlagFilter(flag) { flagFilter = flagFilter === flag ? null : flag; render(); }", HTML)

    def test_the_disconnected_chip_shows_only_while_the_server_is_unreachable(self):
        self.assertIn('<span class="status off" id="status" role="status" hidden><i></i><span>Disconnected; retrying</span></span>', ICONS)
        self.assertIn("$('status').hidden = ok;", body("setStatus"))
        self.assertIn("if (statusOk && !ok) touch.after('error');", body("setStatus"))   # the one low tone on the drop stays

    def test_one_gear_in_the_icon_group_on_every_view(self):
        self.assertIn('id="cfg-btn" aria-label="Settings (m)" title="Settings" aria-controls="mix"', ICONS)
        self.assertNotIn('id="snd2"', HEADER)                            # sound on/off lives in Settings now
        self.assertIn("#theme, #cfg-btn { width: 44px; height: 44px;", HTML)
        self.assertEqual(ICONS.count('id="cfg-btn"'), 1)
        self.assertIn("$('cfg-btn').onclick = () => toggleMix();", HTML)
        self.assertIn("if (open) $('mix').querySelector('input').focus(); else $('cfg-btn').focus();", HTML)


class SettingsTests(unittest.TestCase):
    def test_the_sheet_is_settings_with_sound_ambient_and_volume_above_the_layers(self):
        self.assertIn('<div id="mix" role="dialog" aria-label="Settings"><div class="sheet">\n  <h2>Settings</h2>', HTML)
        self.assertIn('<h3>Sound</h3><div id="cfg-sound"></div>\n  <h3>Touch', HTML)
        r = body("renderMix")
        self.assertIn('<input type="checkbox" id="cfg-snd"${sndOn ? \' checked\' : \'\'}><label for="cfg-snd">Sound</label>', r)
        self.assertIn('<input type="checkbox" id="cfg-amb"${ambOn ? \' checked\' : \'\'}><label for="cfg-amb">Ambient bed</label>', r)
        self.assertIn('<input type="range" id="cfg-vol" min="100" max="${VOL_MAX * 100}" step="5" value="${Math.round(vol * 100)}"', r)
        self.assertIn("$('mix-touch').innerHTML", r)

    def test_the_switches_keep_the_old_behaviour_and_nothing_double_plays(self):
        self.assertIn("function toggleSound() { if (sndOn) touch('toggle', false); setSnd(!sndOn, true); if (sndOn) cue.added(); }", HTML)
        self.assertIn("if (e.key === 's') { toggleSound(); return; }", HTML)
        self.assertIn("if (e.target.id === 'cfg-snd') { toggleSound(); return; }", HTML)
        self.assertIn("if (e.target.id === 'cfg-amb') { touch('toggle', e.target.checked); setAmb(e.target.checked); return; }", HTML)
        self.assertIn("const c = $('cfg-snd'); if (c) c.checked = on;", body("setSnd"))
        self.assertIn("const c = $('cfg-amb'); if (c) c.checked = on;", body("setAmb"))
        self.assertNotIn("h-snd", HTML); self.assertNotIn("h-amb", HTML); self.assertNotIn("snd2", HTML)
        self.assertEqual(HTML.count("function toggleSound()"), 1)

    def test_volume_defaults_to_todays_level_and_only_a_raise_goes_through_the_limiter(self):
        self.assertIn("let vol = 1;", HTML)
        self.assertIn("vol = Math.min(3, Math.max(1, +localStorage.getItem('agentboard-vol') || 1));", HTML)
        self.assertIn("const VOL_MAX = 3;", HTML)
        a = body("ac")
        self.assertIn("master = audio.createGain(); master.gain.value = vol; comp.connect(master);", a)
        self.assertIn("lim.threshold.value = -3; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = .002; lim.release.value = .08;", a)
        self.assertIn("master.connect(volDirect); volDirect.connect(audio.destination);", a)
        self.assertIn("master.connect(volLimited); volLimited.connect(lim); lim.connect(ceil); ceil.connect(audio.destination);", a)
        self.assertIn("const ceil = audio.createWaveShaper(), curve = new Float32Array(4097), k = .6, top = .95;", a)   # nothing reaches full scale
        self.assertIn("volDirect.gain.value = vol > 1 ? 0 : 1; volLimited.gain.value = vol > 1 ? 1 : 0;", a)
        self.assertNotIn("comp.connect(audio.destination)", a)
        s = body("setVol")
        self.assertIn("vol = Math.min(VOL_MAX, Math.max(1, +v || 1));", s)
        self.assertIn("localStorage.setItem('agentboard-vol', String(vol));", s)
        self.assertIn("if (e.target.id === 'cfg-vol') { setVol(e.target.value / 100); return; }", HTML)
        self.assertIn("$('mix').addEventListener('change', e => { if (e.target.id === 'cfg-vol') cue.added(); });", HTML)


class LoadBarTests(unittest.TestCase):
    def test_loads_top_has_no_buttons_but_the_hidden_fullscreen(self):
        for gone in ("h-pop", "h-close", "h-mix", "h-snd", "h-amb", "Pop out", "SND ON", "AMB ON"):
            self.assertNotIn(gone, HBAR, gone)
        self.assertIn('id="h-full"', HBAR)                                 # hidden; f still toggles fullscreen
        self.assertIn("$('hud-inner').focus();", body("openHud"))
        self.assertIn('<div class="hud" id="hud-inner" tabindex="-1">', HTML)
        self.assertNotIn("$('h-pop')", HTML); self.assertNotIn("$('h-close')", HTML)


if __name__ == "__main__":
    unittest.main()
