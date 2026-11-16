"""Cards flagged archived but still inside tasks.json leave it on the next save (night sweep, performance finding).

An older version archived a card by flagging it inside tasks.json; the archive file came later, and only Clear done or Archive moved a flagged card out. A board
with thousands of those (the live one has about 3,100 of 5,000) pays the whole file on every command, every poll and every write: 52 ms to load and 96 ms to
update at 7 MB, against 2.6 ms and 8.9 ms at 0.4 MB. Now any save that changes the board moves them into archive.json first, in the same order the explicit
clear uses (the archive is written first, so a failed save leaves a card in both files, which load_all counts once). Reads never write."""
import json
import tempfile
import unittest
from pathlib import Path

from agentboard.store import Store


class FlaggedCardsLeave(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        for i in range(6):
            self.s.add(f"Card {i}", status="todo", task_id=f"c{i}")
        for i in (0, 1, 2):
            self.s.move(f"c{i}", "done")

    def flag(self, *ids):
        """What an old version left: the card flagged archived inside tasks.json."""
        d = json.loads(self.s.path.read_text())
        for t in d["tasks"]:
            if t["id"] in ids:
                t["archived"] = True
        self.s.path.write_text(json.dumps(d))

    def live_ids(self):
        return [t["id"] for t in json.loads(self.s.path.read_text())["tasks"]]

    def archive_ids(self):
        return sorted(t["id"] for t in self.s.load_archived())

    def test_a_write_moves_the_flagged_cards_into_the_archive_and_load_all_still_sees_every_card(self):
        self.flag("c0", "c1", "c2")
        all_before = sorted(t["id"] for t in self.s.load_all())
        self.s.claim("c4", "Pat-1")   # any save
        self.assertEqual(sorted(self.live_ids()), ["c3", "c4", "c5"])
        self.assertEqual(self.archive_ids(), ["c0", "c1", "c2"])
        self.assertEqual(sorted(t["id"] for t in self.s.load_all()), all_before)

    def test_reading_the_board_writes_nothing(self):
        self.flag("c0", "c1")
        before = self.s.path.read_text()
        self.s.load()
        self.s.load_all()
        self.assertEqual(self.s.path.read_text(), before)
        self.assertEqual(self.archive_ids(), [])

    def test_a_flagged_subtask_of_an_open_parent_keeps_its_slot(self):
        p = self.s.add("Parent", status="todo", task_id="parent")
        self.s.add("Step", parent_id="parent", task_id="step")
        self.s.claim("parent", "Pat-1")
        self.s.update("step", 100, "done")   # the step finishes while the parent stays open
        self.flag("step")
        self.s.claim("c4", "Pat-1")
        self.assertIn("step", self.live_ids())   # as before: the parent's bar keeps its slot
        self.assertNotIn("step", self.archive_ids())

    def test_bringing_one_card_back_while_others_wait_to_move_loses_neither(self):
        self.flag("c0")
        self.s.claim("c4", "Pat-1")   # c0 moves out
        self.flag("c1")               # an old file again: another flagged card
        self.s.unarchive(["c0"])      # a save that rewrites the archive itself: c1 waits for the next save, and nothing is lost
        self.assertIn("c0", self.live_ids())
        ids = [t["id"] for t in self.s.load_all()]
        self.assertEqual((len(ids), len(set(ids))), (6, 6))
        self.s.claim("c5", "Pat-1")   # the next save moves it
        self.assertNotIn("c1", self.live_ids())
        self.assertEqual(self.archive_ids(), ["c1"])
        ids = [t["id"] for t in self.s.load_all()]
        self.assertEqual((len(ids), len(set(ids))), (6, 6))

    def test_a_damaged_archive_stops_the_move_not_the_save(self):
        self.flag("c0")
        self.s.archive_path.write_text("{not json")
        self.s.claim("c4", "Pat-1")   # saved
        self.assertIn("c0", self.live_ids())   # still flagged where it was: nothing was lost
        self.assertEqual(next(t for t in self.s.load() if t["id"] == "c4")["agent"], "Pat-1")

    def test_a_board_with_nothing_flagged_does_not_touch_the_archive_file(self):
        self.s.claim("c4", "Pat-1")
        self.assertFalse(self.s.archive_path.exists())


if __name__ == "__main__":
    unittest.main()
