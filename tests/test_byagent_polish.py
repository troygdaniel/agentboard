"""By agent polish (Nov 3): review and ask cards fit a lane, the card's status text takes the chip's place, and two more Motion
pairings (a new lane sliding in with its card's settle, the edge bar drawing itself in at review with the chime), off until chosen."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class FitTests(unittest.TestCase):
    def test_a_review_or_ask_card_fits_a_lane(self):
        self.assertIn(".card-reply .rr { display: flex; flex-wrap: wrap; gap: 6px; }", HTML)    # Send drops under the field when the card is narrow
        self.assertIn(".card-reply .rr input { flex: 1 1 150px; }", HTML)
        self.assertIn(".card-reply .rr .btn { flex: 0 0 auto; }", HTML)
        self.assertIn(".top .when { margin-left: auto; white-space: nowrap; min-width: 0; overflow: hidden; text-overflow: ellipsis; }", HTML)
        self.assertIn("color: var(--muted); min-height: 20px; min-width: 0; }", HTML)         # .top can shrink, so the ellipsis has somewhere to happen

    def test_the_status_text_takes_the_chips_place_in_a_lane(self):
        self.assertIn("body.byagent .col.acol .card .who { display: none; }", HTML)
        self.assertIn("body.byagent .col.acol .card .top .when { margin-left: 0; }", HTML)
        self.assertIn("body.byagent .col.acol .card .top:has(.report-link) .when { margin-left: auto; }", HTML)


class MotionTests(unittest.TestCase):
    def test_the_two_pairings_live_under_the_motion_layer_which_is_off_by_default(self):
        self.assertIn("body.motion .col.acol.enter { animation: lanein .32s ease-out; }", HTML)
        self.assertIn("body.motion .card.rev-in::after { animation: revin .7s ease-out; }", HTML)
        self.assertIn("@keyframes revin { from { clip-path: inset(0 0 100% 0); box-shadow: 0 0 18px 3px var(--c, var(--ok)); } 70% { clip-path: inset(0); } }", HTML)
        self.assertNotIn(".col.acol.enter { animation", HTML.replace("body.motion .col.acol.enter { animation", ""))   # nothing animates without the layer
        self.assertIn("{ id: 'motion', kind: 'fx', look: true, name: 'Motion', about: 'look and sound move together: a settle when an agent\\'s card lands in a lane (a new By agent lane slides in with it), the green edge drawing itself in when a card reaches review,", HTML)
        self.assertIn(".col.acol.enter, .card.rev-in::after,", HTML[HTML.index("@media (prefers-reduced-motion: reduce) { .bar b"):])   # reduced motion: still

    def test_only_a_change_draws_itself_in(self):
        self.assertIn("const revBefore = new Set(), lanesBefore = new Set(); let lanesKnown = false;", HTML)
        r = body("render")
        self.assertIn("revBefore.clear(); lanesBefore.clear(); lanesKnown = !!$('board').querySelector('.col.acol');", r)
        self.assertIn("document.querySelectorAll('#board .card.review, #h-cards-box .card.review').forEach(c => revBefore.add(c.dataset.id));", r)
        self.assertIn("$('board').querySelectorAll('.col.acol').forEach(c => lanesBefore.add(c.dataset.status.slice(6)));", r)
        self.assertIn("const revIn = reviewing && !firstRender && seen.has(t.id) && !revBefore.has(t.id);", body("card"))
        self.assertIn("${revIn ? 'rev-in' : ''}", body("card"))
        self.assertIn("const fresh = lanesKnown && !firstRender && !lanesBefore.has(n);", body("byAgentHtml"))
        self.assertIn("<section class=\"col acol${fresh ? ' enter' : ''}${laneCls(n)}\"", body("byAgentHtml"))   # laneCls: Needs you marks the lanes that wait on the owner
        # the sounds are the ones already there: the Motion settle on a column change, the review chime from the HUD poll
        self.assertIn("if (c && was !== undefined && c.closest('.col')?.dataset.status !== was) landed(c);", r)
        self.assertIn("else if (fresh.some(e => /^Ready for review:/.test(e.text))) cue.review();", HTML)


if __name__ == "__main__":
    unittest.main()
