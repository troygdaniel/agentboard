"""The Todo column: one design, one function, on the Board and on By agent (Nov 2). Narrow, no 'Unassigned', Copy prompt in the foot row."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class TodoColumnTests(unittest.TestCase):
    def test_one_function_draws_the_column_for_both_views(self):
        self.assertEqual(HTML.count("function todoColHtml("), 1)
        self.assertIn("return todoColHtml(by.todo, filtered) +", HTML)                       # By agent: Todo, then the agent lanes
        self.assertIn("if (k === 'todo') return todoColHtml(by.todo, q || pf || flagFilter);", HTML)   # the Board
        self.assertEqual(HTML.count('<section class="col todo" data-status="todo">'), 1)     # nowhere else builds it

    def test_both_views_give_todo_the_same_narrow_track(self):
        self.assertIn("--todo-w: clamp(220px, 17vw, 270px)", HTML)
        self.assertIn("k === 'todo' ? 'var(--todo-w)'", HTML)                               # the Board's tracks
        self.assertIn("`var(--todo-w) repeat(${Math.max(1, n)}, minmax(220px, 1fr))`", HTML)   # By agent's tracks

    def test_a_card_is_drawn_once_per_view(self):
        # a card in the Todo column and again as "next up" in an agent lane would share one data-id (focus, FLIP and keys all pick the first)
        self.assertNotIn("nextup", HTML)
        self.assertNotIn("nextBy", HTML)

    def test_the_agent_chip_hides_only_inside_an_agent_lane(self):
        self.assertIn("body.byagent .col.acol .card .who { display: none; }", HTML)
        self.assertNotIn("body.byagent .card .who { display: none; }", HTML)

    def test_the_by_agent_view_has_no_todo_overrides_of_its_own(self):
        self.assertNotIn('body.byagent .card[data-status="todo"]', HTML)
        self.assertNotIn("body.byagent .card .copy", HTML)
        self.assertNotIn("body.byagent .card .qnum", HTML)

    def test_the_stacked_phone_layouts_keep_the_narrow_todo_cards(self):
        self.assertIn(".col.todo .card { max-width: 340px; }", HTML)
        self.assertIn("body.byagent .board .col.todo { flex-basis: min(86%, 300px); }", HTML)

    def test_todo_cards_do_not_say_unassigned_and_copy_prompt_is_in_the_foot_row(self):
        self.assertNotIn(".card[data-status=\"todo\"] .unas", HTML)
        self.assertRegex(HTML, r'<div class="meta">\$\{copy\}\$\{laterBtn\}\$\{toTodoBtn\}\$\{who && !todo \? \'\' : queued\}</div>')
        card = HTML[HTML.index("function card(t) {"):HTML.index("function toggleSubs")]
        self.assertNotRegex(card, r"\n    \$\{copy\}\$\{top\}")                              # no longer floats first in the card over the title
        self.assertLess(card.index("const copy = "), card.index("const meta = "))              # meta reads copy: declare it first (a TDZ error blanks the board)

    def test_an_assigned_todo_card_keeps_its_name_row_free_of_the_time(self):
        self.assertIn("${todo ? '' : when}</div>`", HTML)

    def test_the_empty_top_row_never_takes_space(self):
        self.assertIn(".card .top:empty { display: none; }", HTML)
        self.assertEqual(len(re.findall(r"^\s*body\.byagent \.card \.top:empty", HTML, re.M)), 0)


if __name__ == "__main__":
    unittest.main()
