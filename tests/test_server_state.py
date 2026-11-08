"""server-<pid>.json: what a running server was started with, so agentboard doctor does not answer "is the lock on?" from its own shell
alone. Unit tests for the file, doctor's cross-check with fake ps/lsof, and one real server started in a subprocess."""
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import agentboard
from agentboard import doctor, lockdown, serverstate

from tests.test_doctor import FakeRunner


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.board = self.root / "proj" / ".agentboard"
        self.board.mkdir(parents=True)


class TheFile(Base):
    def test_it_holds_yes_or_no_answers_and_plugin_names_and_nothing_else(self):
        os.environ["AGENTBOARD_LOCKDOWN"] = "1"
        os.environ["AGENTBOARD_PRIVATE_THING"] = "must-not-appear-in-the-file"
        serverstate.write(self.board, 8765, ["home"])
        p = serverstate.path_for(self.board, os.getpid())
        d = json.loads(p.read_text())
        self.assertEqual(set(d), {"pid", "port", "started", "lockdown", "plugins_open", "plugins_loaded", "profile"})
        self.assertEqual((d["pid"], d["port"], d["lockdown"], d["plugins_loaded"]), (os.getpid(), 8765, True, ["home"]))
        self.assertNotIn("must-not-appear", p.read_text())
        self.assertNotIn(str(self.root), p.read_text())
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_the_lock_and_the_plugin_gate_are_recorded_as_they_are(self):
        serverstate.write(self.board, 1, [])
        d = serverstate.read(self.board, os.getpid())
        self.assertEqual((d["lockdown"], d["plugins_open"]), (False, False))
        os.environ["AGENTBOARD_PLUGINS"] = "1"
        serverstate.write(self.board, 1, ["home"])
        self.assertTrue(serverstate.read(self.board, os.getpid())["plugins_open"])
        os.environ["AGENTBOARD_LOCKDOWN"] = "1"
        serverstate.write(self.board, 1, [])
        d = serverstate.read(self.board, os.getpid())
        self.assertEqual((d["lockdown"], d["plugins_open"]), (True, False))   # a lock closes the plugin gate

    def test_remove_deletes_only_its_own_file_and_a_dead_servers_file_is_forgotten(self):
        gone = serverstate.path_for(self.board, 2_000_000_000)             # no such process
        gone.write_text(json.dumps({"pid": 2_000_000_000, "lockdown": False, "plugins_open": False}))
        other = serverstate.path_for(self.board, os.getppid())             # a live process that is not us
        other.write_text(json.dumps({"pid": os.getppid(), "lockdown": True, "plugins_open": False}))
        serverstate.write(self.board, 1, [])
        self.assertFalse(gone.exists())
        self.assertTrue(other.exists())
        serverstate.remove(self.board)
        self.assertFalse(serverstate.path_for(self.board, os.getpid()).exists())
        self.assertTrue(other.exists())

    def test_a_planted_link_in_the_way_is_not_written_through(self):
        target = self.root / "victim.txt"
        target.write_text("keep me")
        tmp = serverstate.path_for(self.board, os.getpid()).with_name(f"server-{os.getpid()}.json.tmp")
        tmp.symlink_to(target)
        serverstate.write(self.board, 1, [])
        self.assertEqual(target.read_text(), "keep me")
        self.assertTrue(serverstate.read(self.board, os.getpid()))

    def test_read_checks_every_field_and_never_raises(self):
        pid = 4242
        path = serverstate.path_for(self.board, pid)
        for bad in ("not json", "[]", json.dumps({"pid": pid + 1, "lockdown": True, "plugins_open": False}),
                    json.dumps({"pid": pid, "lockdown": "yes", "plugins_open": False}), json.dumps({"pid": pid, "lockdown": True}),
                    json.dumps({"pid": pid, "lockdown": True, "plugins_open": False, "junk": "x" * 10000})):
            path.write_text(bad)
            self.assertIsNone(serverstate.read(self.board, pid), bad[:40])
        path.write_text(json.dumps({"pid": pid, "lockdown": True, "plugins_open": True, "plugins_loaded": ["home", "Bad Name", 7, "x" * 99], "port": True, "started": 5}))
        d = serverstate.read(self.board, pid)
        self.assertEqual((d["plugins_loaded"], d["port"], d["started"]), (["home"], None, ""))
        path.unlink()
        path.symlink_to(self.root)
        self.assertIsNone(serverstate.read(self.board, pid))
        self.assertIsNone(serverstate.read(self.board, 999))


class DoctorCrossCheck(Base):
    def put(self, pid, lockdown_on, plugins_open=False, loaded=()):
        serverstate.path_for(self.board, pid).write_text(json.dumps(
            {"pid": pid, "port": 8765, "started": "2026-11-07T09:00:00", "lockdown": lockdown_on, "plugins_open": plugins_open, "plugins_loaded": list(loaded)}))

    def check(self, shell_locked, pids=("123",)):
        return doctor.check_servers(self.board, list(pids), shell_locked)

    def test_no_server_running_adds_nothing_and_keeps_the_shell_answer(self):
        self.assertEqual(self.check(True, pids=()), ([], True))
        self.assertEqual(self.check(False, pids=()), ([], False))

    def test_a_locked_server_with_the_gate_closed_is_a_pass(self):
        self.put(123, True)
        lines, locked = self.check(True)
        self.assertEqual([r[0] for r in lines], [doctor.PASS])
        self.assertTrue(locked)

    def test_a_server_started_without_the_lock_beats_a_locked_shell(self):
        self.put(123, False)
        lines, locked = self.check(True)
        self.assertEqual(lines[0][0], doctor.WARN)
        self.assertIn("WITHOUT AGENTBOARD_LOCKDOWN although this shell has it on", lines[0][2])
        self.assertFalse(locked)                                            # the shell alone no longer decides

    def test_an_unlocked_server_in_an_unlocked_shell_is_information(self):
        self.put(123, False)
        lines, locked = self.check(False)
        self.assertEqual(lines[0][0], doctor.INFO)
        self.assertFalse(locked)

    def test_plugins_on_in_the_server_is_a_warning_even_when_locked_shell_says_otherwise(self):
        self.put(123, False, plugins_open=True, loaded=["home"])
        lines, _ = self.check(False)
        self.assertEqual(lines[0][0], doctor.WARN)
        self.assertIn("plugins ON (home)", lines[0][2])

    def test_a_file_whose_pid_is_not_a_running_server_or_is_unreadable_is_not_trusted(self):
        self.put(777, True)                                                 # a file, but pid 777 is not among the running servers
        lines, locked = self.check(True, pids=("123",))
        self.assertEqual(lines[0][0], doctor.INFO)
        self.assertIn("none recorded how it was started", lines[0][2])
        self.assertTrue(locked)                                             # nothing known about the server: the shell answer stands, and the INFO says so
        serverstate.path_for(self.board, 123).write_text("{broken")
        self.assertEqual(self.check(True)[0][0][0], doctor.INFO)

    def test_two_servers_are_each_checked_and_one_unlocked_makes_the_answer_unlocked(self):
        self.put(123, True)
        self.put(124, False)
        lines, locked = self.check(True, pids=("123", "124"))
        self.assertEqual(sorted(r[0] for r in lines), [doctor.PASS, doctor.WARN])
        self.assertFalse(locked)

    def test_the_config_line_uses_the_servers_answer_not_only_the_shells(self):
        (self.board / "config.toml").write_text('[chat]\ncasual = true\n')
        self.put(123, False)
        runner = FakeRunner("  123 /x/agentboard serve --no-open\n", listen=["127.0.0.1:8765"])
        with mock.patch("importlib.metadata.entry_points", return_value=[]), mock.patch.object(Path, "home", return_value=self.root / "home"):
            rs = doctor.run(self.board, env={"AGENTBOARD_LOCKDOWN": "1"}, runner=runner)
        cfg = next(r for r in rs if r[1] == "config")
        self.assertEqual(cfg[0], doctor.WARN)                                # the shell has the lock, the server does not: no PASS
        self.put(123, True)
        with mock.patch("importlib.metadata.entry_points", return_value=[]), mock.patch.object(Path, "home", return_value=self.root / "home"):
            rs = doctor.run(self.board, env={"AGENTBOARD_LOCKDOWN": "1"}, runner=runner)
        self.assertEqual(next(r for r in rs if r[1] == "config")[0], doctor.PASS)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RealServer(Base):
    def start(self, **env):
        self.port = free_port()
        e = {**os.environ, "PYTHONPATH": str(Path(agentboard.__file__).resolve().parents[1]), "AGENTBOARD_DIR": str(self.board),
             "AGENTBOARD_HOME": str(self.root / "home"), "PYTHONDONTWRITEBYTECODE": "1", **env}
        proc = subprocess.Popen([sys.executable, "-m", "agentboard", "serve", "--no-open", "--port", str(self.port)], env=e,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.time() + 15
        while time.time() < deadline and not serverstate.read(self.board, proc.pid):
            time.sleep(0.1)
        return proc

    def test_a_real_server_records_its_lock_and_removes_the_file_when_it_exits(self):
        proc = self.start(AGENTBOARD_LOCKDOWN="1")
        d = serverstate.read(self.board, proc.pid)
        self.assertIsNotNone(d, "the server wrote no state file")
        self.assertEqual((d["lockdown"], d["plugins_open"], d["port"]), (True, False, self.port))
        # the real doctor, real ps: this shell has no lock, the server does
        lines, locked = doctor.check_servers(self.board, doctor._board_pids(subprocess.run) or [], False)
        self.assertIn(doctor.PASS, [r[0] for r in lines])
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=15)
        self.assertFalse(serverstate.path_for(self.board, proc.pid).exists())

    def test_a_server_without_the_lock_says_so(self):
        proc = self.start()
        self.assertFalse(serverstate.read(self.board, proc.pid)["lockdown"])
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=15)


if __name__ == "__main__":
    unittest.main()
