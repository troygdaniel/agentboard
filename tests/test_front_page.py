"""The front page (Nov 13): three tabs, Now, Watch and Map. Now is the pile of cards waiting on the owner; when the last one leaves it flows
into Watch, the whole team as large cards, six to a page; Map is the board. A card that asks several things shows them one step at a time.
These read the page and the server; how it moves is checked in a browser."""
import re
import unittest
from pathlib import Path

from agentboard import cli, nav
from tests.test_reports import HttpTests as _Http

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def body(name):
    return re.search(rf"function {name}\(.*?\n\}}", PAGE, re.S).group(0)


class Routes(_Http):
    def test_watch_has_its_own_address_and_the_shared_bar_lists_the_three(self):
        for path in ("/", "/need", "/watch"):
            self.assertEqual(self.get(path)[0], 200, path)
        self.assertEqual([t[1] for t in nav.TABS], ["Now", "Watch", "Map"])
        self.assertEqual([t[2] for t in nav.TABS], ["/need", "/watch", "/"])


class Tabs(unittest.TestCase):
    def test_the_row_is_now_watch_map_and_the_keys_follow_it(self):
        row = re.search(r'<nav class="ab-tabs" aria-label="Pages">(.*?)</nav>', PAGE).group(1)
        self.assertEqual(re.findall(r'id="(tab-\w+)"', row), ["tab-need", "tab-watch", "tab-board"])
        go = body("goTab")
        self.assertIn("if (i === 2) { nowWatch = false; goView(0); return; }", go)      # the third tab is the board
        self.assertIn("nowWatch = i === 1; nowPinned = i === 0;", go)
        self.assertIn("const was = tabNow(); if (was === i) return;", go)                # pressing the tab you are on does nothing

    def test_the_bare_address_opens_now_and_an_emptied_pile_flows_into_watch(self):
        self.assertIn("if (!BYAGENT && !MEFIRST && !SOLO && !hudIsOpen() && !openId && !location.hash) setTimeout(() => goView(2), 0);", PAGE)
        d = body("deckHtml")
        self.assertIn("if (!n && (lastPileN > 0 || !nowPinned)) { nowWatch = true; nowPinned = false; }", d)
        self.assertIn("if (nowWatch) return watchHtml(by, n);", d)
        self.assertIn("let nowWatch = location.pathname.replace(/\\/+$/, '').endsWith('/watch');", PAGE)

    def test_the_cards_on_screen_travel_between_tabs_and_the_names_are_taken_back(self):
        go = body("goTab")
        self.assertIn("if (!document.startViewTransition || RM || watchOpenId) { watchOpenId = null; go(); return; }", go)   # no feature, or reduced motion: it just switches
        self.assertIn("t.finished.finally(() => { vtNames(false);", go)
        names = body("vtNames")
        self.assertIn("if (!id || seen.has(id)) return;", names)                         # one name per card: a duplicate would cancel the whole move
        self.assertIn("id.replace(/[^a-zA-Z0-9_-]/g, '_')", names)                       # a card's id never reaches CSS raw


class Keys(unittest.TestCase):
    def test_the_sheet_leads_with_eight_and_folds_the_rest(self):
        core = re.search(r'<dl class="keys-core">(.*?)</dl>', PAGE, re.S).group(1)
        self.assertEqual(core.count("<dt>"), 8)
        for row in ("<dd>Now, Watch, Map</dd>", "<dd>Open the card's details, or close them</dd>", "<dd>Reply to the card's agent</dd>", "<dd>Tell ORCH something</dd>"):
            self.assertIn(row, core)
        self.assertIn('<details class="keys-more"><summary>More keys</summary>', PAGE)

    def test_the_keys_that_were_cut_are_cut_everywhere(self):
        for key in ("j", "k", "a", "h", "t", "e", "f", "m", "[", "]"):
            self.assertNotIn(f"e.key === '{key}'", PAGE, key)
            self.assertNotIn(f"<dt><kbd>{key}</kbd></dt>", PAGE, key)
        self.assertIn("const map = { ArrowDown: 'down', ArrowUp: 'up', ArrowLeft: 'left', ArrowRight: 'right' };", PAGE)
        self.assertNotIn("deckDetails(e.key === 'ArrowRight')", PAGE)                    # on Now the arrows only move

    def test_enter_is_details_on_both_and_the_slash_is_orch_except_in_settings(self):
        self.assertIn("if (e.key === 'Enter' && watchSel) { e.preventDefault(); e.stopImmediatePropagation(); watchToggle(watchSel); return; }", PAGE)
        self.assertIn("if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || mixIsOpen() ||", PAGE)


class Watch(unittest.TestCase):
    def test_everyone_is_a_large_card_in_a_fixed_order_and_every_word_is_escaped(self):
        w = body("watchHtml")
        self.assertIn("name(a).localeCompare(name(b), undefined, { numeric: true }) || a.id.localeCompare(b.id)", w)   # a card never moves because it was updated
        self.assertIn("const cards = [...mains.map(tile), ...[...groups.values()].map(waitTile), ...idle.map(idleTile)]", w)
        self.assertIn("g[0]._more = g.slice(1); return g[0];", w)                     # one card per working agent: the card it last reported on, and how many more
        self.assertIn("esc(t._more.map(x => x.title).join(' · '))", w)
        for part in ("esc(name(t))", "esc(line)", "esc(t.title)", "esc(y.say || verb)", "esc(a)", "esc(t.id)"):
            self.assertIn(part, w)
        self.assertIn("const watchPer = () => innerWidth >= 1180 ? 6 : innerWidth >= 780 ? 4 : 2;", PAGE)

    def test_a_change_is_shown_as_a_change(self):
        w = body("watchHtml")
        self.assertIn("moved = !!was && (dp !== 0 || was.line !== line)", w)
        self.assertIn('${dp > 0 ? `<u class="w-delta">+${dp}%</u>` : \'\'}', w)
        s = body("watchSettle")
        self.assertIn("watchPrev.set(id, { p: +el.dataset.p, line: el.dataset.line, dn: +el.dataset.dn || 0 });", s)
        self.assertIn("[data-watch]", s)                                                 # only working cards are remembered: the others carry no progress
        self.assertIn("if (!document.querySelector('.deck.watch .w-track')) return;", s)

    def test_the_arrows_walk_a_page_and_its_side_edges_turn_it(self):
        m = body("watchMove")
        self.assertIn("document.querySelectorAll('.w-page.cur .w-nav')", m)
        self.assertIn("else if (dx) watchGo(watchPage + dx, c.top); else touch('bump');", m)   # up and down stop at the edge
        g = body("watchGo")
        self.assertIn("if (k < 0 || k >= watchPages) { touch('bump'); return false; }", g)
        self.assertIn("pg.inert = !cur;", g)                                             # a page you cannot see cannot take the keyboard
        self.assertIn("watchPing.delete(k);", g)                                         # its dot stops calling once you look

    def test_a_card_opens_where_it_is_and_goes_back(self):
        t = body("watchToggle")
        self.assertIn("if (wid && wid.startsWith('idle:')) { touch('bump'); return; }", t)
        self.assertIn(".onfinish = () => render();", t)                                  # closing: back to its place, then the grid
        self.assertIn(".w-tile.lifted { visibility: hidden; }", PAGE)
        self.assertIn(".replace(' lifted', '').replace(' sel', '')", body("watchHtml"))  # the open copy is not the hidden one
        self.assertIn("const fc = document.querySelector('.w-focus[data-new]');", body("watchSettle"))
        self.assertNotIn("openPanel(", body("watchToggle"))                              # never the side panel


class Steps(unittest.TestCase):
    def test_several_things_to_do_are_shown_one_at_a_time(self):
        y = body("youOf")
        self.assertIn("if (steps.length > 1) {", y)
        self.assertIn("verb: `Step ${i + 1} of ${steps.length}`, say: steps[i]", y)
        self.assertIn("verb: 'Sign off', say: t.result || t.status_text || '', sub: `All ${steps.length} steps done`", y)
        self.assertIn("!/^(nothing|none|n\\/a)\\b/i.test(x)", PAGE)
        c = body("card")
        self.assertIn('data-step="${esc(t.id)}">Done · next step</button>', c)
        self.assertIn("data-text=\"${esc(`I'm stuck on step ${you.step + 1}: “${you.say}”. Help me with just this step, in one line.`)}\"", c)
        self.assertIn("(slot.querySelector('[data-step]') || slot.querySelector('[data-done]'))", body("deckSpace"))   # Space, Space advances a step too

    def test_the_three_small_words_on_the_open_card(self):
        c = body("card")
        self.assertIn('data-simpler="${esc(t.id)}"', c)
        self.assertIn('data-snooze="${esc(t.id)}"', c)
        self.assertIn("quickReply(sm.dataset.simpler, 'Be simpler: one line. What is the one thing I need to do?', sm)", PAGE)
        self.assertIn("(!!a.owner_later - !!b.owner_later) || dkKind(a) - dkKind(b)", body("deckHtml"))   # put off: last in the pile, whatever it asks

    def test_sign_off_all_only_offers_what_reported_passing_tests(self):
        self.assertIn("const ok = deckIds.map(id => byId.get(id)).filter(x => x && dkPassed(x)); return ok.length > 1 ?", body("deckHeadHtml"))
        self.assertIn("esc(ok.map(x => x.title).join(' · '))", body("deckHeadHtml"))
        self.assertIn("ids.forEach((id, i) => setTimeout(() => {", PAGE)
        self.assertIn("move(id, 'done'); }, i * 420));", PAGE)


class OwnerMarks(_Http):
    """Which step you are on, and what you put off, are kept on the card: the same on every screen, gone when the wait they belong to ends."""
    def spa(self):   # made in each test, not in setUp: the shared fixture's own tests count the cards they find
        self.s.add("Spa shortlist", status="todo", task_id="spa")
        self.s.claim("spa", "atlas")
        self.s.review("spa", "Five options", body_md="## Next\n- open the report\n- pick one\n- reply with its number", by="atlas")

    def card(self):
        import json
        return next(t for t in json.loads(self.get("/api/tasks")[1])["tasks"] if t["id"] == "spa")

    def test_a_step_and_later_are_saved_and_served_and_neither_is_activity(self):
        self.spa()
        before = self.card()["updated"]
        self.assertEqual(self.post("/api/owner-mark", {"id": "spa", "step": 2}), {"ok": True, "owner_step": 2, "owner_later": False})
        self.post("/api/owner-mark", {"id": "spa", "later": True})
        t = self.card()
        self.assertEqual((t["owner_step"], t["owner_later"]), (2, True))
        self.assertEqual(t["updated"], before)                                # the card does not look fresher because you ticked a step
        self.assertFalse(any("step" in str(e.get("text", "")).lower() for e in self.s.get(self.s.load(), "spa")["log"]))
        self.post("/api/owner-mark", {"id": "spa", "step": 0, "later": False})
        t = self.card()
        self.assertNotIn("owner_step", t)
        self.assertNotIn("owner_later", t)

    def test_only_a_whole_number_in_range_a_real_flag_and_a_card_in_doing(self):
        self.spa()
        import urllib.error
        for bad in ({"id": "spa", "step": -1}, {"id": "spa", "step": 51}, {"id": "spa", "step": "2"}, {"id": "spa", "step": True}, {"id": "spa", "later": "yes"}, {"id": "spa"}, {"id": "nope", "step": 1}):
            with self.assertRaises(urllib.error.HTTPError, msg=bad):
                self.post("/api/owner-mark", bad)
        self.s.add("Idle", status="todo", task_id="idle")
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/owner-mark", {"id": "idle", "step": 1})

    def test_the_marks_end_with_the_wait_they_were_made_in(self):
        self.spa()
        mark = lambda: self.post("/api/owner-mark", {"id": "spa", "step": 2, "later": True})
        gone = lambda: self.assertFalse({"owner_step", "owner_later"} & set(self.s.get(self.s.load(), "spa")))
        mark(); self.s.review("spa", "Five options, again", body_md="## Next\n- nothing", by="atlas"); gone()      # a new report
        mark(); self.s.ask("spa", "Which one?", by="atlas"); gone()                                                  # a new question
        self.s.review("spa", "Ready", body_md="## Next\n- nothing", by="atlas")
        mark(); self.s.update("spa", status="done"); gone()                                                          # the card closed

    def test_the_page_reads_them_from_the_card_and_not_from_the_browser(self):
        self.assertIn("const i = Math.min(t.owner_step || 0, steps.length);", PAGE)
        self.assertIn("await api('/api/owner-mark', { id: t.id, ...mark });", PAGE)
        self.assertIn("catch (err) { Object.assign(t, was);", PAGE)          # a refused save is put back on screen
        for old in ("ab-steps", "stepAt", "snz."):
            self.assertNotIn(old, PAGE)


class Orch(unittest.TestCase):
    def test_one_line_goes_to_orch_and_its_answer_comes_back_escaped(self):
        self.assertIn('<form id="orch-line" autocomplete="off">', PAGE)
        self.assertIn("await api('/api/chat', /^@[\\w-]+\\s/.test(text) ? { text } : { text, to: 'ORCH' });", PAGE)   # "@name ..." is addressed by the server, as in the chat drawer
        self.assertIn("bub.innerHTML = `<span aria-hidden=\"true\">${esc(nodeGlyph(last.sender))}</span><p><b>${esc(last.sender)}</b>${esc(last.text)}</p>`;", PAGE)
        self.assertIn("return m.kind === 'agent' && m.text && (to === 'you' || to === String(OWNER || '').toLowerCase());", PAGE)   # only a line written to you rises
        self.assertIn("if (orchSeen === null) { orchSeen = last.seq; return; }", PAGE)  # what ORCH said before you arrived is not announced


class Flow(unittest.TestCase):
    """Nov 13, later: fewer trips. The bottom line writes to anyone, a card shows its steps as dots, and coming back says what changed."""
    def test_at_offers_the_names_and_every_one_is_escaped(self):
        w = body("orchWho")
        self.assertIn("m = /^@([\\w-]*)$/.exec(v)", w)
        self.assertIn('data-who="${esc(n)}"', w)
        self.assertIn("${esc(nodeGlyph(n))}</i>${esc(n)}</button>", w)
        self.assertIn(".slice(0, 8)", w)
        self.assertIn("window.addEventListener('keydown', e => { if (e.key !== 'Tab' || !e.target.closest?.('#orch-line')) return;", PAGE)   # Tab takes the first name

    def test_coming_back_says_what_changed_and_never_for_a_glance_away(self):
        self.assertIn("let awaySnap = null, awayAt = 0, backAfterMs = 60000;", PAGE)
        self.assertIn("else if (awaySnap && Date.now() - awayAt >= backAfterMs) setTimeout(awayShow, 1500);", PAGE)
        a = body("awayShow")
        self.assertIn("if (!need && !done && !moved) return;", a)                       # nothing changed: nothing is said
        self.assertIn("el.className = 'backline';", a)                                  # not "away": the greyed rings in the strip own that word
        self.assertNotIn("querySelectorAll('.away')", PAGE)
        self.assertNotIn("${esc(", a)                                                   # it prints counts only, no card text
        self.assertIn("@media (prefers-reduced-motion: reduce) { .backline, .orch-who { animation: none; } }", PAGE)

    def test_step_dots_and_the_way_to_the_whole_card(self):
        self.assertIn("Array.from({ length: y.steps }, (_, k) => `<s class=\"${k < y.step ? 'dn' : k === y.step ? 'at' : ''}\"></s>`)", PAGE)
        self.assertIn('class="deck-full" data-full="${esc(d.id)}">Everything on this card ›</button>', body("deckMoreHtml"))
        self.assertIn("const fc = e.target.closest?.('[data-full]'); if (fc) { const id = fc.dataset.full; setTimeout(() => openPanel(id), 0); }", PAGE)


class Life(unittest.TestCase):
    def test_what_moves_means_something_and_all_of_it_stops_when_asked(self):
        self.assertIn("document.documentElement.style.setProperty('--heat', working.length ? (nn / working.length).toFixed(2) : 0);", PAGE)
        self.assertIn("body.deckview #aura i { animation-play-state: paused; }", PAGE)   # the pile has its own life
        for rule in ("#aura i, .orbit, .dial span.on { animation: none; }", ".w-track { transition: none; }", "::view-transition-group(*), ::view-transition-old(*), ::view-transition-new(*) { animation: none !important; }"):
            self.assertIn(rule, PAGE)
        for fn in ("sparkle", "greet"):
            self.assertIn("if (RM", body(fn) if fn == "sparkle" else PAGE[PAGE.index("function greet("):][:700])

    def test_the_frame_holds_still_while_the_cards_travel(self):
        # the top bar shimmered for a few frames on every tab change: the page's snapshot was cross-fading onto a copy of itself
        self.assertIn("#board { view-transition-name: ab-main; }", PAGE)                 # only the board's own area slides
        self.assertIn("::view-transition-old(root) { display: none; } ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }", PAGE)
        self.assertIn("::view-transition-old(ab-main) { animation: vtout .28s ease both; }", PAGE)
        self.assertNotIn("::view-transition-old(root) { animation: vtout", PAGE)

    def test_the_greeting_is_once_a_day_and_the_tab_icon_follows_the_badge(self):
        g = PAGE[PAGE.index("function greet("):][:900]
        self.assertIn("localStorage.setItem('ab-greeted', today)", g)
        self.assertIn("esc(part + who)", g)
        self.assertIn("favSync(+b.textContent || 0);", PAGE)
        self.assertIn("if (!link || favSync.was === n) return;", body("favSync"))

    def test_only_what_you_do_makes_a_touch_sound(self):
        touch = re.search(r"const TOUCH = \{(.*?)\n\};", PAGE, re.S).group(1)
        for kind in ("travel:", "rise:", "settle:", "page:", "stepup:", "stuck:", "later:", "batch:"):
            self.assertIn("  " + kind, touch)
        for fn in ("watchSettle", "watchHtml", "favSync"):
            self.assertNotIn("touch", body(fn), fn)                                      # an agent's step, ORCH's answer, the greeting: the board's own cues, never Touch

    def test_one_accent_and_nothing_from_outside(self):
        self.assertEqual(PAGE.count("#e8590c"), 1)
        for outside in ("cdnjs", "googleapis", "unpkg", "getUserMedia("):
            self.assertNotIn(outside, PAGE)


if __name__ == "__main__":
    unittest.main()
