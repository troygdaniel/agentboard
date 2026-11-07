"""Private by default (sec-data-file-modes): every file the board makes is yours alone, whatever your umask, and what an earlier version
left readable is tightened. The real command line runs in a subprocess under a normal umask 022, because umask is per process."""
import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agentboard import private, server
from agentboard.store import Store

SRC = str(Path(__file__).resolve().parents[1] / "src")


def mode(p):
    return stat.S_IMODE(Path(p).lstat().st_mode)


class Session:
    """A throwaway project folder, a throwaway HOME, and a shell that runs agentboard commands under umask 022."""

    def __init__(self, extra_env=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / "project"
        self.work.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_") and k != "PYTHONPATH"}
        self.env.update({"HOME": str(self.home), "PYTHONPATH": SRC, **(extra_env or {})})
        self.board = self.work / ".agentboard"

    def run(self, *cmds, umask="022"):
        script = f"umask {umask}; " + "; ".join(f"{sys.executable} -m agentboard {c} >/dev/null 2>&1" for c in cmds)
        subprocess.run(["sh", "-c", script], cwd=self.work, env=self.env, check=True, timeout=120)

    def close(self):
        self.tmp.cleanup()

    def everything(self):
        out = []
        for dp, dns, fns in os.walk(self.board):
            out += [Path(dp) / n for n in dns + fns]
        return out


class EverythingTheBoardMakesIsPrivate(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.addCleanup(self.s.close)

    def a_whole_day(self):
        self.s.run("init", "add 'A card' -d 'private words' --status todo --id a-card", "claim a-card --name AGENT-1",
                   "add 'step' --parent a-card", "update step 50 working", "ask a-card 'a question?'",
                   "review a-card 'a result' --body 'a body with private words'", "chat send 'hello' --name AGENT-1", "backup")

    def test_every_file_is_0600_and_every_folder_0700_under_a_normal_umask(self):
        self.a_whole_day()
        names = {p.relative_to(self.s.board).as_posix() for p in self.s.everything()}
        self.assertTrue({"tasks.json", "config.toml", "backups", "reports"} <= names, names)   # the day really made the interesting files
        self.assertTrue(any(n.startswith("reports/") and n.endswith(".html") for n in names), names)
        for p in self.s.everything() + [self.s.board]:
            want = 0o700 if p.is_dir() else 0o600
            self.assertEqual(mode(p), want, f"{p.relative_to(self.s.work)} is {oct(mode(p))}, want {oct(want)}")

    def test_the_project_files_the_board_touches_keep_your_umask(self):
        self.s.run("init", "summary --html out.html")
        self.assertEqual(mode(self.s.work / ".gitignore"), 0o644)     # the project's own file, not board data
        self.assertEqual(mode(self.s.work / "out.html"), 0o644)       # a page you asked for, to open or share
        self.assertEqual(mode(self.s.board), 0o700)

    def test_a_program_the_board_starts_gets_your_umask_back(self):
        self.s.run("init")
        (self.s.board / "config.toml").write_text('[providers.t]\ntype = "command"\nrun = "touch made-by-provider.txt"\n')
        self.s.run("add 'Use it' --status todo --id use-it --ctx t", "prompt use-it")
        self.assertEqual(mode(self.s.work / "made-by-provider.txt"), 0o644)   # what a provider command writes in your project
        self.assertEqual(mode(self.s.board / "tasks.json"), 0o600)             # while the board's own files stay private

    def test_an_explicit_umask_turns_it_off_for_a_shared_folder(self):
        s2 = Session({"AGENTBOARD_UMASK": "022"})
        self.addCleanup(s2.close)
        s2.run("init", "add 'A card' --status todo --id a-card")
        self.assertEqual(mode(s2.board / "config.toml"), 0o644)
        with mock.patch.dict(os.environ, {"AGENTBOARD_UMASK": "022"}):
            self.assertEqual(private.tighten_dir(s2.board), 0)   # and the server's start-up pass leaves it alone
        self.assertEqual(mode(s2.board / "config.toml"), 0o644)

    def test_a_looser_umask_cannot_loosen_it(self):
        self.s.run("init", "add 'A card' --status todo --id a-card", umask="000")
        for p in self.s.everything() + [self.s.board]:
            self.assertEqual(mode(p), 0o700 if p.is_dir() else 0o600, p.name)


class TighteningWhatIsAlreadyThere(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dir = self.root / ".agentboard"
        for d in ("reports", "runs/card/run1", "backups"):
            (self.dir / d).mkdir(parents=True)
        self.files = [self.dir / n for n in ("config.toml", "sessions.json", "chat-cursors.json", "reports/a-20260101-000000.html",
                                              "runs/card/run1/stdout.json", "runs/card/run1/prompt.md", ".lock")]
        for f in self.files:
            f.write_text("x")
            os.chmod(f, 0o644)
        for d in [self.dir, *[p for p in self.dir.rglob("*") if p.is_dir()]]:
            os.chmod(d, 0o755)

    def test_loose_files_and_folders_are_tightened_and_a_second_pass_changes_nothing(self):
        n = private.tighten_dir(self.dir)
        self.assertGreaterEqual(n, len(self.files) + 4)
        for p in [self.dir, *self.dir.rglob("*")]:
            self.assertEqual(mode(p), 0o700 if p.is_dir() else 0o600, p.name)
        self.assertEqual(private.tighten_dir(self.dir), 0)

    def test_a_symlink_is_left_alone_and_never_followed_out_of_the_folder(self):
        outside = self.root / "outside.txt"
        outside.write_text("not ours")
        os.chmod(outside, 0o644)
        os.symlink(outside, self.dir / "link.txt")
        os.symlink(self.root, self.dir / "linkdir")
        private.tighten_dir(self.dir)
        self.assertEqual(mode(outside), 0o644)

    def test_an_executable_bit_survives_but_group_and_other_do_not(self):
        f = self.dir / "tool.sh"
        f.write_text("#!/bin/sh\n")
        os.chmod(f, 0o755)
        private.tighten_dir(self.dir)
        self.assertEqual(mode(f), 0o700)

    def test_a_missing_folder_is_not_an_error(self):
        self.assertEqual(private.tighten_dir(self.root / "nope"), 0)

    def test_serve_tightens_at_start(self):
        store = Store(self.dir)
        fake = mock.MagicMock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(server, "ThreadingHTTPServer", return_value=fake), mock.patch.object(server.threading, "Thread"), \
                contextlib.redirect_stdout(io.StringIO()):
            server.serve(store, 8199, open_browser=False)
        self.assertEqual(mode(self.dir / "config.toml"), 0o600)
        self.assertEqual(mode(self.dir / "reports"), 0o700)


class TheBackupSyncCopy(unittest.TestCase):
    def test_the_copy_in_the_cloud_folder_is_private_too(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        s = Store(root / ".agentboard")
        s.add("A", status="todo")
        sync = root / "iCloud" / "backups"
        (root / ".agentboard" / "config.toml").write_text(f'[backup]\nsync_dir = "{sync}"\n')
        old = os.umask(0o077)           # what the command line and the server run under
        self.addCleanup(os.umask, old)
        s.backups.tick()
        dest = s.backups.sync(datetime(2026, 11, 7, 3, 0), force=True)
        self.assertEqual(mode(dest), 0o600)
        self.assertEqual(mode(sync), 0o700)


class TheHelpers(unittest.TestCase):
    def test_original_umask_is_remembered_and_children_get_it(self):
        with mock.patch.dict(os.environ, {private.ORIG_ENV: "027"}):
            self.assertEqual(private.original_umask(), 0o027)
            self.assertEqual(private.child(), {"umask": 0o027} if os.name == "posix" else {})

    def test_without_a_remembered_one_it_is_the_current_umask(self):
        env = {k: v for k, v in os.environ.items() if k != private.ORIG_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            old = os.umask(0o022)
            self.addCleanup(os.umask, old)
            self.assertEqual(private.original_umask(), 0o022)

    def test_as_user_restores_the_private_umask_afterwards(self):
        with mock.patch.dict(os.environ, {private.ORIG_ENV: "022"}):
            old = os.umask(0o077)
            self.addCleanup(os.umask, old)
            with private.as_user():
                cur = os.umask(0o022)
                self.assertEqual(cur, 0o022)
            self.assertEqual(os.umask(0o077), 0o077)


if __name__ == "__main__":
    unittest.main()
