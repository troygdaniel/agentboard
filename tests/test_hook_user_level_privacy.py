"""The chat security review of chat-f6 (Nov 8). MEDIUM: with the hooks in ~/.claude/settings.json every Claude Code session on the Mac runs the
SendMessage mirror, so a session the board never heard of (another project, an employer's code) must post nothing; only a session that told the
board its name (AGENTBOARD_NAME, or `agentboard me`) is mirrored. LOW: install and uninstall write the settings file through a temp file in its
folder, keep the mode and a .bak, and rewrite a symlink's target rather than the link. HOME points at a temp folder throughout."""
import json
import os
import stat
import unittest
from unittest import mock

from agentboard import hooks

from test_mirror import PAYLOAD, Base


class OnlyKnownSessionsAreMirrored(Base):
    def setUp(self):
        super().setUp()
        self.home = self.root / "home"
        self.home.mkdir(exist_ok=True)
        os.environ["HOME"] = str(self.home)

    def test_an_unrelated_sessions_send_message_never_reaches_the_board(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.home, self.s.dir)   # the user-level hook: every session on the Mac runs it
        private = dict(PAYLOAD, session_id="9f3a1c2d-unrelated", tool_input={"to": "worker", "message": "PRIVATE: notes from an unrelated project"})
        self.assertIsNone(hooks.mirror_send_message(self.s, private))
        hooks.run_hook(self.s, stdin=_Stdin(json.dumps(private)))
        self.assertEqual([m for m in self.s.chat_list() if "PRIVATE" in m.get("text", "")], [])
        self.assertNotIn("PRIVATE", (self.s.dir / "tasks.json").read_text())

    def test_a_session_that_said_its_name_is_mirrored_the_owner_is_not(self):
        payload = dict(PAYLOAD, session_id="abc-known", tool_input={"to": "AGENT-2", "message": "on it"})
        self.assertIsNone(hooks.mirror_send_message(self.s, payload))
        hooks.remember_session(self.s.dir, "AGENT-4", session_id="abc-known")   # agentboard me --name AGENT-4
        m = hooks.mirror_send_message(self.s, payload)
        self.assertEqual((m["sender"], m["via"]), ("AGENT-4", "mirror"))
        os.environ["AGENTBOARD_NAME"] = self.s.owner   # the owner's own session: never mirrored as an agent
        self.assertIsNone(hooks.mirror_send_message(self.s, dict(payload, session_id="owner-session")))
        os.environ["AGENTBOARD_NAME"] = "AGENT-7"
        self.assertEqual(hooks.mirror_send_message(self.s, dict(payload, session_id="other"))["sender"], "AGENT-7")


class _Stdin:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text


class TheSettingsFileIsWrittenSafely(Base):
    def setUp(self):
        super().setUp()
        self.p = self.proj / ".claude" / "settings.json"
        self.p.parent.mkdir(parents=True)

    def test_mode_is_kept_a_bak_holds_the_original_and_nothing_else_is_left(self):
        self.p.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
        os.chmod(self.p, 0o644)
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj, self.s.dir)
        self.assertEqual(stat.S_IMODE(self.p.stat().st_mode), 0o644)
        self.assertEqual(json.loads((self.p.parent / "settings.json.bak").read_text()), {"permissions": {"allow": ["Bash(ls)"]}})
        d = json.loads(self.p.read_text())
        self.assertEqual(d["permissions"], {"allow": ["Bash(ls)"]})
        self.assertIn("Stop", d["hooks"])
        self.assertEqual([x.name for x in self.p.parent.iterdir() if x.name.endswith(".tmp")], [])
        orig = self.p.parent / "settings.json.orig"
        self.assertEqual(json.loads(orig.read_text()), {"permissions": {"allow": ["Bash(ls)"]}})   # the pristine file, kept once
        hooks.uninstall(self.proj)
        self.assertEqual(json.loads(self.p.read_text()), {"permissions": {"allow": ["Bash(ls)"]}})
        self.assertIn("Stop", (self.p.parent / "settings.json.bak").read_text())   # the .bak is the version before the last write
        self.assertEqual(json.loads(orig.read_text()), {"permissions": {"allow": ["Bash(ls)"]}})   # the .orig is not
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/other/agentboard"):
            hooks.install(self.proj, self.s.dir)   # a reinstall with a moved agentboard rewrites the commands
        self.assertEqual(json.loads(orig.read_text()), {"permissions": {"allow": ["Bash(ls)"]}})   # still pristine after a second install
        self.assertIn("/opt/other/agentboard", self.p.read_text())

    def test_a_new_file_is_private_and_a_failed_write_leaves_the_old_one_whole(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj, self.s.dir)
        self.assertEqual(stat.S_IMODE(self.p.stat().st_mode), 0o600)
        before = self.p.read_text()
        with mock.patch("agentboard.hooks.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            hooks.write_settings(self.p, "{}")
        self.assertEqual(self.p.read_text(), before)
        self.assertEqual([x.name for x in self.p.parent.iterdir() if x.name.endswith(".tmp")], [])

    def test_a_symlinked_settings_file_stays_a_symlink_and_its_target_is_rewritten(self):
        real = self.root / "dotfiles" / "claude-settings.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"env": {"X": "1"}}))
        self.p.symlink_to(real)
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj, self.s.dir)
        self.assertTrue(self.p.is_symlink())
        d = json.loads(real.read_text())
        self.assertEqual(d["env"], {"X": "1"})
        self.assertIn("Stop", d["hooks"])
        self.assertTrue((real.parent / "claude-settings.json.bak").exists())


if __name__ == "__main__":
    unittest.main()
