"""Nothing hides under Load and nothing in the header moves (4 Nov): the toast and the error strip sit above the overlay, the strip
floats with a close button instead of pushing the board down, the header never wraps at desktop width and its counts shrink before
anything else gives, cards glide only on a real move, Load keeps each pane's scroll, a telemetry row does not lift, Settings has a
Look section holding Motion and the gear shows when sound is off."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    assert m, selector
    return m.group(1)


class AboveLoadTests(unittest.TestCase):
    def test_the_toast_and_the_error_strip_are_above_load(self):
        self.assertIn("z-index: 36;", rule("#toast"))
        self.assertIn("z-index: 30;", rule("#hud"))
        err = rule("#error")
        self.assertIn("position: fixed;", err)
        self.assertIn("z-index: 36;", err)
        self.assertIn("top: calc(var(--hdr-b, 56px) + 10px);", err)

    def test_the_error_strip_closes_and_moves_nothing(self):
        self.assertIn('<div id="error" role="alert"><span id="error-text"></span><button type="button" id="error-close" aria-label="Dismiss">×</button></div>', HTML)
        self.assertIn("$('error-close').onclick = () => showError('');", HTML)
        self.assertIn("$('error').classList.toggle('on', !!msg);", HTML)
        self.assertNotIn("margin-bottom: 16px; display: none; }", rule("#error"))


class HeaderTests(unittest.TestCase):
    def test_the_header_never_wraps_at_desktop_width_and_the_counts_shrink_first(self):
        self.assertIn("@media (min-width: 901px) { header { flex-wrap: nowrap; } }", HTML)
        summ = rule("#summary")
        for piece in ("white-space: nowrap;", "overflow: hidden;", "text-overflow: ellipsis;", "min-width: 0;", "font-variant-numeric: tabular-nums;"):
            self.assertIn(piece, summ)
        self.assertIn("#orch-btn[hidden] { display: inline-flex; visibility: hidden; }", HTML)   # the slot is there from the first paint
        self.assertIn("#later-btn { min-width: 104px; font-variant-numeric: tabular-nums; }", HTML)
        self.assertIn("min-width: 6ch;", rule(".rb-sum"))


class GlideAndScrollTests(unittest.TestCase):
    def test_a_card_glides_only_when_its_column_or_order_changed(self):
        self.assertIn("const beforeOrder = new Map();", HTML)
        self.assertIn("if (beforeOrder.has(id) && beforeOrder.get(id) === orderNow[id]) return;", HTML)
        self.assertIn("const orderNow = Object.fromEntries([...shown.all('.card')].map((c, i) => [c.dataset.id, (c.closest('.col')?.dataset.status || '') + ':' + i]));", HTML)

    def test_load_keeps_each_panes_scroll_across_opens(self):
        self.assertIn("let hudScroll = { doing: 0, todo: 0 };", HTML)
        self.assertIn("hudScroll = { doing: $('h-cards-box').scrollTop, todo: $('h-todo-wrap').querySelector('.cards')?.scrollTop || 0 };", HTML)
        self.assertIn("top = box.innerHTML ? box.scrollTop : hudScroll.doing;", HTML)
        self.assertIn("ttop = tw.innerHTML ? (tw.querySelector('.cards')?.scrollTop || 0) : hudScroll.todo;", HTML)


class SettingsAndRowsTests(unittest.TestCase):
    def test_a_telemetry_row_does_not_lift(self):
        self.assertIn(".h-row:not(.attn):hover { transform: none;", HTML)

    def test_settings_has_a_look_section_and_the_gear_shows_sound_off(self):
        self.assertIn('<h3>Look (every view)</h3><div id="mix-look"></div>', HTML)
        self.assertIn("$('mix-look').innerHTML = LAYERS.filter(L => L.look).map(row).join('');", HTML)
        self.assertIn("{ id: 'motion', kind: 'fx', look: true,", HTML)
        self.assertIn("<h3>Ambience (plays with the ambient bed, on every view)</h3>", HTML)
        self.assertNotIn("plays with AMB", HTML)
        self.assertIn("body.snd-off #cfg-btn .snd-off { display: block; }", HTML)
        self.assertIn("document.body.classList.toggle('snd-off', !on);", HTML)


class CalmCardsTests(unittest.TestCase):
    def test_calm_cards_is_a_look_switch_off_by_default_with_no_level(self):
        self.assertIn("{ id: 'calm', kind: 'fx', look: true, plain: true, name: 'Calm cards', about: '", HTML)
        self.assertIn("apply(lvl) { document.body.classList.toggle('calm', lvl > 0); } },", HTML)
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", HTML).group(1).strip(), "touch: true")   # off until chosen: the current look stays
        self.assertIn("(L.plain ? '<span></span><span></span>' : `<input type=\"range\"", HTML)                 # no level slider, nothing to hear
        self.assertIn("body.calm :is(.col.doing, .col.acol, .h-one) .card:not(.done):not(.ask):not(.review):not(.abandoned) { background: var(--surface); border-color: var(--line);", HTML)


if __name__ == "__main__":
    unittest.main()
