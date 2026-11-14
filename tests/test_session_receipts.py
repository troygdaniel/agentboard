"""A handled line is not delivered again (card talk-it-through-bugs). The two-step receipts of cursors.py (chat-f3) print a line as DELIVERED and count it SEEN
when the session next does something on the board as that name; a delivery nothing confirmed in RESHOW_S (5 minutes) is shown again by the next `chat inbox`.
That second half assumed a session that has not confirmed in 5 minutes never read the line. A busy session breaks it: ORCH was shown a line, acted on it
(merged a branch, ran a test suite, ten minutes of commands that carry no --name), then restarted its listener, and `chat inbox` printed the line again with
"printed to you 10 min ago and never confirmed: shown again". Time is the wrong witness. The right one is the session itself: a delivery records which session
it went to (AGENTBOARD_SESSION, else the first ancestor process of the command that is not a shell: the agent runtime, or the terminal's login), and that session running any board
command, or its next `chat inbox`, is proof it read what it was shown, however long ago. A different session taking over the name, or one we cannot tell,
still gets the old 5-minute rule. A throwaway board; nothing reaches a real one."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import cli, cursors, lifecycle
from agentboard.store import Store

ME, SOMEONE_ELSE = "pid:4111", "pid:4222"


class Base(unittest.TestCase):
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
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.s.add("seed")
        self.who = ME
        sid = mock.patch.object(lifecycle, "session_id", create=True, side_effect=lambda: self.who)   # which session is running the command (a test says)
        sid.start()
        self.addCleanup(sid.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def backdate(self, name, minutes):
        """The delivery to `name` happened `minutes` ago (the file as the board wrote it, only its time moved)."""
        f = Path(self.s.dir) / cursors.DELIVERED
        d = json.loads(f.read_text())
        d[name.lower()]["at"] = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
        f.write_text(json.dumps(d))

    def line_to(self, name, text):
        return self.s.chat_send(self.s.owner, text, kind="user", to=name)


class ABusySessionIsNotShownTheLineAgain(Base):
    def test_ten_minutes_of_unnamed_commands_then_the_next_inbox_does_not_repeat_the_line(self):
        q = self.line_to("R2", "please merge the branch")
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertIn("please merge the branch", out)
        self.backdate("R2", 10)                                              # the session worked for ten minutes
        self.run_cli("list")                                                 # commands with no --name and no AGENTBOARD_NAME: nothing named it
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertNotIn("never confirmed", out)
        self.assertNotIn("please merge the branch", out)
        self.assertIn("nothing new", out)
        self.assertEqual(cursors.get(self.s.dir, "R2"), q["seq"])

    def test_restarting_the_listener_alone_after_a_long_job_is_enough(self):
        q = self.line_to("R2", "run the suite")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.backdate("R2", 12)                                              # no command at all in between: the restart is the proof
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertNotIn("never confirmed", out)
        self.assertNotIn("run the suite", out)
        self.assertEqual(cursors.get(self.s.dir, "R2"), q["seq"])

    def test_a_board_command_from_that_session_confirms_without_any_name(self):
        q = self.line_to("R2", "look at this")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.assertEqual(cursors.pending(self.s.dir, "R2")["seq"], q["seq"])
        self.run_cli("list")                                                 # any board command by the session that was shown it
        self.assertIsNone(cursors.pending(self.s.dir, "R2"))
        self.assertEqual(cursors.get(self.s.dir, "R2"), q["seq"])

    def test_a_new_line_after_the_long_job_still_comes(self):
        self.line_to("R2", "first")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.backdate("R2", 10)
        self.line_to("R2", "second")
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertIn("second", out)
        self.assertNotIn("first", out)


class AReaderThatIsGoneStillGetsTheLineAgain(Base):
    """What chat-f3 is for (loss path 5): the session that was shown the line is gone, or never read it."""

    def test_a_different_session_taking_over_the_name_after_five_minutes_is_shown_it_again(self):
        self.line_to("R2", "did you get this?")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.backdate("R2", 6)
        self.who = SOMEONE_ELSE                                              # the first session is gone; another one starts listening as R2
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertIn("never confirmed: shown again", out)
        self.assertIn("did you get this", out)

    def test_another_session_running_a_command_does_not_confirm_for_this_one(self):
        q = self.line_to("R2", "yours")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.who = SOMEONE_ELSE
        self.run_cli("list")
        self.assertEqual(cursors.pending(self.s.dir, "R2")["seq"], q["seq"])

    def test_a_session_we_cannot_tell_keeps_the_old_rule(self):
        self.line_to("R2", "who are you?")
        self.who = None
        self.run_cli("chat", "inbox", "--name", "R2")
        self.backdate("R2", 6)
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertIn("never confirmed: shown again", out)
        q2 = self.line_to("R2", "and this?")
        self.backdate("R2", 1)                                                # inside the window it is confirmed, as before
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertNotIn("never confirmed", out)

    def test_within_five_minutes_the_next_inbox_confirms_as_before(self):
        q = self.line_to("R2", "quick")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.who = SOMEONE_ELSE
        self.backdate("R2", 2)
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertNotIn("never confirmed", out)
        self.assertEqual(cursors.get(self.s.dir, "R2"), q["seq"])


class TheSessionKey(unittest.TestCase):
    """lifecycle.session_id(): AGENTBOARD_SESSION, else the first ancestor process that is not a shell, from a table of (pid -> parent, command)."""

    def chain(self, table, start=900, env=None):
        clean = {k: v for k, v in os.environ.items() if k != "AGENTBOARD_SESSION"}
        clean.update(env or {})
        with mock.patch.object(lifecycle, "_ps", side_effect=lambda pid: table.get(pid)), mock.patch("os.getppid", return_value=start), mock.patch.dict(os.environ, clean, clear=True):
            lifecycle._SESSION[0] = "unset"
            try:
                return lifecycle.session_id()
            finally:
                lifecycle._SESSION[0] = "unset"

    def test_it_is_the_agent_runtime_not_the_shell_that_runs_the_command(self):
        # agentboard (this process) < zsh -c (pid 900) < claude (pid 800) < -zsh (700) < login (600) < Terminal (500): a pid maps to (its parent, its command)
        table = {900: (800, "/bin/zsh"), 800: (700, "claude"), 700: (600, "-zsh"), 600: (500, "login"), 500: (1, "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal")}
        self.assertEqual(self.chain(table), "pid:800")

    def test_a_terminal_tab_is_its_login_process(self):
        table = {900: (700, "-zsh"), 700: (600, "login"), 600: (500, "Terminal")}
        self.assertEqual(self.chain(table), "pid:700")                         # the login process: one per terminal tab

    def test_wrappers_are_skipped_like_shells(self):
        table = {900: (880, "env"), 880: (870, "timeout"), 870: (860, "/bin/bash"), 860: (800, "claude")}
        self.assertEqual(self.chain(table), "pid:860")

    def test_a_session_may_name_itself_and_that_wins(self):
        table = {900: (800, "zsh"), 800: (1, "claude")}
        self.assertEqual(self.chain(table, env={"AGENTBOARD_SESSION": "orch-main"}), "orch-main")
        self.assertEqual(self.chain({}, env={"AGENTBOARD_SESSION": "  x  "}), "x")           # even where no process can be looked up

    def test_nothing_known_is_none_and_never_an_error(self):
        self.assertIsNone(self.chain({}))
        self.assertIsNone(self.chain({900: (1, "zsh")}))                      # only shells up to init

    def test_a_refused_program_start_is_just_an_unknown_session(self):
        with mock.patch.object(lifecycle.subprocess, "run", side_effect=RuntimeError("program starts are refused here")), mock.patch("os.getppid", return_value=900):
            with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AGENTBOARD_SESSION"}, clear=True):
                lifecycle._SESSION[0] = "unset"
                try:
                    self.assertIsNone(lifecycle.session_id())
                finally:
                    lifecycle._SESSION[0] = "unset"

    def test_it_is_worked_out_once_per_process(self):
        calls = []
        table = {900: (800, "zsh"), 800: (1, "claude")}
        with mock.patch.object(lifecycle, "_ps", side_effect=lambda pid: calls.append(pid) or table.get(pid)), mock.patch("os.getppid", return_value=900), \
                mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AGENTBOARD_SESSION"}, clear=True):
            lifecycle._SESSION[0] = "unset"
            try:
                a, n = lifecycle.session_id(), len(calls)
                b = lifecycle.session_id()
                self.assertEqual((a, b, len(calls)), ("pid:800", "pid:800", n))
            finally:
                lifecycle._SESSION[0] = "unset"


if __name__ == "__main__":
    unittest.main()
