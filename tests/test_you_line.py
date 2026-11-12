"""The You line and the calmer board (Nov 12). Every Doing card says, in the same place, what its owner owes it: answer, sign off, close it,
check on it, or nothing. The rest of the page says each fact once: the state colour is one wash on the card, subtasks are segments, and what
is not an action waits behind a hover or a fold. These read the page; how it looks is checked in a browser."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def body(name):
    return re.search(rf"function {name}\(.*?\n\}}", PAGE, re.S).group(0)


class YouLineTests(unittest.TestCase):
    def test_every_doing_card_is_in_exactly_one_of_five_states(self):
        y = body("youOf")
        self.assertIn("if (!t || t.status !== 'doing' || isKid(t)) return null;", y)   # only a card in Doing, never a subtask
        order = ["k: 'ask'", "k: 'rev'", "k: 'fin'", "k: 'quiet'", "k: 'none'"]          # a question beats a sign-off beats the clock
        self.assertEqual(order, sorted(order, key=y.index))
        self.assertIn("old = a.min >= (cfg.stale_minutes || DEFAULT_STALE_MIN)", y)     # quiet and finished use the board's own stale rule
        self.assertIn("if (old && full) return { k: 'fin'", y)                          # at 100% and never handed in is not "abandoned?"
        self.assertIn("return { k: 'none', verb: 'Nothing'", y)                         # needing nothing is said, not left to a missing flag

    def test_a_review_leads_with_the_agents_next_step_when_it_wrote_one(self):
        self.assertIn("const nx = youNext(t.details);", body("youOf"))
        self.assertIn("verb: nx ? 'Do this, then sign off' : 'Sign off', say: nx || t.result || t.status_text || ''", body("youOf"))
        nxt = re.search(r"function youNext\(md\) \{.*", PAGE).group(0)
        self.assertIn("##\\s*Next", nxt)
        self.assertIn("/^(nothing|none|n\\/a)\\b/i.test(l) ? '' : l", nxt)               # "Next: nothing" is a plain sign-off

    def test_the_line_is_on_the_card_and_at_the_top_of_the_panel_and_all_of_it_is_escaped(self):
        self.assertIn("const you = youOf(t), askFlag = youCard(t);", body("card"))
        self.assertIn("${top}${askFlag}${saidRow}", body("card"))                       # right under the holder, before anything else
        self.assertIn("return `${headTop}${tabs}${youPanel(t)}${askC}", body("panelHtml"))
        self.assertIn("return `${headTop}${tabs}${youPanel(t)}${doneHtml(", body("panelHtml"))
        card_fn = re.search(r"function youCard\(t\) \{.*?\n  return .*", PAGE, re.S).group(0)
        for part in ("esc(y.verb)", "esc(y.say)"):
            self.assertIn(part, card_fn)
        self.assertIn("youOf(byId.get(t.id) || t)", PAGE)                               # the panel reads the list's copy, where the report's text is

    def test_a_quiet_or_finished_card_offers_its_two_choices_and_they_are_the_boards_own(self):
        b = re.search(r"function youBtns\(.*?\n\}", PAGE, re.S).group(0)
        self.assertIn("return y.k === 'fin' ? done + nudge : y.k === 'quiet' ? nudge + rel : '';", b)
        self.assertIn('data-dog-action="release" data-dog-id="${esc(t.id)}"', b)        # the watchdog's release
        self.assertIn('data-thread="${esc(t.agent)}"', b)                               # a nudge opens the agent's thread
        self.assertIn('data-done="${esc(t.id)}"', b)
        self.assertIn('id="p-lat-done"', b)                                             # in the panel, the panel's own Mark done

    def test_the_corner_no_longer_asks_abandoned_on_a_doing_card(self):
        self.assertIn("const whenText = a.text ? (doing ? '' :", body("card"))
        self.assertIn("const when = whenText ? `<span", body("card"))


class CalmTests(unittest.TestCase):
    def test_subtasks_are_one_segment_each_and_fold_until_asked(self):
        s = body("subsBlock")
        self.assertIn('<span class="segs" aria-hidden="true" title="${d} of ${n} steps done">', s)
        self.assertIn('style="--p:${dn ? 100 : (k.progress || 0)}%"', s)
        self.assertIn("subsOpen.has(t.id) ? subsOpen.get(t.id) : false;", s)
        self.assertIn('aria-label="${d} of ${n} subtasks done', s)                      # the count is still read out
        self.assertIn(".segs:has(i:nth-child(9)) { gap: 2px; }", PAGE)                  # a long card keeps its segments apart

    def test_the_header_keeps_two_filters_and_says_all_clear(self):
        r = body("render")
        self.assertIn('data-flag="needs_input" role="button" tabindex="0"', r)
        self.assertIn('data-flag="review" role="button" tabindex="0"', r)
        self.assertIn('aria-label="${asks} to answer">⚠ ${asks}</span>', r)             # a number with its words in the label and the tooltip
        self.assertIn("(needN ? '' : '<span class=\"sum-ok\">All clear</span>')", r)
        self.assertNotIn("abandoned</span> · ", r)                                      # the cards say which are quiet and which are finished

    def test_what_is_not_an_action_waits_behind_a_hover_or_a_fold(self):
        self.assertIn('<details class="dog-fold"${dogOpen ? \' open\' : \'\'}><summary data-dog-fold>Between agents: ${hh(words)}</summary>', PAGE)
        self.assertIn('<details class="p-fold"${pFoldOpen ? \' open\' : \'\'}><summary data-p-fold>More', body("panelHtml"))
        self.assertIn("let dogOpen = false, pFoldOpen = false;", PAGE)                  # a redraw does not close what you opened
        self.assertIn("@media (hover: hover) { .card[data-status=todo] .meta", PAGE)    # with no hover (a phone) the buttons stay
        self.assertIn(".card[data-status=todo] .meta:has(.copied)", PAGE)               # a copied prompt keeps showing that it was

    def test_one_fact_once(self):
        self.assertIn(".col.acol h2 em { display: none; }", PAGE)                       # the lane's state word
        self.assertIn(".ls-g .ls-tx span { display: none; }", PAGE)                     # the ring's caption
        self.assertIn(".p-you.has-next ~ .dgrid .dsec.next { display: none; }", PAGE)   # the next step, already at the top
        self.assertIn(".p-you:is(.quiet, .fin) + .lat { display: none; }", PAGE)
        self.assertIn(".card .qr:has(.qr-ch.opt) .qr-ch:not(.opt)", PAGE)               # the agent's own options, or one Go ahead

    def test_motion_stops_when_asked_and_colours_are_the_boards(self):
        self.assertIn("@media (prefers-reduced-motion: reduce) { .segs i.lv { animation: none; } }", PAGE)
        self.assertIn(".card.y-ask { --y: var(--err); } .card.y-rev { --y: var(--ok); } .card.y-fin, .card.y-quiet { --y: var(--need); }", PAGE)
        self.assertEqual(PAGE.count("#e8590c"), 1)


if __name__ == "__main__":
    unittest.main()
