"""hooks install writes the full path of agentboard (a bare name is looked up on PATH every time, from a file usually committed with the
project); hooks uninstall removes only that hook; the old bare entry is upgraded in place."""
import json
import os
import shlex
import sys
import unittest
from unittest import mock

from agentboard import hooks

from test_mirror import Base

OLD = {"matcher": "SendMessage", "hooks": [{"type": "command", "command": "agentboard hook send-message"}]}
OTHER = {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo hi"}]}


class HookInstall(Base):
    def settings(self):
        return self.proj / ".claude" / "settings.json"

    def read(self):
        return json.loads(self.settings().read_text())

    def test_the_command_is_the_full_path_quoted_for_a_shell(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/my tools/agentboard"):
            hooks.install(self.proj)
        cmd = self.read()["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(cmd, "'/opt/my tools/agentboard' hook send-message")
        self.assertEqual(shlex.split(cmd), ["/opt/my tools/agentboard", "hook", "send-message"])
        self.assertTrue(hooks.installed(self.proj))
        self.assertEqual(hooks.installed_command(self.proj), cmd)

    def test_off_path_it_falls_back_to_this_python_as_a_module_still_a_full_path(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value=None):
            hooks.install(self.proj)
        argv = shlex.split(self.read()["hooks"]["PostToolUse"][0]["hooks"][0]["command"])
        self.assertEqual(argv, [sys.executable, "-m", "agentboard", "hook", "send-message"])
        self.assertTrue(os.path.isabs(argv[0]))

    def test_an_old_bare_entry_is_upgraded_once_and_everything_else_stays(self):
        self.settings().parent.mkdir(parents=True)
        self.settings().write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PostToolUse": [OTHER, OLD]}}))
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            _p, changed = hooks.install(self.proj)
            self.assertTrue(changed)
            before = self.read()
            _p, changed = hooks.install(self.proj)
            self.assertFalse(changed)
        d = self.read()
        self.assertEqual(d, before)
        self.assertEqual(d["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(d["hooks"]["PostToolUse"][0], OTHER)
        self.assertEqual(d["hooks"]["PostToolUse"][1]["hooks"][0]["command"], "/opt/ab/agentboard hook send-message")
        self.assertEqual(len(d["hooks"]["PostToolUse"]), 2)

    def test_a_hook_someone_else_wrote_for_send_message_is_left_alone(self):
        mine = {"matcher": "SendMessage", "hooks": [{"type": "command", "command": "/usr/local/bin/audit-log"}]}
        self.settings().parent.mkdir(parents=True)
        self.settings().write_text(json.dumps({"hooks": {"PostToolUse": [mine]}}))
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj)
            hooks.uninstall(self.proj)
        self.assertEqual(self.read(), {"hooks": {"PostToolUse": [mine]}})


class HookUninstall(Base):
    def setUp(self):
        super().setUp()
        self.p = self.proj / ".claude" / "settings.json"

    def test_uninstall_removes_only_our_hook_and_what_it_emptied(self):
        self.p.parent.mkdir(parents=True)
        self.p.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PostToolUse": [OTHER, OLD], "Stop": [OTHER]}}))
        _p, changed = hooks.uninstall(self.proj)
        self.assertTrue(changed)
        self.assertEqual(json.loads(self.p.read_text()), {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PostToolUse": [OTHER], "Stop": [OTHER]}})
        self.assertFalse(hooks.installed(self.proj))
        self.assertFalse(hooks.uninstall(self.proj)[1])   # twice: nothing to do

    def test_a_file_that_held_only_our_hook_is_removed_and_no_file_is_made_when_there_was_none(self):
        hooks.install(self.proj)
        self.assertTrue(self.p.exists())
        hooks.uninstall(self.proj)
        self.assertFalse(self.p.exists())
        other = self.root / "elsewhere"
        self.assertEqual(hooks.uninstall(other)[1], False)
        self.assertFalse((other / ".claude").exists())

    def test_a_broken_settings_file_is_reported_not_overwritten(self):
        self.p.parent.mkdir(parents=True)
        self.p.write_text("{not json")
        with self.assertRaises(hooks.BoardError):
            hooks.uninstall(self.proj)
        self.assertEqual(self.p.read_text(), "{not json")


class HookCli(Base):
    def test_install_says_what_it_wrote_and_what_the_hook_copies_and_uninstall_undoes_it(self):
        _code, out = self.run_cli("hooks", "install")
        self.assertIn("command:", out)
        self.assertIn("do not send secrets in SendMessage", out)
        self.assertIn("installed", self.run_cli("hooks", "status")[1])
        _code, out = self.run_cli("hooks", "uninstall")
        self.assertIn("removed from", out)
        self.assertIn("not installed", self.run_cli("hooks", "status")[1])
        self.assertIn("not installed in", self.run_cli("hooks", "uninstall")[1])


if __name__ == "__main__":
    unittest.main()
