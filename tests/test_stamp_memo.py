"""A board stamp is parsed once, then remembered (sweep-perf: one HUD build at 5,000 cards called parse_stamp 100,000 times, 76 ms of a 220 ms build, for
the same few thousand stamps every time). The datetimes are immutable, so the same object can be handed out. The test checks identity and bounds,
not milliseconds, so a busy Mac cannot flake it."""
import unittest
from datetime import datetime
from unittest import mock

from agentboard import store
from agentboard.store import parse_stamp


class StampMemo(unittest.TestCase):
    def test_the_same_stamp_gives_the_same_object(self):
        a = parse_stamp("2026-11-15T20:41:09")
        self.assertEqual(a, datetime(2026, 11, 15, 20, 41, 9))
        self.assertIs(parse_stamp("2026-11-15T20:41:09"), a)
        self.assertIs(parse_stamp("2026-11-15T20:41:09 trailing words"), a)   # only the first 19 characters count, as before

    def test_what_is_not_a_stamp_is_none_and_stays_none(self):
        for bad in (None, "", "yesterday", "2026-13-45T99:99:99", 42, ["2026-11-15T20:41:09x"]):
            self.assertIsNone(parse_stamp(bad), bad)
            self.assertIsNone(parse_stamp(bad), bad)

    def test_a_stamp_in_the_old_strptime_shape_still_parses(self):
        self.assertEqual(parse_stamp("2026-1-5T7:08:09"), datetime(2026, 1, 5, 7, 8, 9))

    def test_the_memo_is_bounded(self):
        store._STAMPS.clear()
        with mock.patch.object(store, "STAMPS_MAX", 50):
            for i in range(120):
                self.assertEqual(parse_stamp(f"2026-11-15T10:{i // 60:02d}:{i % 60:02d}"), datetime(2026, 11, 15, 10, i // 60, i % 60))
            self.assertLessEqual(len(store._STAMPS), 50)
        store._STAMPS.clear()


if __name__ == "__main__":
    unittest.main()
