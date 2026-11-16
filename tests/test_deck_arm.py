"""The pile's two-step Space keeps its light through a redraw (sweep2-bugs, 16 Nov). Space arms the front card's first answer and lights its
button; a poll that brings another card's change redraws the pile inside the three-second window, and the rebuilt card came back without
the light while the arm stayed live, so the second Space sent an answer the screen no longer showed. A unit test cannot press a key in a
browser, so this pins the shape of the fix; the real check, with real key events in headless Chrome on a throwaway board, is
tests/qa/deck_arm_check.mjs (`node tests/qa/deck_arm_check.mjs`)."""
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body_of(start):
    """The text of the function that begins with `start`, up to its first line that starts with a closing brace."""
    at = HTML.index(start)
    return HTML[at: HTML.index("\n}", at) + 2]


class DeckArmTests(unittest.TestCase):
    def test_one_helper_names_the_button_space_arms_and_presses(self):
        helper = body_of("function deckArmTarget()")
        self.assertIn("[data-quick][data-text=\"Go ahead\"]", helper)   # a card that asks: its first answer
        self.assertIn("[data-step]", helper)                              # a card to sign off: the next step, else Mark done
        self.assertIn(".deck-head .deck-fix", helper)                     # a quiet card: the watchdog's one fix
        self.assertEqual(HTML.count("function deckArmTarget()"), 1)

    def test_space_arms_and_presses_through_that_helper(self):
        space = body_of("function deckSpace()")
        self.assertIn("btn = deckArmTarget()", space)
        self.assertNotIn("slot.querySelector('[data-quick]", space)      # not its own copy of the lookup, which the redraw could drift from

    def test_a_redraw_lights_the_button_again_while_the_arm_is_live(self):
        pose = body_of("function deckPose(")
        at = pose.index("if (deckArm === deckTop) { const b = deckArmTarget(); if (b) b.classList.add('deck-armed'); }")
        self.assertGreater(at, pose.index("innerHTML = deckHeadHtml(top, at, n)"))   # after the head is drawn, on the same redraw
        self.assertLess(pose.index("if (deckIds[at] !== deckTop && deckArm) deckDisarm(true);"), at)   # a redraw that moved to another card disarms first


if __name__ == "__main__":
    unittest.main()
