"""Text contrast on the Watch tiles (sweep2-ux, 16 Nov). A tile's agent name, its state word, its "You · Answer" line and the digit in its orb were drawn in the agent's or the state's own colour
straight onto a tile tinted with that colour: 3.5 to 1 for the pink agent's name, 3.9 for "Silent", 4.4 for "You · Answer" and 2.8 for the pink digit in the light theme (the pink digit and name
were 2.9 and 4.1 in the dark one). They are now mixed toward the text colour: darker in the light theme, lighter in the dark one. A unit test cannot read a gradient, so this pins the four
rules; the real check, each text's ratio worked out from a screenshot in both themes, is tests/qa/tile_contrast_check.mjs: `node tests/qa/tile_contrast_check.mjs`."""
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class TileContrastTests(unittest.TestCase):
    def test_the_orbs_digit_is_mixed_toward_the_text_colour(self):
        self.assertIn(".orb i { position: relative; z-index: 1; font-style: normal; font-size: 21px; font-weight: 700; color: color-mix(in srgb, var(--c) 80%, var(--text)); }", HTML)

    def test_the_agent_name_on_a_tile_is_mixed_toward_the_text_colour(self):
        self.assertIn("text-transform: uppercase; color: color-mix(in srgb, var(--c) 78%, var(--text)); }", HTML)

    def test_the_state_word_is_mixed_toward_the_text_colour(self):
        self.assertIn("letter-spacing: .06em; color: color-mix(in srgb, var(--sc) 80%, var(--text)); white-space: nowrap; }", HTML)

    def test_the_you_line_is_mixed_toward_the_text_colour(self):
        self.assertIn(".w-verb { font-style: normal; font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: color-mix(in srgb, var(--y) 80%, var(--text)); }", HTML)

    def test_a_waiting_tiles_name_still_uses_the_plain_text_colour(self):
        self.assertIn(".w-waiting .w-tx b { color: var(--text); }", HTML)


if __name__ == "__main__":
    unittest.main()
