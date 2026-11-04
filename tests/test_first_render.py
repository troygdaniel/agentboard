"""A page opened straight at #/hud or at a card's hash (Nov 4): the first render runs before the script has finished, so every
variable it reads must already be declared. hoverAgent was declared at the very end, so opening /#/hud threw at the first
render and Load's poll never started (an empty Agents column); the page recovered only on the next tick."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class FirstRenderTests(unittest.TestCase):
    def test_hover_state_is_declared_before_the_first_render_can_run(self):
        decl = PAGE.index("let hoverAgent = null;")
        self.assertLess(decl, PAGE.index("function render() {"))
        self.assertLess(decl, PAGE.index("else if (location.hash === '#/hud') openHud();"))
        self.assertEqual(PAGE.count("let hoverAgent"), 1)


if __name__ == "__main__":
    unittest.main()
