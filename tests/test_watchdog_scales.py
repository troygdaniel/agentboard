"""watchdog.findings (the HUD's strip of ways the board is stuck) reads the board file once and does not scan every card for each Doing card (sweep-perf:
two parses of the whole file and one scan of all cards per Doing card, 48 ms at 5,000 cards, on every HUD rebuild). The tests count reads and calls instead
of timing them, so a busy Mac cannot flake them; the last one pins what it reports."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import watchdog
from agentboard.store import Store


def board(parents=40, kids=3):
    tmp = tempfile.TemporaryDirectory()
    s = Store(Path(tmp.name) / ".agentboard")
    s.dir.mkdir(parents=True, exist_ok=True)
    for i in range(parents):
        s.add(f"Card {i}", status="todo", task_id=f"c{i}")
        for j in range(kids):
            s.add(f"Step {i}.{j}", parent_id=f"c{i}", task_id=f"c{i}-s{j}")
        s.claim(f"c{i}", "atlas")
    return tmp, s


class Findings(unittest.TestCase):
    def test_one_read_of_the_board_file(self):
        tmp, s = board()
        self.addCleanup(tmp.cleanup)
        reads, real = [], Store._read

        def counting(store, *a, **k):
            reads.append(1)
            return real(store, *a, **k)
        with mock.patch.object(Store, "_read", counting):
            watchdog.findings(s)
        self.assertLessEqual(len(reads), 1, f"{len(reads)} reads of the board file for one set of findings")

    def test_no_scan_of_every_card_for_each_doing_card(self):
        tmp, s = board()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(watchdog, "_kids", side_effect=AssertionError("a scan of every card for one Doing card")):
            watchdog.findings(s)

    def test_a_split_card_is_still_found(self):
        tmp, s = board(parents=3)
        self.addCleanup(tmp.cleanup)
        with s.transaction() as tasks:
            for t in tasks:
                if t["id"] == "c1-s0":
                    t["agent"] = "orion"
                if t["id"] == "c1-s1":
                    t["agent"] = "vega"
                if t["id"] == "c1-s2":
                    t["agent"] = "atlas"     # the holder's own subtask is not "another agent"
                if t["id"] == "c2-s0":
                    t["agent"] = "orion"
                    t["status"] = "done"     # a finished subtask of another agent is not an open one
        split = [f for f in watchdog.findings(s) if f["kind"] == "split-card"]
        self.assertEqual([f["id"] for f in split], ["c1"])
        self.assertIn("orion, vega hold open subtasks of it", split[0]["what"])
        self.assertEqual(split[0]["fix"]["action"], "hand")


if __name__ == "__main__":
    unittest.main()
