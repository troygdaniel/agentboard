"""`agentboard list` puts each subtask under its parent in one pass over the cards, not one pass per card (sweep-perf: 5,000 cards took 0.54 s,
of which 0.44 s was this ordering, a scan of every card for every card). The test counts lookups instead of timing them, so a busy Mac cannot flake it."""
import unittest

from agentboard import cli


class Counting(dict):
    gets = 0

    def get(self, key, default=None):
        Counting.gets += 1
        return super().get(key, default)


def reference(tasks):
    """The old ordering, kept here as the statement of what the order is: board order, each subtask right under its parent."""
    ids = {t["id"] for t in tasks}
    for t in tasks:
        if t.get("parent_id") in ids:
            continue
        yield t
        yield from (k for k in tasks if k.get("parent_id") == t["id"])


def card(cid, parent=None):
    c = Counting(id=cid, title=cid, status="done")
    if parent:
        c["parent_id"] = parent
    return c


class TreeOrder(unittest.TestCase):
    def test_same_order_as_before(self):
        tasks = [card("a"), card("a1", "a"), card("b"), card("c1", "c"), card("a2", "a"), card("c"), card("orphan", "gone"), card("b1", "b"), card("deep", "a1")]
        self.assertEqual([t["id"] for t in cli._tree_order(tasks)], [t["id"] for t in reference(tasks)])
        self.assertEqual([t["id"] for t in cli._tree_order(tasks)], ["a", "a1", "a2", "b", "b1", "c", "c1", "orphan"])

    def test_an_empty_board(self):
        self.assertEqual(list(cli._tree_order([])), [])

    def test_the_work_grows_with_the_cards_not_with_their_square(self):
        tasks = []
        for i in range(400):
            tasks.append(card(f"p{i}"))
            tasks += [card(f"p{i}-{j}", f"p{i}") for j in range(4)]   # 2,000 cards
        Counting.gets = 0
        out = list(cli._tree_order(tasks))
        self.assertEqual(len(out), 2000)
        self.assertLess(Counting.gets, 10 * len(tasks), f"{Counting.gets} lookups for {len(tasks)} cards: it scans every card for every card")


if __name__ == "__main__":
    unittest.main()
