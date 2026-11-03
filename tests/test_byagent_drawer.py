"""The left drawer is Later (backlog), the same on the Board and on By agent: Todo is a column in both, so there is no Todo drawer (Nov 2)."""
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class DrawerTests(unittest.TestCase):
    def test_the_drawer_is_later_in_both_views_with_no_view_switch(self):
        self.assertNotIn("DRAWER", HTML)
        self.assertIn("renderLater(by.backlog)", HTML)
        self.assertIn("t.status === 'backlog' && !isKid(t)", HTML)
        self.assertIn('<button class="btn" id="later-btn" aria-controls="later">Later <span id="later-n"></span></button>', HTML)

    def test_by_agent_has_the_park_an_idea_form_like_the_board(self):
        render = HTML[HTML.index("function renderLater(list) {"):]
        render = render[:render.index("\nfunction setSide")]
        self.assertIn('<form class="later-add" id="later-form">', render)
        self.assertNotIn("BYAGENT", render)

    def test_the_by_agent_init_does_not_relabel_the_later_button(self):
        init = HTML[HTML.index("if (BYAGENT) {\n  document.body.classList.add('byagent');"):]
        init = init[:init.index("\n}\n")]
        for needle in ("$('later-btn')", "$('later').setAttribute('aria-label'", ".p-head strong').textContent", "$('key-later')"):
            self.assertNotIn(needle, init)

    def test_copy_prompt_and_later_buttons_work_inside_the_drawer(self):
        drawer = HTML[HTML.index("$('later-body').addEventListener('click'"):]
        drawer = drawer[:drawer.index("\n});\n")]
        self.assertIn("e.target.closest('.copy')", drawer)
        self.assertIn("copyPrompt(cb)", drawer)
        self.assertIn("[data-later]", drawer)
        self.assertEqual(HTML.count("async function copyPrompt(btn)"), 1)   # one function for the board and the drawer
        self.assertIn("return copyPrompt(btn);", HTML)   # the board uses the same function

    def test_a_redraw_on_the_by_agent_view_does_not_throw_on_agent_columns(self):
        # data-status="agent:AGENT-1" is not a key of `by`; an unguarded by[k].length threw on every redraw after the first,
        # which silently skipped the rest of render() (the Todo count, the drawer, the title) and made Copy prompt say Failed
        self.assertNotIn("n = by[k].length", HTML)
        self.assertIn("n = by[k]?.length", HTML)
        self.assertIn("n !== undefined && lastCounts[k]", HTML)


if __name__ == "__main__":
    unittest.main()
