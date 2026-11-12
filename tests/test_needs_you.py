"""Needs you (Nov 11): the third tab. The cards waiting on the owner as a pile you move through: one card open (the board's own card), the
ones before it as strips above, the ones after it as strips below. These read the page and the server; how the motion looks is checked in
a browser."""
import re
import unittest
from pathlib import Path

from agentboard import cli, nav
from tests.test_reports import HttpTests as _Http

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def body(name):
    return re.search(rf"function {name}\(.*?\n\}}", PAGE, re.S).group(0)


class RouteTests(_Http):
    def test_need_serves_the_board_page_like_the_other_two_views(self):
        for path in ("/", "/agents", "/need"):
            status, page, headers = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn('id="tab-need"', page if isinstance(page, str) else page.decode(), path)
            self.assertIn("Content-Security-Policy", headers, path)

    def test_the_shared_bar_links_to_it(self):
        self.assertIn(("need", "Needs you", "/need"), nav.TABS)
        self.assertEqual(len(nav.TABS), 3)


class ViewSwitchTests(unittest.TestCase):
    def test_one_two_three_open_the_three_tabs_and_the_ring_has_three_views(self):
        self.assertIn("if ((e.key === '1' || e.key === '2' || e.key === '3') && !SOLO && !e.altKey) { e.preventDefault(); goView(+e.key - 1); return; }", PAGE)
        self.assertIn("const curView = () => MEFIRST ? 2 : BYAGENT ? 1 : 0;", PAGE)
        self.assertIn("agents = i >= 1, need = i === 2", body("goView"))
        self.assertIn("<kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></dt><dd>Board, By agent, Needs you</dd>", PAGE)

    def test_back_and_forward_follow_the_address(self):
        self.assertIn("need ? '/need' : agents ? '/agents' : '/'", body("setView"))
        self.assertIn("need = path.endsWith('/need'), agents = need || path.endsWith('/agents')", PAGE)

    def test_the_pile_is_drawn_by_the_same_card_function_in_the_same_redraw(self):
        self.assertIn("$('board').innerHTML = MEFIRST ? deckHtml(by, q || flagFilter) : BYAGENT ? byAgentHtml(by, q || flagFilter) :", body("render"))
        self.assertIn("${card(t)}", body("deckHtml"))   # the board's own card: its reply box, quick answers and Mark done come with it
        self.assertNotIn("MEFIRST", body("byAgentHtml"))   # By agent is plain lanes; it does not know about the pile


class PileTests(unittest.TestCase):
    def test_asks_first_then_sign_offs_and_an_answered_card_has_left(self):
        self.assertIn("const dkKind = t => dkSent(t) ? 9 : t.needs_input ? 0 : t.review ? 1 : dkDog(t.id) ? 2 : 9;", PAGE)
        d = body("deckHtml")
        self.assertIn("by.doing.filter(t => dkKind(t) < 3)", d)
        self.assertIn("dkKind(a) - dkKind(b) || heldBy(b.id).length - heldBy(a.id).length", d)   # then the one holding the most Todo cards

    def test_the_whole_layout_comes_from_one_position_and_a_move_redraws_nothing(self):
        pose = body("deckPose")
        self.assertNotIn("innerHTML = deckHtml", pose)
        self.assertNotIn("render()", pose)
        self.assertIn("el.style.setProperty('--a'", pose)   # how far a card is from the open one
        self.assertIn("el.style.setProperty('--o'", pose)   # how open it is
        self.assertIn("function deckGo(to) { const i = deckIds.indexOf(to); if (i < 0) return; deckPose(i); }", PAGE)

    def test_it_does_not_wrap(self):
        step = body("deckStep")
        self.assertIn("if (j < 0 || j >= deckIds.length) {", step)   # past an end: a small bump, and you stay where you are
        self.assertNotIn("%", step)
        self.assertNotIn("'Top of the pile'", PAGE)   # the counter and the rail say where the ends are
        self.assertNotIn("'Last one'", PAGE)

    def test_the_hand_moves_it_continuously_and_it_settles_on_a_card(self):
        self.assertIn("deckPose(lim(want), 'drag')", PAGE)
        self.assertIn("Math.round(p + extra)", PAGE)
        self.assertIn(".deck.drag .deck-slot,.deck.drag .deck-slot *", PAGE)   # while dragging nothing eases: it follows

    def test_one_key_never_answers(self):
        space = body("deckSpace")
        self.assertIn("if (deckArm === t.id) { deckDisarm(true); btn.click(); return; }", space)   # only the second press clicks
        self.assertIn("deckArmT = setTimeout(() => deckDisarm(false), 3000);", space)
        keys = PAGE[PAGE.index("else if (e.key === 'Enter' && !(t && t.closest && t.closest('button, a')))"):][:400]
        self.assertIn("inp.focus()", keys)   # Enter only puts you in the reply box
        self.assertNotIn(".click()", keys)

    def test_typing_in_the_reply_box_keeps_the_keys(self):
        self.assertIn("if (typing) { if (e.key === 'Escape') t.blur(); return; }", PAGE)

    def test_the_details_open_beside_the_card_from_the_feed_the_panel_reads(self):
        self.assertIn("fetch(BASE + '/api/task?id=' + encodeURIComponent(id)", body("deckFill"))
        more = body("deckMoreHtml")
        for part in ("esc(h.title)", "esc(c)", "d.description_html", "fmt(d.description)", "esc(e.text)", "d.body_html"):   # everything escaped but what the server already made safe
            self.assertIn(part, more)
        self.assertNotIn("render()", body("deckDetails"))

    def test_the_gauges_go_grey_for_agents_with_nothing_in_the_pile(self):
        self.assertIn("laneAway.clear(); new Set(by.doing.map(t => t.agent).filter(Boolean)).forEach(a => { if (!list.some(t => t.agent === a)) laneAway.add(a); });", body("deckHtml"))
        self.assertIn("if (MEFIRST) { deckJump(who); return; }", PAGE)   # and a gauge moves the pile to that agent's card
        self.assertIn(".ls-g.away{filter:grayscale(1);opacity:.38}", PAGE)

    def test_no_motion_under_reduced_motion(self):
        self.assertIn("if (RM) { deckPose(at, 'still'); deckFill(); return; }", body("deckSettle"))
        self.assertIn("@media (prefers-reduced-motion: reduce){.deck,.deck *{transition:none !important}", PAGE)


class StuckAndClearedTests(unittest.TestCase):
    def test_a_stuck_card_is_the_watchdogs_finding_and_its_fix_is_the_watchdogs(self):
        # only what the watchdog calls stuck (quiet past the threshold with nothing to wake it), never every quiet card
        self.assertIn("const dkDog = id => (boardDog || []).find(f => f.id === id && (f.kind === 'stuck' || f.kind === 'claimed-idle'))\n", PAGE)
        head = body("deckHeadHtml")
        self.assertIn('class="deck-fix" data-dog-action="${esc(dog.fix.action)}" data-dog-id="${esc(dog.fix.id)}"', head)   # the board's own fix button and route
        self.assertIn("'has gone quiet'", head)
        self.assertIn("$('board').querySelector('.deck-head .deck-fix')", body("deckSpace"))   # Space, Space does the same, still two presses
        self.assertIn("working.filter(t => !t.needs_input && !t.review && dkDog(t.id)).length", body("render"))   # and the tab counts it

    def test_an_agent_that_left_several_cards_behind_is_released_in_one_press(self):
        # only its stuck cards, each by the watchdog's own single release: release-all would take its questions and sign-offs too
        self.assertIn("const dkMates = t => deckIds.map(id => byId.get(id)).filter(c => c && c.agent === t.agent && dkKind(c) === 2 && (c.progress || 0) < 100);", PAGE)
        head = body("deckHeadHtml")
        self.assertIn("mates.length > 1 ?", head)                       # one stuck card has its own button and needs no second
        self.assertIn('data-deck-all="${esc(top.agent)}"', head)
        self.assertIn("Release all ${mates.length} of ${esc(top.agent)}", head)
        self.assertLess(head.index("${fix}"), head.index("${all}"))     # Space, Space still finds the single release first
        self.assertIn("await api('/api/watchdog-fix', { action: 'release', id: c.id });", PAGE)
        self.assertNotIn("action: 'release-all'", PAGE)
        self.assertIn("if (c.id !== deckTop) deckCleared.push({ id: c.id, title: c.title, agent: c.agent, word: 'Released', undo: null });", PAGE)

    def test_a_card_the_board_marks_abandoned_is_in_the_pile_even_when_its_agent_still_listens(self):
        # the watchdog skips a holder with a wait running, so its finding alone left out cards the board itself shows as "abandoned?"
        self.assertIn("const dkStale = t => !!t && t.status === 'doing' && !isKid(t) && ago(t.updated).min >= (cfg.stale_minutes || DEFAULT_STALE_MIN);", PAGE)
        self.assertIn("|| (dkStale(byId.get(id)) ? { id, kind: 'abandoned',", PAGE)
        self.assertIn("fix: { action: 'release', id, label: 'Release to Todo' } } : null);", PAGE)   # the same release, the watchdog's
        head = body("deckHeadHtml")
        self.assertIn("' · its agent still listens' : ' · nothing will wake it'", head)
        self.assertIn("full = k === 2 && (top.progress || 0) >= 100", head)        # finished work nobody handed in: Mark done comes first
        self.assertIn('class="deck-fix" data-done="${esc(top.id)}"', head)
        self.assertLess(head.index("${fin}"), head.index("${fix}"))
        self.assertIn("const mates = !full && dog", head)                          # and release-all never takes a finished card

    def test_what_you_cleared_is_ticked_and_only_the_last_sign_off_can_be_undone(self):
        h = body("deckClearedHtml")
        self.assertIn("can = i === last && c.undo", h)
        self.assertIn("deckCleared.slice(-5)", h)
        self.assertIn("' · an answer cannot be unsent'", h)
        self.assertIn("undo: word === 'Signed off' && undoInfo && undoInfo.prev && undoInfo.prev.id === gone ?", body("deckSettle"))
        self.assertIn("await api('/api/restore', c.undo);", PAGE)   # the same restore the toast's Undo uses
        for part in ("esc(c.word)", "esc(c.title)"):
            self.assertIn(part, h)


class CalmPileTests(unittest.TestCase):
    """The open card says who, what and how long. Everything around it says only what the card does not."""
    def test_the_line_above_keeps_the_count_what_it_holds_and_a_quiet_cards_fix(self):
        head = body("deckHeadHtml")
        self.assertIn("return `<b title=\"${esc(top.agent || 'Unassigned')} ${what}\">${at + 1}<i> of ${n}</i></b>", head)
        self.assertIn('<span class="deck-holds"', head)
        self.assertIn("${fin}${fix}${all}${hint}", head)
        self.assertNotIn('class="you ', head)                    # the You line is on the card, once
        self.assertNotIn("dkAge(top)", head)

    def test_what_the_open_card_hides_is_in_the_details(self):
        self.assertIn(".deck-slot.front .card .title { display: none; }", PAGE)
        self.assertIn('return `<h2 class="deck-name">${esc(d.title || \'\')}</h2>`', body("deckMoreHtml"))

    def test_hints_and_arrows_wait_for_a_hover_or_focus_and_an_armed_send_always_shows(self):
        self.assertIn(".deck-head em.keys:not(.armed) { opacity: 0 !important;", PAGE)
        self.assertIn(".deck-head:focus-within em.keys { opacity: .8 !important; }", PAGE)
        self.assertIn(".deck-rail .deck-nav:focus-visible { opacity: 1; }", PAGE)
        self.assertIn(".deck-slot:not(.front) .who .nm { display: none; }", PAGE)   # a strip is a face and a sentence

    def test_the_empty_pile_says_it_in_two_words(self):
        self.assertIn("<strong>All clear</strong>", body("deckHtml"))
        self.assertIn("<span>${by.doing.length} working</span>", body("deckHtml"))


class TaskTextTests(_Http):
    """The details panel's "The task" was the description as one escaped paragraph: a blurb. It is rendered like an agent's report."""
    def test_the_server_renders_the_description_safely_and_the_panel_uses_it(self):
        import json
        self.s.add("Pilot hosting", status="todo", task_id="host",
                   description="Find hosting.\n\n## What we need\n- one web process\n- a database\n\n1. under 20 dollars\n\n<script>alert(1)</script> <img src=x onerror=alert(1)>")
        d = json.loads(self.get("/api/task?id=host")[1])
        html = d["description_html"]
        self.assertIn("What we need</h", html)                  # a heading, not "## What we need"
        self.assertEqual(html.count("<li>"), 3)
        self.assertNotIn("<script", html)                       # never raw HTML
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.s.add("No text", status="todo", task_id="bare")
        self.assertNotIn("description_html", json.loads(self.get("/api/task?id=bare")[1]))

    def test_the_panel_draws_it_as_rich_text_and_cuts_a_long_one(self):
        m = body("deckMoreHtml")
        self.assertIn('<section class="deck-task"><h3>The task</h3>${d.description_html ? `<div class="rich-body">${d.description_html}</div>`', m)
        self.assertIn('`<div class="rich-body fmt">${fmt(d.description)}</div>`', m)   # an older server: the board's own formatter, still escaped
        self.assertNotIn("<p>${esc(d.description)}</p>", PAGE)
        self.assertIn(".deck-task .rich-body{max-height:230px;overflow:hidden}", PAGE)
        self.assertIn("more.hidden = !long;", body("deckTaskFit"))                     # a short task has no button
        self.assertIn(".deck-more .rich-body :is(h1,h2,h3,h4,h5,h6){", PAGE)           # a heading in the text is not styled as the panel's own label


class SoundTests(unittest.TestCase):
    """The pile sounds through the board's Touch layer: nothing plays with sound off or that layer off, and every cue obeys its limits."""
    def test_each_move_has_its_cue_in_the_touch_vocabulary(self):
        touch = re.search(r"const TOUCH = \{(.*?)\n\};", PAGE, re.S).group(1)
        for kind in ("flip:", "bump:", "arm:", "disarm:", "sent:", "clear:"):
            self.assertIn("  " + kind, touch)
        self.assertIn("tap(agentPitch(agent), t + .012, .035, .8, { verb: .45 });", touch)   # a card turns in its agent's voice
        self.assertIn("deckSound('flip', top.agent, at - prevAt)", body("deckPose"))
        self.assertIn("performance.now() - deckFlipAt > 45", body("deckPose"))               # a fast drag is not a rattle
        self.assertIn("if (mode !== 'still'", body("deckPose"))                              # a redraw places the pile silently
        self.assertIn("deckSound('bump')", body("deckStep"))
        self.assertIn("touch('arm')", body("deckSpace"))


class SharedTests(unittest.TestCase):
    def test_by_agent_says_what_a_waiting_agent_waits_for(self):
        lanes = body("byAgentHtml")
        self.assertNotIn("wOf(c) ? 'sign off' : 'answer'", lanes)   # the card's You line says the verb and the time; the rule keeps its bar and what it holds
        self.assertIn("wOf(c) ? 'frees' : 'holds'", lanes)   # an ask holds its Todo cards until the card is done; a sign-off frees them
        self.assertIn('class="holds-btn"', lanes)
        self.assertIn("if (doingBy.has('')) active.push('');", lanes)

    def test_a_card_lights_what_it_holds_and_a_held_card_lights_its_blocker(self):
        self.assertIn("held.length ? held : up ? [up] : []", body("linkPaint"))
        self.assertIn("if (!key || key === linkKey) return;", body("linkOn"))   # staying on the same card restarts nothing
        self.assertIn("tb.scrollTo({ top: todoTop", body("linkOff"))            # Todo goes back to where it was

    def test_lanes_that_stay_slide_and_lanes_that_leave_fade_where_they_stood(self):
        draw = body("render")
        self.assertIn("const laneSnap = laneSnapshot();", draw)
        self.assertLess(draw.index("$('board').innerHTML ="), draw.index("laneSettle(laneSnap);"))
        r = body("laneSettle")
        self.assertIn("position:fixed", r)
        self.assertNotIn("scaleX", r)

    def test_one_accent_theme_colours_and_nothing_from_outside(self):
        self.assertIn(":root{--need:#e8590c}", PAGE)
        self.assertEqual(PAGE.count("#e8590c"), 1)        # every other use goes through the variable
        self.assertNotIn("var(--card,", PAGE)             # not one of the board's colours: it fell back to white in the dark theme
        for outside in ("cdnjs", "three.min.js", "mediapipe", "getUserMedia("):
            self.assertNotIn(outside, PAGE.replace("navigator.mediaDevices.getUserMedia(", "") if outside == "getUserMedia(" else PAGE)
        self.assertNotIn("animation:meTurn", PAGE)        # the rings stand still: turning, they repainted every frame


if __name__ == "__main__":
    unittest.main()
