"""A new card never takes the id of an archived one (night sweep, functional lane).

A card's id is a slug of its title, made unique among the cards on the board, and the archive was left out. Titles repeat all the time (a subtask called "Run the
tests" under every card), so a new card got the id of an archived one. When it was cleared in turn, the archive kept ONE card for that id, the newest: the first
card's history, report and what it learned were replaced without a word. And `unarchive` of the old id could not put it back while a live card held the id: it
dropped it from the archive instead."""
import json
import tempfile
import unittest
from pathlib import Path

from agentboard.store import BoardError, Store


class TheArchiveIsPartOfTheNamespace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")

    def finish_and_clear(self, tid):
        self.s.move(tid, "done")
        self.s.clear_done()

    def test_a_second_card_with_the_same_title_gets_a_new_id_and_both_stay_in_the_archive(self):
        first = self.s.add("Run the tests", description="FIRST card", status="todo")
        self.finish_and_clear(first["id"])
        second = self.s.add("Run the tests", description="SECOND card", status="todo")
        self.assertNotEqual(second["id"], first["id"])
        self.finish_and_clear(second["id"])
        kept = {t["id"]: t["description"] for t in self.s.load_archived()}
        self.assertEqual(kept, {first["id"]: "FIRST card", second["id"]: "SECOND card"})   # one card per id used to be all that was left

    def test_the_old_card_can_still_be_brought_back_beside_the_new_one(self):
        first = self.s.add("Run the tests", description="FIRST card", status="todo")
        self.finish_and_clear(first["id"])
        second = self.s.add("Run the tests", description="SECOND card", status="todo")
        self.s.unarchive([first["id"]])
        live = {t["id"]: t["description"] for t in self.s.load()}
        self.assertEqual(len(live), 2)   # two cards, two ids (the old one used to be dropped from the archive and never come back)
        self.assertEqual(live, {first["id"]: "FIRST card", second["id"]: "SECOND card"})
        self.assertEqual(self.s.load_archived(), [])

    def test_a_subtask_does_not_take_an_archived_subtasks_id_either(self):
        a = self.s.add("Card A", status="todo")
        step = self.s.add("Write tests", parent_id=a["id"])
        self.s.move(a["id"], "done")
        self.s.clear_done()
        b = self.s.add("Card B", status="todo")
        step2 = self.s.add("Write tests", parent_id=b["id"])
        self.assertNotEqual(step2["id"], step["id"])
        ids = [t["id"] for t in self.s.load_all()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_id_given_by_hand_cannot_be_an_archived_id_either(self):
        first = self.s.add("Run the tests", status="todo")
        self.finish_and_clear(first["id"])
        with self.assertRaises(BoardError) as e:
            self.s.add("Another", task_id=first["id"])
        self.assertIn("already exists", str(e.exception))

    def test_a_damaged_archive_does_not_stop_a_new_card(self):
        self.s.add("Seed", status="todo")
        self.s.archive_path.write_text("{not json")
        t = self.s.add("A new card", status="todo")   # the live board keeps working, as it did; the archive's own readers say what is wrong
        self.assertEqual(t["title"], "A new card")
        self.assertIn(t["id"], [x["id"] for x in json.loads(self.s.path.read_text())["tasks"]])


if __name__ == "__main__":
    unittest.main()
