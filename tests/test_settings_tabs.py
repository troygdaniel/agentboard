"""Settings in tabs (settings-ui-tabs, docs/settings-tabs-design.md): the sheet is a head (title, search, close) over a tab list and one pane; the core
panes and a plugin's register through one call, a tab with nothing in it is not drawn, the last tab is remembered, #settings/<tab> opens it, the tab list
is a real tablist. Nothing the old sheet held was removed or renamed: every id and heading is still there, in a pane. The page script is syntax-checked
with Node when it is installed (a duplicate declaration once blanked the whole page)."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
STATIC = HTML.split("<script>")[0]   # the markup and the CSS, before the page script


def rule(selector):
    m = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    return m.group(1) if m else None


class TheSheetMarkup(unittest.TestCase):
    def test_the_head_is_the_title_then_close_then_search_and_the_body_is_tabs_over_panes(self):
        self.assertIn('<div id="mix" role="dialog" aria-label="Settings"><div class="sheet">\n  <h2>Settings</h2><button class="icon-btn sheet-x" id="mix-close"', HTML)
        # the DOM order is the focus order: close, then search, then the tab list, then the pane
        order = [STATIC.index(x) for x in ('id="mix-close"', 'id="mix-search"', 'id="mix-tabs"', 'id="mix-panes"')]
        self.assertEqual(order, sorted(order))
        self.assertIn('<div class="tabs" id="mix-tabs" role="tablist" aria-label="Settings" aria-orientation="vertical"></div>', HTML)
        self.assertIn('<input id="mix-search" type="search" placeholder="Search settings" aria-label="Search settings"', HTML)
        self.assertIn('<div class="results" id="mix-results" role="listbox" aria-label="Matching settings" hidden></div>', HTML)

    def test_each_core_pane_is_a_tabpanel_tied_to_its_tab(self):
        for t in ("general", "sound", "agents", "more"):
            self.assertIn(f'<div class="pane" id="pane-{t}" role="tabpanel" aria-labelledby="stab-{t}" data-tab="{t}" hidden>', HTML)

    def test_the_plugin_slot_is_still_there_inside_the_more_pane(self):
        self.assertRegex(HTML, r'<div class="pane" id="pane-more"[^>]*>\s*<div id="ab-slot-settings"></div>\s*</div>')
        self.assertIn("settings: $('ab-slot-settings')", HTML)   # AB.settings keeps working for a plugin that has not moved to a tab

    def test_no_id_is_used_twice_in_the_markup(self):
        # the tab ids were once tab-agents, which the header's By agent link already had: a pane's aria-labelledby named the wrong element
        ids = re.findall(r'\bid="([^"$`{}]+)"', STATIC)
        self.assertEqual([k for k, v in Counter(ids).items() if v > 1], [])
        self.assertIn('id="stab-${esc(t.id)}"', HTML)

    def test_nothing_the_old_sheet_held_was_removed_or_renamed(self):
        for old in ('<h3>Sound</h3><div id="cfg-sound"></div>', '<h3>Touch (what your hands do, on every view)</h3><div id="mix-touch"></div>',
                    '<h3>Ambience (plays with the ambient bed, on every view)</h3><div id="mix-amb"></div>', '<h3>Effects (every view)</h3><div id="mix-fx"></div>',
                    '<h3>Look (every view)</h3><div id="mix-look"></div>', 'class="mix-note">Sound and look, for every view.'):
            self.assertIn(old, HTML)
        for piece in ('id="cfg-snd"', 'id="cfg-amb"', 'id="cfg-vol"', 'id="lyr-${L.id}"', 'data-hear="${L.id}"', 'data-level="${L.id}"', "$('mix-touch').innerHTML", "$('mix-fx').innerHTML"):
            self.assertIn(piece, HTML)

    def test_look_moved_to_general_and_the_sound_rows_to_sound(self):
        general = re.search(r'id="pane-general".*?\n      </div>', HTML, re.S).group(0)
        sound = re.search(r'id="pane-sound".*?\n      </div>', HTML, re.S).group(0)
        self.assertIn('id="mix-look"', general)
        for c in ("cfg-sound", "mix-touch", "mix-amb", "mix-fx"):
            self.assertIn(f'id="{c}"', sound)
            self.assertNotIn(f'id="{c}"', general)


@unittest.skipUnless(shutil.which("node"), "node is not installed: the page script is not syntax-checked")
class ThePageScriptParses(unittest.TestCase):
    def test_the_whole_page_script_is_valid_javascript(self):
        scripts = re.findall(r"<script>(.*?)</script>", HTML, re.S)
        self.assertTrue(scripts)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(max(scripts, key=len))
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True, timeout=60)
        Path(f.name).unlink(missing_ok=True)
        self.assertEqual(r.returncode, 0, r.stderr[:600])


class TheTabApi(unittest.TestCase):
    def test_a_plugin_registers_a_tab_with_one_call_and_gets_its_pane(self):
        self.assertIn("function settingsTab(id, label, o = {}) {", HTML)
        self.assertIn("Object.assign(AB, { settingsTab, settingsBadge });", HTML)
        self.assertIn("function settingsBadge(id, state)", HTML)
        self.assertIn("if (!t) {", HTML)   # the same id returns the same pane: only a new id creates one

    def test_a_tab_with_nothing_in_it_is_not_drawn_and_appears_when_its_pane_gets_a_child(self):
        self.assertIn("has: o.has || (() => [...pane.children].some(c => !c.hidden))", HTML)   # a child the plugin hid does not count
        self.assertIn("new MutationObserver(() => syncSettingsTabs()).observe(o.watch || pane, { childList: true, attributes: true, attributeFilter: ['hidden'], subtree: true });", HTML)
        self.assertIn("const vis = setTabs.filter(t => t.has());", HTML)
        self.assertIn("has: () => [...$('ab-slot-settings').children].some(c => !c.hidden), watch: $('ab-slot-settings')", HTML)   # More shows only when a plugin appended to AB.settings

    def test_the_core_tabs_register_through_the_same_call_in_order(self):
        for line in ("settingsTab('general', 'General', { order: 10,", "settingsTab('sound', 'Sound', { order: 20,", "settingsTab('agents', 'Agents and chat', { order: 30,", "settingsTab('more', 'More', { order: 90,"):
            self.assertIn(line, HTML)

    def test_the_tab_list_is_rebuilt_only_when_it_changed_so_a_focused_tab_keeps_focus(self):
        self.assertIn("if (sig === setTabsSig) return;", HTML)

    def test_open_settings_lands_on_the_tab_that_holds_the_element(self):
        self.assertIn("openSettings: el => { toggleMix(true, el && el.closest ? el.closest('[data-tab]')?.dataset.tab : undefined);", HTML)

    def test_a_badge_is_an_amber_dot_with_words_for_a_screen_reader(self):
        self.assertIn('<i class="dot" aria-hidden="true"></i><span class="sr"> needs a look</span>', HTML)
        self.assertIn("var(--warn)", rule(".tab .dot"))


class TheMemoryTheLinkAndTheKeys(unittest.TestCase):
    def test_the_last_tab_is_remembered_per_browser_and_the_page_works_without_it(self):
        self.assertIn("try { localStorage.setItem(SET_TAB_KEY, t.id); } catch (e) {}", HTML)
        self.assertIn("try { return localStorage.getItem(SET_TAB_KEY); } catch (e) { return null; }", HTML)

    def test_an_unknown_tab_falls_back_to_the_remembered_one_then_the_first(self):
        self.assertIn("vis.find(x => x.id === id) || vis.find(x => x.id === rememberedSettingsTab()) || vis[0]", HTML)

    def test_a_settings_hash_opens_the_sheet_and_is_not_taken_for_a_card(self):
        a, b = HTML.index("else if (/^#settings(\\/|$)/.test(location.hash)) toggleMix(true"), HTML.index("else if (location.hash.length > 1) openPanel(")
        self.assertLess(a, b)
        self.assertIn("addEventListener('hashchange', () => { if (/^#settings(\\/|$)/.test(location.hash)) toggleMix(true, hashTab() || undefined); });", HTML)
        self.assertIn("if (mixIsOpen() && !o.keepHash) history.replaceState(null, '', location.pathname + location.search + '#settings/' + t.id);", HTML)   # no history entry per tab
        self.assertIn("history.replaceState(null, '', location.pathname + location.search); $('cfg-btn').focus();", HTML)   # closing clears the hash

    def test_the_tab_list_is_a_real_tablist_with_arrows_home_and_end(self):
        self.assertIn("const prev = SET_NARROW.matches ? 'ArrowLeft' : 'ArrowUp', next = SET_NARROW.matches ? 'ArrowRight' : 'ArrowDown';", HTML)
        self.assertIn("e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1", HTML)
        self.assertIn("b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1;", HTML)   # one tab stop
        self.assertIn("e.preventDefault(); e.stopPropagation(); selectSettingsTab(tabs[j].dataset.tab, { focus: true });", HTML)   # the board's arrow shortcuts must not also run

    def test_opening_focuses_the_selected_tab_and_closing_returns_to_the_gear(self):
        self.assertIn("wantSettingsTab(tabId || hashTab(), { focus: true });", HTML)
        self.assertIn("else selectSettingsTab(id || rememberedSettingsTab() || 'general', o);", HTML)
        self.assertIn("$('cfg-btn').focus();", HTML)

    def test_the_slash_is_the_search_box_while_the_sheet_is_open(self):
        self.assertIn("if (e.key === '/' && mixIsOpen()) { e.preventDefault(); $('mix-search').focus(); return; }", HTML)

    def test_the_first_escape_clears_the_search_and_the_next_closes_the_sheet(self):
        self.assertIn("else if (e.key === 'Escape' && e.target.value) { e.preventDefault(); e.stopPropagation(); setSearch('');", HTML)
        self.assertIn("if (mixIsOpen()) { toggleMix(false); return; }", HTML)


class ThePendingTab(unittest.TestCase):
    """AGENT-6's render check: on a cold first load /#settings/texts opened on General and rewrote the hash, because the page read the hash (~30 ms) before the
    home plugin's script registered the Texts tab (~130 ms). A tab asked for before it exists is now remembered and selected the moment it has something."""

    def test_an_unknown_tab_is_remembered_and_the_hash_is_left_alone(self):
        self.assertIn("let pendingSettingsTab = null;", HTML)
        self.assertIn("if (id && !known) { pendingSettingsTab = id; selectSettingsTab(null, { ...o, keepHash: true }); }", HTML)
        self.assertIn("if (!o.keepHash) pendingSettingsTab = null;", HTML)   # the person choosing a tab, or the tab arriving, ends the wait

    def test_the_tab_is_selected_when_it_first_has_something_and_only_then_is_the_hash_written(self):
        self.assertIn("if (pendingSettingsTab && vis.some(t => t.id === pendingSettingsTab)) selectSettingsTab(pendingSettingsTab);", HTML)
        self.assertIn("else selectSettingsTab(vis.some(t => t.id === cur) ? cur : vis[0]?.id, { keepScroll: true, keepHash: !!pendingSettingsTab });", HTML)

    def test_a_search_hit_puts_focus_on_the_setting(self):
        self.assertIn("h.row.querySelector('input, button, select')?.focus({ preventScroll: true });", HTML)


class TheSearch(unittest.TestCase):
    def test_it_indexes_every_row_of_every_tab_hidden_ones_included(self):
        self.assertIn("setTabs.filter(t => t.has()).forEach(t => t.pane.querySelectorAll('.mix-row').forEach(row => {", HTML)

    def test_it_matches_all_the_words_ranks_a_name_that_starts_with_the_query_first_and_shows_eight(self):
        self.assertIn("if (!words.every(w => all.includes(w))) return null;", HTML)
        self.assertIn("score: n.startsWith(lq) ? 0 : n.includes(lq) ? 1 : words.every(w => n.includes(w)) ? 2 : 3", HTML)
        self.assertIn(".sort((a, b) => a.score - b.score).slice(0, 8);", HTML)

    def test_a_hit_opens_its_tab_scrolls_to_the_row_and_marks_it_for_a_second(self):
        self.assertIn("setSearch(''); selectSettingsTab(h.tab.id);\n  h.row.scrollIntoView({ block: 'start' });", HTML)
        self.assertIn("setTimeout(() => h.row.classList.remove('flash'), 1400);", HTML)

    def test_the_search_box_names_its_active_result_for_a_screen_reader(self):
        self.assertIn("box.setAttribute('aria-activedescendant', 'hit-0')", HTML)
        self.assertIn('role="option" id="hit-${i}"', HTML)


class TheFocusStaysInTheSheet(unittest.TestCase):
    """AGENT-6's render check: Tab from the last control landed on the page behind the dialog, and Shift+Tab from the close button on the toast's Undo."""

    def test_the_sheet_wraps_tab_and_shift_tab(self):
        self.assertIn("$('mix').addEventListener('keydown', e => {", HTML)
        self.assertIn("if (e.key !== 'Tab') return;", HTML)
        self.assertIn("const t = settingsTrapTarget(items, document.activeElement, e.shiftKey);", HTML)
        self.assertIn("if (t) { e.preventDefault(); t.focus(); }", HTML)

    @unittest.skipUnless(shutil.which("node"), "node is not installed: the wrap is checked as text only")
    def test_the_wrap_logic_in_node(self):
        fn = re.search(r"function settingsTrapTarget\(items, active, shift\) \{.*?\n\}\n", HTML, re.S).group(0)
        script = fn + """
const a = { n: 'close' }, b = { n: 'search' }, c = { n: 'last' }, out = x => x && x.n;
const items = [a, b, c];
console.log(JSON.stringify([out(settingsTrapTarget(items, c, false)), out(settingsTrapTarget(items, a, true)), out(settingsTrapTarget(items, b, false)), out(settingsTrapTarget(items, b, true)),
  out(settingsTrapTarget(items, { n: 'behind' }, false)), out(settingsTrapTarget(items, { n: 'behind' }, true)), out(settingsTrapTarget([], a, false)), out(settingsTrapTarget([a], a, false)), out(settingsTrapTarget([a], a, true))]));
"""
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        # Tab from the last wraps to the first; Shift+Tab from the first to the last; inside the list it moves as usual (null); from outside it comes in
        self.assertEqual(json.loads(r.stdout), ["close", "last", None, None, "close", "last", None, "close", "close"])


class TheNewRows(unittest.TestCase):
    def test_the_theme_row_and_the_header_switch_are_one_switch(self):
        self.assertIn("function setTheme(t) {", HTML)
        self.assertIn("$('theme').onclick = () => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]);", HTML)
        self.assertIn("const ts = e.target.closest('[data-theme-set]'); if (ts) { setTheme(ts.dataset.themeSet); return; }", HTML)

    def test_agent_chat_is_shown_with_its_command_and_never_written_from_the_page(self):
        # ORCH, 8 Nov: do not write a board-wide setting from the page; show the status and the command that changes it
        self.assertIn("Change it in a terminal: <code>agentboard chat agents ${on ? 'off' : 'on'}</code>.", HTML)
        pane = re.search(r"function renderAgentsPane\(\) \{.*?\n\}\n", HTML, re.S).group(0)
        self.assertNotIn("api(", pane)
        self.assertNotIn("chat-agents", pane)
        self.assertNotIn('type="checkbox"', pane)

    def test_the_boards_own_values_are_read_only_with_the_key_that_changes_them(self):
        self.assertIn("Set <code>[board] owner</code> in config.toml.", HTML)
        self.assertIn("Set <code>[board] stale_minutes</code> in config.toml.", HTML)
        self.assertIn("chatAgentsOn = !!d.agents;", HTML)


class TheLayout(unittest.TestCase):
    def test_the_sheet_is_720_wide_and_a_grid_of_head_over_body(self):
        r = rule("#mix .sheet")
        self.assertIn("width: min(720px, calc(100vw - 32px))", r)
        self.assertIn("height: min(720px, calc(100vh - 48px))", r)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", r)

    def test_the_layers_sit_in_two_columns_and_one_on_a_phone(self):
        self.assertIn("grid-template-columns: 1fr 1fr", rule("#mix-touch, #mix-amb, #mix-fx"))
        phone = re.search(r"@media \(max-width: 619px\) \{\s*#mix \.sheet \{[^}]*\}.*?\n  \}\n", HTML, re.S).group(0)
        self.assertIn("width: 100vw; height: 100dvh", phone)
        self.assertIn("flex-direction: row", phone)
        self.assertIn("overflow-x: auto", phone)
        self.assertIn("#mix-touch, #mix-amb, #mix-fx { grid-template-columns: 1fr; }", phone)

    def test_the_marked_row_is_a_bar_and_not_an_animation_under_reduced_motion(self):
        self.assertIn("@media (prefers-reduced-motion: reduce) { .mix-row.flash { animation: none; box-shadow: inset 3px 0 0 var(--warn); } }", HTML)

    def test_a_clamped_about_line_keeps_its_whole_text_as_a_title(self):
        rules = re.findall(r"(?:^|\n)\s*\.mix-row \.mix-about\s*\{([^}]*)\}", HTML)   # the base rule and the clamp are two rules with one selector
        self.assertTrue(any("-webkit-line-clamp: 2" in r for r in rules))
        self.assertIn("a.title = a.textContent.trim()", HTML)


if __name__ == "__main__":
    unittest.main()
