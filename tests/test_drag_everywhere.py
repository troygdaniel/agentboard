"""Drag and drop works on every view that shows cards (Nov 4): Board's three columns, By agent's Todo column and agent lanes,
Load's Todo column and Doing pane. One set of handlers, the Board's own feel, sounds and Undo."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class DragEverywhereTests(unittest.TestCase):
    def test_no_view_switches_dragging_off(self):
        self.assertNotIn("draggable = false", HTML)   # the old By agent and Load guards are gone; only Later's backlog cards stay un-draggable (their markup says so)
        self.assertIn("draggable=\"${backlog ? 'false' : 'true'}\"", HTML)

    def test_one_set_of_handlers_on_the_board_and_both_load_panes(self):
        self.assertIn("const DROP_ROOTS = [board, $('h-todo-wrap'), $('h-cards')];", HTML)
        for ev in ("dragstart", "dragend", "dragover", "dragleave", "drop"):
            self.assertEqual(len(re.findall(r"addEventListener\('%s'" % ev, HTML.split("DROP_ROOTS.forEach")[1])), 1, ev)
        self.assertEqual(HTML.count("board.addEventListener('drop'"), 0)   # not a Board-only handler any more

    def test_load_doing_pane_is_a_column_to_drop_on(self):
        self.assertIn('id="h-cards" data-status="doing"', HTML)

    def test_a_lane_is_doing_and_keeps_its_agent(self):
        rule = HTML[HTML.index("function dropRule("):HTML.index("function clearDrop()")]
        self.assertIn("k.startsWith('agent:')", rule)
        self.assertIn("status: 'doing'", rule)
        self.assertIn("t.status === 'doing' && (t.agent || '') !== lane", rule)   # another agent's lane: refused

    def test_a_foreign_lane_shows_no_insertion_line_and_springs_back_with_a_reason(self):
        self.assertIn("if (rule.foreign) { col.classList.add('nodrop'); return; }", HTML)
        self.assertIn("stays with ${t.agent || 'no agent'}: drop it in its own lane, or on Todo", HTML)
        self.assertIn(".col.over.nodrop .cards { outline-color: var(--err); }", HTML)

    def test_a_todo_card_dropped_on_a_lane_says_where_it_landed(self):
        self.assertIn("no agent yet, so under Unassigned", HTML)
        self.assertIn("async function move(id, status, before, note = '') {", HTML)

    def test_the_drop_clears_every_marker_on_every_view(self):
        c = HTML[HTML.index("function clearDrop()"):HTML.index("function beforeCard(")]
        self.assertIn("document.querySelectorAll('.drop')", c)
        self.assertIn("classList.remove('over', 'nodrop')", c)

    def test_a_drop_still_goes_through_move_for_the_same_undo(self):
        self.assertIn("move(id, rule.status, b?.dataset.id, where);", HTML)
        self.assertIn("toast(`Moved “${t.title}” to ${LABELS[status]}${note}`, { prev: r.prev, before: r.prev_before, kids: r.prev_kids });", HTML)


if __name__ == "__main__":
    unittest.main()
