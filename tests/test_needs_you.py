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
        self.assertIn("const dkKind = t => dkSent(t) ? 2 : t.needs_input ? 0 : t.review ? 1 : 2;", PAGE)
        d = body("deckHtml")
        self.assertIn("by.doing.filter(t => dkKind(t) < 2)", d)
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
        self.assertIn("'Top of the pile'", PAGE)
        self.assertIn("'Last one'", PAGE)

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
        for part in ("esc(h.title)", "esc(c)", "esc(d.description)", "esc(e.text)", "d.body_html"):   # everything escaped but the report the server already made safe
            self.assertIn(part, more)
        self.assertNotIn("render()", body("deckDetails"))

    def test_the_gauges_go_grey_for_agents_with_nothing_in_the_pile(self):
        self.assertIn("laneAway.clear(); new Set(by.doing.map(t => t.agent).filter(Boolean)).forEach(a => { if (!list.some(t => t.agent === a)) laneAway.add(a); });", body("deckHtml"))
        self.assertIn("if (MEFIRST) { deckJump(who); return; }", PAGE)   # and a gauge moves the pile to that agent's card
        self.assertIn(".ls-g.away{filter:grayscale(1);opacity:.38}", PAGE)

    def test_no_motion_under_reduced_motion(self):
        self.assertIn("if (RM) { deckPose(at, 'still'); deckFill(); return; }", body("deckSettle"))
        self.assertIn("@media (prefers-reduced-motion: reduce){.deck,.deck *{transition:none !important}", PAGE)


class SharedTests(unittest.TestCase):
    def test_by_agent_says_what_a_waiting_agent_waits_for(self):
        lanes = body("byAgentHtml")
        self.assertIn("wOf(c) ? 'sign off' : 'answer'", lanes)
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
