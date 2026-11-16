"""A config.toml that is not UTF-8 (night sweep, functional lane): an editor that saved "Jos\\u00e9" in Latin-1, or a binary file by mistake.

tomlread.load decoded the bytes itself and let UnicodeDecodeError out, so prompt.load_config (which catches the reader's own TOMLDecodeError and says WHICH file
to fix) never saw it. Every command then printed only "decoding with 'utf-8-sig' codec failed", with no file named and no way to know where to look, and the
HUD and /api/config answered 500 with the same line. A file that is not text is the same kind of fault as a file with a typo: the same message, naming the file."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, prompt, tomlread
from agentboard.store import BoardError, Store

LATIN1 = '[board]\nowner = "José"\n'.encode("latin-1")   # the byte 0xe9 alone is not UTF-8


class TheReader(unittest.TestCase):
    def test_bytes_that_are_not_utf8_are_the_readers_own_error(self):
        with self.assertRaises(tomlread.TOMLDecodeError) as e:
            tomlread.load(io.BytesIO(LATIN1))
        self.assertIn("UTF-8", str(e.exception))

    def test_utf8_with_or_without_a_bom_still_reads(self):
        for raw in ('[board]\nowner = "José"\n'.encode("utf-8"), b"\xef\xbb\xbf" + '[board]\nowner = "José"\n'.encode("utf-8")):
            self.assertEqual(tomlread.load(io.BytesIO(raw))["board"]["owner"], "José")


class TheCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(root / "proj" / ".agentboard")
        self.d = self.s.dir
        self.d.mkdir(parents=True, exist_ok=True)
        os.environ["AGENTBOARD_DIR"] = str(self.d)
        self.s.add("A card", status="todo")
        (self.d / "config.toml").write_bytes(LATIN1)

    def test_load_config_names_the_file_to_fix(self):
        with self.assertRaises(BoardError) as e:
            prompt.load_config(self.d)
        self.assertIn("config.toml", str(e.exception))
        self.assertIn("UTF-8", str(e.exception))
        self.assertIn("fix or delete it", str(e.exception))

    def test_a_command_says_which_file_and_why_instead_of_a_codec_name(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                cli.main(["list"])
            except SystemExit as e:
                if isinstance(e.code, str):
                    out.write(e.code)
        text = out.getvalue()
        self.assertIn("config.toml", text)
        self.assertNotIn("utf-8-sig", text)


if __name__ == "__main__":
    unittest.main()
