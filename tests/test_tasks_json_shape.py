"""A tasks.json that is valid JSON of the wrong shape stops with one readable line, not a Python traceback (night sweep, card sweep-func-cli).
`[]`, `null`, `"text"`, `5` or `true` (a hand edit, a bad merge, a sync conflict that left an empty list) made `list`, `rollup` and `watchdog` die with
"AttributeError: 'list' object has no attribute 'setdefault'"; text that is not JSON at all already said so and named the recovery. The same recovery hint now
follows the wrong shape, for the cards (`tasks`) and for the chat (`chat`)."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import BoardError, Store


class Shape(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Seed", status="todo", task_id="seed")

    def put(self, text):
        self.s.path.write_text(text)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def test_a_file_that_is_not_an_object_is_refused_with_the_recovery_hint(self):
        for text in ("[]", "null", '"text"', "5", "true", "[1, 2]"):
            self.put(text)
            with self.assertRaises(BoardError, msg=text) as e:
                self.s.load()
            self.assertIn(str(self.s.path), str(e.exception))
            self.assertIn("not a board", str(e.exception))

    def test_the_commands_say_so_in_one_line_and_never_traceback(self):
        for text in ("[]", "null"):
            self.put(text)
            for argv in (("list",), ("rollup",), ("watchdog",), ("add", "x"), ("night", "status")):
                code, _, err = self.run_cli(*argv)
                self.assertNotEqual(code, 0, (text, argv))
                self.assertIn("not a board", err)
                self.assertNotIn("Traceback", err)

    def test_a_chat_that_is_not_a_list_is_refused_too(self):
        self.put(json.dumps({"tasks": [], "chat": "x"}))
        with self.assertRaises(BoardError) as e:
            self.s.load()
        self.assertIn("chat", str(e.exception))

    def test_a_good_file_and_a_missing_file_are_as_before(self):
        self.assertEqual([t["id"] for t in self.s.load()], ["seed"])
        self.s.path.unlink()
        self.assertEqual(self.s.load(), [])


if __name__ == "__main__":
    unittest.main()
