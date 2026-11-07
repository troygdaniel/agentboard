"""lookup reads a report through one descriptor (sec2-lookup-report-toctou, Nov 7): the check that it is a regular file and the read are the
same open (O_NOFOLLOW, then fstat), so a report swapped for a symlink between a check and a read is never followed, and a FIFO never
blocks. Fake board, fake files."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agentboard import lookup, reports
from agentboard.store import Store


class NoFollowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / ".agentboard"
        self.s = Store(self.dir)
        self.s.dir.mkdir(parents=True, exist_ok=True)
        t = self.s.add("report card", "about the zeppelin", status="todo")
        self.s.move(t["id"], "doing")
        self.s.update(t["id"], 100, "done with the zeppelin")
        self.s.move(t["id"], "done")
        self.card = t["id"]
        reports.write_report(self.s, self.card)
        self.rdir = reports.reports_dir(self.dir)
        self.secret = Path(self.tmp.name) / "secret.txt"
        self.secret.write_text("the pelican password is swordfish\n")

    def test_a_symlink_is_not_followed_even_when_the_check_is_lied_to(self):
        link = self.rdir / f"{self.card}.md"   # an extras file that is really a link to a secret
        link.symlink_to(self.secret)
        with mock.patch.object(Path, "is_symlink", return_value=False), mock.patch.object(Path, "is_file", return_value=True):   # the swap won the race
            self.assertEqual(lookup._report_text(link), "")
            self.assertEqual(lookup._file_date(link), "")
            hits, _ = lookup.lookup(self.s, "pelican swordfish", only="reports")
        self.assertEqual(hits, [])

    def test_a_fifo_named_like_an_extras_file_does_not_block(self):
        os.mkfifo(self.rdir / f"{self.card}.md")
        out = {}

        def go():
            out["hits"], _ = lookup.lookup(self.s, "zeppelin", only="reports")

        th = threading.Thread(target=go, daemon=True)
        th.start()
        th.join(3)
        self.assertFalse(th.is_alive(), "lookup blocked on the FIFO")
        self.assertTrue(out["hits"])   # the real report still answers

    def test_a_regular_report_and_extras_file_still_read_with_a_date(self):
        extras = self.rdir / f"{self.card}.md"
        extras.write_text("Extra notes: the harbour crane was the blocker.\n")
        self.assertIn("harbour crane", lookup._report_text(extras))
        self.assertRegex(lookup._file_date(extras), r"^\d{4}-\d{2}-\d{2}$")
        hits, _ = lookup.lookup(self.s, "harbour crane", only="reports")
        self.assertEqual(hits[0]["where"], f"{self.card} ({extras.name})")

    def test_a_missing_or_directory_path_reads_as_nothing(self):
        self.assertEqual(lookup._report_text(self.rdir / "nope.md"), "")
        (self.rdir / "dir.md").mkdir()
        self.assertEqual(lookup._report_text(self.rdir / "dir.md"), "")
        self.assertEqual(lookup._file_date(self.rdir / "dir.md"), "")


if __name__ == "__main__":
    unittest.main()
