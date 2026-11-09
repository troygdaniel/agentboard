"""AGENTBOARD_LOCKDOWN is checked first in every path that starts a program or sends board data off the machine.
Each test turns the lock on and makes subprocess and urllib fail the test if they are reached: refusing is not enough, nothing may start."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agentboard import agentchat, cli, lockdown, prompt as promptlib, providers, runs, voice
from agentboard.store import BoardError, Store


def boom(*a, **k):
    raise AssertionError("a program was started or a socket opened while the machine is locked down")


class Locked(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dir = self.root / ".agentboard"
        self.s = Store(self.dir)
        self.s.add("A card", status="todo", task_id="a")
        os.environ[lockdown.ENV] = "1"
        self.addCleanup(os.environ.pop, lockdown.ENV, None)
        for target in ("subprocess.run", "subprocess.Popen", "urllib.request.urlopen"):
            p = mock.patch(target, side_effect=boom)
            p.start()
            self.addCleanup(p.stop)

    def unlocked(self):
        return mock.patch.dict(os.environ, {lockdown.ENV: "0"})


class ChatRounds(Locked):
    def test_both_claude_calls_refuse_before_starting_claude(self):
        with self.assertRaises(BoardError) as cm:
            agentchat.casual_line("claude", "haiku", 1.0, {"sender": "AGENT-1", "text": "x" * 40})
        self.assertIn("AGENTBOARD_LOCKDOWN", str(cm.exception))
        with self.assertRaises(BoardError):
            agentchat._ask_model("claude", "haiku", 1.0, "a prompt")


class OneShotRuns(Locked):
    def test_run_and_detach_refuse(self):
        with self.assertRaises(BoardError):
            runs.run_card(self.s, "a")
        with self.assertRaises(BoardError):
            runs.detach([], self.dir, "a")
        self.assertEqual(Store.get(self.s.load(), "a")["status"], "todo")   # nothing was claimed on the way


class Providers(Locked):
    def test_command_and_http_providers_refuse(self):
        task = {"title": "t"}
        with self.assertRaises(providers.ProviderError) as cm:
            providers.run_provider("c", "x", {"type": "command", "run": "echo hi"}, task, self.dir)
        self.assertIn("locked", str(cm.exception))
        with self.assertRaises(providers.ProviderError):
            providers.run_provider("h", "x", {"type": "http", "url": "http://localhost:5001/{query}"}, task, self.dir)

    def test_a_prompt_with_a_command_provider_still_builds_and_says_why(self):
        (self.dir / "config.toml").write_text('[providers.c]\ntype = "command"\nrun = "echo SHOULD-NOT-APPEAR"\n')
        task = Store.get(self.s.load(), "a")
        task["ctx"] = ["c:x"]
        text, warnings = promptlib.build_prompt(task, self.dir)
        self.assertNotIn("SHOULD-NOT-APPEAR", text)
        self.assertTrue(any("locked" in w for w in warnings), warnings)

    def test_local_file_providers_are_not_affected(self):
        notes = self.root / "n.md"
        notes.write_text("# Hello\nbody\n")
        out = providers.run_provider("m", "", {"type": "markdown", "path": str(notes)}, {"title": "t"}, self.dir)
        self.assertIn("body", out)


class BackupCopy(Locked):
    def test_the_synced_folder_copy_does_not_happen_but_local_snapshots_do(self):
        sync = self.root / "iCloud" / "agentboard-backups"
        (self.dir / "config.toml").write_text(f'[backup]\nsync_dir = "{sync}"\n')
        b = self.s.backups
        self.assertIsNone(b.sync_dir())
        self.assertIsNone(b.sync(datetime(2026, 11, 26, 3, 0), force=True))
        self.assertFalse(sync.exists())
        self.assertEqual(len(b.snapshots()), 1)   # the board's own hourly snapshot inside .agentboard is untouched
        with self.unlocked():
            self.assertEqual(b.sync_dir(), sync)


class Voice(Locked):
    def test_no_microphone_tools_or_paste_keystroke(self):
        st = voice.status(self.dir)
        self.assertFalse(st["ready"])
        self.assertIn("locked", st["error"])
        for fn in (voice.tools, voice.paste_into_front_window, lambda: voice.record(self.root / "x.wav")):
            with self.assertRaises(BoardError):
                fn()


class Spawn(Locked):
    def test_spawn_refuses(self):
        err = io.StringIO()   # the CLI may print its error on either stream: read both
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
            with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.dir)}):
                try:
                    cli.main(["spawn", "atlas,scribe"])
                    code = 0
                except SystemExit as e:   # the CLI exits with its error text as the exit value
                    code = e.code if isinstance(e.code, int) else 1
                    err.write(str(e.code))
        self.assertNotEqual(code, 0)
        self.assertIn("locked", err.getvalue())


class HelpListing(Locked):
    """The command list of a locked-down machine does not advertise the microphone command (work-ready-ux): it is refused there anyway."""

    def help_text(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cli.main(["--help"])
            except SystemExit:
                pass
        return out.getvalue()

    def test_locked_help_has_no_mic_line(self):
        text = self.help_text()
        self.assertNotIn("records the mic", text)
        self.assertNotIn("whisper", text)
        self.assertNotIn("SUPPRESS", text)   # argparse prints a literal ==SUPPRESS== for a hidden subcommand before Python 3.13
        self.assertIsNone(re.search(r"^ {4}dictate\b", text, re.M))   # no row for it in the command list
        self.assertIsNotNone(re.search(r"^ {4}spawn\b", text, re.M))   # the other rows are still listed

    def test_unlocked_help_still_lists_dictate(self):
        with self.unlocked():
            text = self.help_text()
        self.assertIn("records the mic", text)
        self.assertIsNotNone(re.search(r"^ {4}dictate\b", text, re.M))

    def test_the_hidden_command_still_says_it_is_locked(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
            with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.dir)}):
                try:
                    cli.main(["dictate", "--file", str(self.root / "x.wav")])
                except SystemExit as e:
                    err.write(str(e.code))
        self.assertIn("locked", err.getvalue())


class NotLockedNothingChanges(unittest.TestCase):
    def test_with_the_lock_off_the_command_provider_still_runs(self):
        with mock.patch.dict(os.environ, {lockdown.ENV: ""}):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            out = providers.run_provider("c", "x", {"type": "command", "run": "echo hi {arg}"}, {"title": "t"}, Path(tmp.name) / ".agentboard")
        self.assertEqual(out, "hi x")


if __name__ == "__main__":
    unittest.main()
