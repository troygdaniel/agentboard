"""Look > Lively (Nov 4): one switch, off until chosen, that makes the small moments move: a card you moved settles with a ring of the
column's colour, a count rolls to its new number, a finished subtask ticks itself in, a changed % pops and its bar flashes, an empty
column breathes and its line arrives, the toast springs up, the open card's sections step in, the column under a drag lights up.
Everything is a class the CSS animates under body.lively, so nothing changes while it is off; reduced motion turns all of it off."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
LAYERS = re.search(r"const LAYERS = \[(.*?)\n\];", PAGE, re.S).group(1)


def body(name):
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\n}\n", i) + 2]


class LivelyTests(unittest.TestCase):
    def test_lively_is_a_look_switch_off_until_chosen(self):
        self.assertIn("{ id: 'lively', kind: 'fx', look: true, plain: true, name: 'Lively', about: '", LAYERS)
        self.assertIn("apply(lvl) { document.body.classList.toggle('lively', lvl > 0); } },", LAYERS.split("id: 'lively'")[1])
        self.assertEqual(re.search(r"const LAYER_ON = \{([^}]*)\}", PAGE).group(1).strip(), "touch: true")   # still the one default-on layer
        self.assertIn("const lively = () => layerOn('lively');", PAGE)

    def test_every_rule_sits_under_the_body_class(self):
        css = PAGE[PAGE.index("/* Look > Lively"):PAGE.index("</style>")]
        css = css[css.index("*/") + 2:]   # past the comment block
        rules = [l.strip() for l in css.splitlines() if l.strip() and not l.strip().startswith(("@keyframes", "@media", "body.lively", "}"))]
        self.assertEqual(rules, [".col.todo { --ring: var(--info); } .col.doing, .col.acol { --ring: var(--run); } .col.done { --ring: var(--ok); }"])   # a token only; it paints nothing by itself
        for piece in (".card.landed::before", ".col h2 .cnt.roll .rn", ".sub.just-done .check path", ".note .pct.pop", ".bar b.pop", ".empty::before", ".empty.arrive", "#toast.on", "#panel.fresh .p-body > *", ".drop", ".col.over"):
            self.assertIn("body.lively " + piece if not piece.startswith(".col.over") else "body.lively .col.over", css)

    def test_reduced_motion_turns_every_one_off_pseudo_elements_included(self):
        rm = PAGE[PAGE.index("@media (prefers-reduced-motion: reduce) {   /* a pseudo-element cannot sit inside :is()"):]
        rm = rm[:rm.index("\n  }\n") + 4]
        for piece in (".cnt.roll .rn", ".sub.just-done", ".pct.pop", ".bar b.pop", ".empty.arrive", "#toast.on", "#panel.fresh .p-body > *", ".drop"):
            self.assertIn(piece, rm)
        self.assertIn("body.lively .card.landed::before, body.lively .cnt.roll::before, body.lively .empty::before { animation: none; }", rm)
        self.assertNotIn("::before,", rm.split("body.lively :is(")[1].split(")")[0])   # none inside :is(), where CSS would drop it

    def test_the_hooks_mark_a_change_never_a_first_render(self):
        self.assertIn("const pctUp = !firstRender && lastPct.has(t.id) && lastPct.get(t.id) !== (t.progress || 0);", body("card"))
        self.assertIn("const kjust = kdone && !firstRender && lastSubDone.get(k.id) === false;", body("subsBlock"))
        self.assertIn("const dUp = !firstRender && lastSubCount.has(t.id) && lastSubCount.get(t.id) !== d; subCountNow.set(t.id, d);", body("subsBlock"))
        r = body("render")
        self.assertIn("if (!firstRender) document.querySelectorAll('.col').forEach(c => cntBefore.set(c.dataset.status, [+c.querySelector('.cnt')?.textContent, !!c.querySelector('.empty')]));", r)
        self.assertIn("if (!firstRender && lively()) livelyCounts(cntBefore);", r)
        self.assertIn("livelySummary({ needs_input: asks, review: revs, working: working.length });", r)
        self.assertIn("if (landedId) {", r)

    def test_the_moved_card_settles_where_you_sent_it_and_the_number_only_looks_rolled(self):
        self.assertIn("if (t && t.status !== status) { landedId = id; landedTo = status; }", body("move"))
        self.assertIn("if (c && (col === landedTo || (landedTo === 'doing' && col?.startsWith('agent:')))) { landedId = null; settle(c, before.has(c.dataset.id) && c.dataset.id !== justDroppedWas); }", body("render"))
        st = body("settle")
        self.assertIn("if (!lively() || RM) return;", st)
        self.assertIn("delay: glided ? 400 : 0", st)                                          # after the 420 ms glide, not under it
        rc = body("rollCount")
        self.assertIn("if (!c || RM) return;", rc)
        self.assertIn("c.innerHTML = `<span class=\"rn\">${to}</span>`;", rc)                # textContent stays the number
        self.assertIn("if (lively() && !RM) { $('panel').classList.add('fresh');", body("openPanel"))


if __name__ == "__main__":
    unittest.main()
