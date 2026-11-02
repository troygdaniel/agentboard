"""The left drawer: Later (backlog) on the board, the Todo cards on the by-agent view. One drawer, one switch (DRAWER)."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class DrawerTests(unittest.TestCase):
    def test_the_drawer_lists_backlog_on_the_board_and_todo_by_agent(self):
        m = re.search(r"const DRAWER = BYAGENT \? \{ status: '(\w+)', label: '(\w+)'.*?\n  : \{ status: '(\w+)', label: '(\w+)'", HTML, re.S)
        self.assertEqual(m.groups(), ("todo", "Todo", "backlog", "Later"))

    def test_every_list_the_drawer_shows_comes_from_the_one_switch(self):
        self.assertIn("renderLater(by[DRAWER.status])", HTML)
        self.assertIn("t.status === DRAWER.status && !isKid(t)", HTML)
        self.assertNotIn("renderLater(by.backlog)", HTML)

    def test_the_todo_drawer_has_no_park_an_idea_form_and_nothing_drags(self):
        self.assertIn("(BYAGENT ? '' : `<form class=\"later-add\"", HTML)
        self.assertIn("if (BYAGENT) body.querySelectorAll('.card').forEach(c => { c.draggable = false; });", HTML)

    def test_the_by_agent_init_relabels_the_button_title_and_key_help(self):
        init = HTML[HTML.index("if (BYAGENT) {\n  document.body.classList.add('byagent');"):]
        init = init[:init.index("\n}\n")]
        for needle in ("$('later-btn').firstChild.nodeValue", "$('later').setAttribute('aria-label'", ".p-head strong').textContent", "$('key-later')"):
            self.assertIn(needle, init)
        self.assertIn('<button class="btn" id="later-btn" aria-controls="later">Later <span id="later-n"></span></button>', HTML)   # the board keeps Later

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
