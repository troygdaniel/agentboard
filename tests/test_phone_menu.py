"""The phone menu (sweep-ux, 15 Nov). At 700px and under the header's buttons are hidden ("a phone: the three tabs, the card, the line to ORCH"), so a phone could not open Settings
(and with it the Night switch), the Later drawer, the new-task sheet or the theme switch. One Menu button now shows at that width and opens a sheet with the four.

A unit test cannot tap a phone, so this pins the shape; the real check, at 390px and 1280px in headless Chrome on a throwaway board with real key events, is
tests/qa/phone_menu_check.mjs: `node tests/qa/phone_menu_check.mjs`."""
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class PhoneMenuTests(unittest.TestCase):
    def test_the_button_and_the_sheet_are_in_the_page_and_closed_to_begin_with(self):
        self.assertIn('id="more-btn" type="button" aria-label="Menu" title="Menu" aria-haspopup="menu" aria-expanded="false" aria-controls="more-menu"', HTML)
        self.assertIn('<div id="more-menu" role="menu" aria-label="Menu" hidden>', HTML)
        for item in ("new", "later", "settings", "theme"):
            self.assertIn(f'role="menuitem" data-more="{item}" tabindex="-1"', HTML)
        self.assertLess(HTML.index('id="cfg-btn"'), HTML.index('id="more-btn"'))   # after Settings, the last of the header's buttons

    def test_it_shows_only_where_the_other_header_buttons_are_hidden(self):
        self.assertIn("@media (max-width: 700px) { .ab-more { display: grid; } }", HTML)
        self.assertIn(".ab-more { display: none;", HTML)
        self.assertIn("@media (min-width: 701px) { #more-menu { display: none !important; } }", HTML)
        self.assertIn("header .btn, header .ab-cfg, #summary,", HTML)      # the two chips step back with the buttons: the Menu is what stays
        self.assertNotIn('class="btn" id="more-btn"', HTML)                 # not a .btn: the phone rule would hide it with the rest

    def test_each_item_clicks_the_header_button_it_stands_for_and_the_click_goes_no_further(self):
        self.assertIn("$({ new: 'new-btn', later: 'later-btn', settings: 'cfg-btn', theme: 'theme' }[b.dataset.more]).click();", HTML)
        at = HTML.index("moreMenu.addEventListener('click', e => {")
        self.assertIn("e.stopPropagation();", HTML[at: at + 400])           # the page closes a drawer on a click outside it: this click opens one

    def test_keys_arrows_in_the_capture_phase_esc_in_the_chain_and_focus_returns(self):
        self.assertIn("window.addEventListener('keydown', e => {   // the capture phase on the window: the Now deck's arrow keys must not get them first", HTML)
        self.assertIn("e.preventDefault(); e.stopImmediatePropagation();\n}, true);", HTML)
        self.assertIn("if (!moreMenu.hidden) { toggleMore(false); return; }\n    if ($('keys').classList.contains('on'))", HTML)
        self.assertIn("} else if (moreMenu.contains(document.activeElement)) moreBtn.focus();", HTML)
        self.assertIn("focusWhenShown(moreItems()[0], () => !moreMenu.hidden);", HTML)

    def test_a_press_outside_closes_it_in_the_capture_phase_so_a_card_that_stops_its_own_click_cannot_keep_it_open(self):
        self.assertIn("document.addEventListener('pointerdown', e => { if (!moreMenu.hidden && !e.target.closest('#more-menu, #more-btn')) toggleMore(false); }, true);", HTML)
        self.assertNotIn("document.addEventListener('click', e => { if (!moreMenu.hidden", HTML)

    def test_the_logo_word_leaves_the_row_for_the_button_on_a_phone_but_stays_for_a_screen_reader(self):
        self.assertIn('</svg><span class="brand">agentboard</span></h1>', HTML)
        self.assertIn("@media (max-width: 480px) { h1 { flex: 0 0 auto; } h1 .brand { position: absolute;", HTML)


if __name__ == "__main__":
    unittest.main()
