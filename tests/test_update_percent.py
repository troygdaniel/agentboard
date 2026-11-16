"""`update ID 12.5`, `update ID 50%` and `update ID 1e1` set no percent: the token was taken as the status line and the command said "ID: 0%" as if all was well
(night sweep, card sweep-func-cli). A number-shaped token that is not a whole number is refused now, so an agent that meant a percent finds out; words, a
version and "3 of 5" still go through as a status line, and a whole number is a percent as before."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class UpdatePercent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Card", status="doing", task_id="card")
        self.s.claim("card", "AG-1")
        self.s.update("card", 40, "starting point")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir), "AGENTBOARD_NAME": "AG-1"}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(["update", "card", *argv])
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def card(self):
        return Store.get(self.s.load(), "card")

    def test_a_number_that_is_not_a_whole_number_is_refused_and_nothing_changes(self):
        for token in ("12.5", "50%", "1e1", ".5", "99.9", "+3.0", "-0.5", "7 %"):
            code, _, err = self.run_cli(token)
            self.assertNotEqual(code, 0, token)
            self.assertIn("whole number from 0 to 100", err)
        t = self.card()
        self.assertEqual((t["progress"], t["status_text"]), (40, "starting point"))

    def test_a_decimal_with_words_after_it_was_already_refused(self):
        code, _, err = self.run_cli("12.5", "halfway")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.card()["progress"], 40)

    def test_whole_numbers_and_words_still_work(self):
        self.assertEqual(self.run_cli("55")[0], 0)
        self.assertEqual(self.card()["progress"], 55)
        self.assertEqual(self.run_cli("  60")[0], 0)
        self.assertEqual(self.card()["progress"], 60)
        for words in ("half done", "v2", "3 of 5 steps", "step 2.1 passes", "waiting on CI"):
            self.assertEqual(self.run_cli(words)[0], 0, words)
            t = self.card()
            self.assertEqual((t["progress"], t["status_text"]), (60, words))
        self.assertEqual(self.run_cli("70", "going well")[0], 0)
        self.assertEqual((self.card()["progress"], self.card()["status_text"]), (70, "going well"))


if __name__ == "__main__":
    unittest.main()
