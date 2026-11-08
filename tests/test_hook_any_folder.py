"""chat-f6: the Stop hook works from any folder. `hooks install` writes the board folder into the hook command (--dir), `hooks install
--user` puts the hooks in the user's own ~/.claude/settings.json so every session on this Mac has them, and `agentboard doctor` says
where the Stop hook is and whether its board folder exists. R11 of tests/chat_repro.py (a home-folder session with no board in its
environment) now blocks on an unread owner line. HOME points at a temp folder throughout: the real ~/.claude is never touched."""
import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from agentboard import doctor, hooks

from test_mirror import Base

SRC = str(Path(__file__).resolve().parents[1] / "src")


class HomeBase(Base):
    def setUp(self):
        super().setUp()
        self.home = self.root / "home"
        self.home.mkdir(exist_ok=True)
        os.environ["HOME"] = str(self.home)   # Path.home() reads HOME: the user's settings live in the temp folder for every test here
        self.s.add("seed")

    def user_settings(self):
        return self.home / ".claude" / "settings.json"

    def project_settings(self):
        return self.proj / ".claude" / "settings.json"


class TheCommandNamesTheBoard(HomeBase):
    def test_install_writes_the_board_folder_into_both_hooks(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj, self.s.dir)
        d = json.loads(self.project_settings().read_text())
        mirror = d["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        stop = d["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(mirror), ["/opt/ab/agentboard", "hook", "send-message", "--dir", str(self.s.dir.resolve())])
        self.assertEqual(shlex.split(stop), ["/opt/ab/agentboard", "hook", "stop", "--dir", str(self.s.dir.resolve())])
        self.assertEqual(hooks.hook_board(stop), str(self.s.dir.resolve()))
        self.assertTrue(hooks.installed(self.proj, "stop"))
        self.assertEqual(hooks.status(self.proj), "installed")
        _p, changed = hooks.install(self.proj, self.s.dir)
        self.assertFalse(changed)   # idempotent

    def test_a_folder_with_a_space_is_quoted_and_still_recognised(self):
        board = self.root / "my proj" / ".agentboard"
        board.mkdir(parents=True)
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj, board)
        cmd = hooks.installed_command(self.proj, "stop")
        self.assertIn("'", cmd)
        self.assertEqual(hooks.hook_board(cmd), str(board.resolve()))
        self.assertTrue(hooks._ours({"command": cmd}, "stop"))
        _p, changed = hooks.uninstall(self.proj)
        self.assertTrue(changed)
        self.assertFalse(self.project_settings().exists())

    def test_an_entry_without_a_board_folder_or_with_another_is_rewritten(self):
        self.project_settings().parent.mkdir(parents=True)
        other = self.root / "other" / ".agentboard"
        self.project_settings().write_text(json.dumps({"hooks": {
            "PostToolUse": [{"matcher": "SendMessage", "hooks": [{"type": "command", "command": "/opt/ab/agentboard hook send-message"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": f"/opt/ab/agentboard hook stop --dir {other}"}]}]}}))
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            _p, changed = hooks.install(self.proj, self.s.dir)
        self.assertTrue(changed)
        for event in ("send-message", "stop"):
            self.assertEqual(hooks.hook_board(hooks.installed_command(self.proj, event)), str(self.s.dir.resolve()), event)
        self.assertNotIn(str(other), self.project_settings().read_text())

    def test_someone_elses_hook_with_options_is_not_ours(self):
        self.assertFalse(hooks._ours({"command": "/opt/ab/agentboard hook stop --evil x"}, "stop"))
        self.assertFalse(hooks._ours({"command": "/usr/bin/other hook stop --dir /x"}, "stop"))
        self.assertTrue(hooks._ours({"command": f"{sys.executable} -m agentboard hook stop --dir /x"}, "stop"))
        self.assertIsNone(hooks.hook_board("/opt/ab/agentboard hook stop"))


class UserLevelInstall(HomeBase):
    def test_hooks_install_user_writes_the_users_settings_with_the_board_folder(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            code, out = self.run_cli("hooks", "install", "--user")
        self.assertFalse(code, out)   # cli.main returns None on success
        self.assertIn(str(self.user_settings()), out)
        self.assertIn("every session on this Mac", out)
        self.assertIn(f"Both name the board folder ({self.s.dir})", out)
        d = json.loads(self.user_settings().read_text())
        self.assertEqual(hooks.hook_board(d["hooks"]["Stop"][0]["hooks"][0]["command"]), str(self.s.dir.resolve()))
        self.assertFalse(self.project_settings().exists())   # --user: nothing written in the project
        code, out = self.run_cli("hooks", "status", "--project", str(self.home))
        self.assertIn("installed", out)
        code, out = self.run_cli("hooks", "uninstall", "--user")
        self.assertFalse(code, out)
        self.assertFalse(self.user_settings().exists())

    def test_the_project_install_also_names_the_board(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            code, out = self.run_cli("hooks", "install")
        self.assertFalse(code, out)   # cli.main returns None on success
        self.assertIn("so they work from any folder a session starts in.", out)
        self.assertEqual(hooks.hook_board(hooks.installed_command(self.proj, "stop")), str(self.s.dir.resolve()))


class TheHookFromAnyFolder(HomeBase):
    """R11: a session started in an empty folder, no AGENTBOARD_DIR, no board above it. With --dir the Stop hook finds the board and blocks on an
    unread owner line; without it, it prints nothing, as before."""

    def hook(self, *extra, name="R11", env_dir=None):
        empty = self.root / "empty"
        empty.mkdir(exist_ok=True)
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": SRC, "PYTHONDONTWRITEBYTECODE": "1"}
        if env_dir is not None:
            env["AGENTBOARD_DIR"] = env_dir
        if name:
            env["AGENTBOARD_NAME"] = name
        payload = json.dumps({"session_id": "abc", "stop_hook_active": False})
        r = subprocess.run([sys.executable, "-m", "agentboard", "hook", "stop", *extra], env=env, cwd=str(empty), capture_output=True, text=True,
                           input=payload, timeout=60)
        return r.returncode, r.stdout.strip()

    def test_r11_blocks_with_the_baked_in_folder_and_prints_nothing_without_it(self):
        self.s.chat_send(self.s.owner, "unread thread line", kind="user", to="R11")
        code, out = self.hook()
        self.assertEqual((code, out), (0, ""))   # no board in the environment, none above the folder: nothing, as R11 found
        code, out = self.hook("--dir", str(self.s.dir))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["decision"], "block")
        self.assertIn("unread thread line", d["reason"])
        code, out = self.hook("--dir", str(self.s.dir), env_dir="")   # an empty AGENTBOARD_DIR in the environment loses to the baked-in folder
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_the_installed_command_runs_as_written(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value=None):   # the python -m form: the one a test can run as written
            hooks.install(self.home, self.s.dir)
        cmd = hooks.installed_command(self.home, "stop")
        self.s.chat_send(self.s.owner, "please answer", kind="user", to="R11")
        argv = shlex.split(cmd)
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": SRC, "AGENTBOARD_NAME": "R11", "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run(argv, env=env, cwd=str(self.root), capture_output=True, text=True, input=json.dumps({"session_id": "x", "stop_hook_active": False}), timeout=60)
        self.assertEqual(json.loads(r.stdout)["decision"], "block", r.stdout + r.stderr)


class DoctorSaysWhereItIs(HomeBase):
    def line(self):
        rows = [r for r in doctor.check_stop_hook(self.proj)]
        return rows

    def test_not_installed_installed_user_and_project_and_a_missing_board(self):
        rows = self.line()
        self.assertEqual([r[0] for r in rows], ["WARN"])
        self.assertIn("not installed: run agentboard hooks install --user", rows[0][2])
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.home, self.s.dir)
        rows = self.line()
        self.assertEqual([r[0] for r in rows], ["PASS"])
        self.assertIn(f"installed for the board at {self.s.dir.resolve()}", rows[0][2])
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.proj, self.root / "gone" / ".agentboard")
        rows = self.line()
        self.assertEqual([r[0] for r in rows], ["PASS", "WARN"])
        self.assertIn("installed but no board found at", rows[1][2])
        self.project_settings().write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/opt/ab/agentboard hook stop"}]}]}}))
        rows = self.line()
        self.assertIn("installed without a board folder", rows[1][2])
        self.assertEqual(rows[1][0], "WARN")

    def test_the_doctor_report_carries_the_line(self):
        with mock.patch("agentboard.hooks.shutil.which", return_value="/opt/ab/agentboard"):
            hooks.install(self.home, self.s.dir)
        results = doctor.run(self.s.dir, self.proj, runner=lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        mine = [r for r in results if r[1] == "Stop hook"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0][0], "PASS")


if __name__ == "__main__":
    unittest.main()
