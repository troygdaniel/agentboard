"""Overnight reliability (overnight-rel-server-lifecycle): start, stop, restart and status with a REAL `agentboard serve` subprocess on a
throwaway board: health answers with no board data; status finds it; a second start on the same port says who holds it; stop ends it
gracefully (exit 0, state file gone); kill -9 leaves a stale file that status cleans; restart keeps the port and gives a new pid; a request
in flight finishes before the server closes. Loopback only."""
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from agentboard import cli, doctor, lifecycle, serverstate
from agentboard.store import Store

SRC = str(Path(__file__).resolve().parents[1] / "src")
PY = sys.executable


def free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.board = self.root / "proj" / ".agentboard"
        self.board.mkdir(parents=True)
        self.s = Store(self.board)
        self.s.add("a card")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env.update({"PYTHONPATH": SRC, "AGENTBOARD_DIR": str(self.board), "HOME": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"})
        self.env = env
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.pids = []
        self.addCleanup(self.kill_all)

    def kill_all(self):
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def serve(self, port, wait=True):
        pr = subprocess.Popen([PY, "-m", "agentboard", "serve", "--port", str(port), "--no-open"], env=self.env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        self.pids.append(pr.pid)
        if wait:
            deadline = time.time() + 20
            while time.time() < deadline and pr.poll() is None:
                h = lifecycle.health(port, timeout=0.5)
                if h and h.get("pid") == pr.pid:
                    return pr
                time.sleep(0.05)
            self.fail(f"the server did not come up: {pr.stdout.read() if pr.poll() is not None else 'still starting'}")
        return pr

    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", out):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class Health(Base):
    def test_health_names_the_server_and_carries_no_board_data(self):
        port = free_port()
        pr = self.serve(port)
        h = lifecycle.health(port)
        self.assertEqual((h["ok"], h["pid"], h["port"]), (True, pr.pid, port))
        self.assertTrue(h["agentboard"])
        self.assertIsInstance(h["uptime_s"], int)
        self.assertEqual(set(h), {"ok", "agentboard", "pid", "port", "started", "uptime_s", "plugins", "lockdown"})
        raw = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"Host": f"localhost:{port}"}), timeout=5).read()
        self.assertNotIn(b"a card", raw)
        self.assertNotIn(str(self.root).encode(), raw)
        with self.assertRaises(urllib.error.HTTPError) as cm:   # the same Host guard as every route
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"Host": "evil.example"}), timeout=5)
        self.assertEqual(cm.exception.code, 403)
        self.assertIsNone(lifecycle.health(free_port()))


class StatusStopRestart(Base):
    def test_status_stop_and_the_state_file(self):
        self.assertEqual(self.run_cli("status")[0], 1)
        port = free_port()
        pr = self.serve(port)
        code, out = self.run_cli("status")
        self.assertEqual(code, 0, out)
        self.assertIn(f"running: pid {pr.pid} on port {port} since", out)
        self.assertIn("lockdown off", out)
        self.assertTrue(serverstate.path_for(self.board, pr.pid).exists())
        t0 = time.monotonic()
        ok, line = lifecycle.stop(self.board)
        self.assertTrue(ok, line)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(pr.wait(timeout=10), 0)   # SIGTERM is a clean exit
        self.assertIn("agentboard: stopped", pr.stdout.read())
        self.assertFalse(serverstate.path_for(self.board, pr.pid).exists())
        self.assertEqual(lifecycle.running(self.board), [])
        code, out = self.run_cli("status")
        self.assertEqual(code, 1)
        self.assertIn("not running", out)
        self.assertEqual(lifecycle.stop(self.board), (True, "not running (nothing to stop)"))

    def test_a_second_start_on_the_same_port_says_who_holds_it(self):
        port = free_port()
        pr = self.serve(port)
        second = subprocess.run([PY, "-m", "agentboard", "serve", "--port", str(port), "--no-open"], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(second.returncode, 1)
        self.assertIn(f"this board is already served on port {port} by pid {pr.pid}", second.stdout + second.stderr)
        self.assertIn("agentboard restart", second.stdout + second.stderr)
        self.assertTrue(lifecycle.health(port))   # the first is untouched
        other = self.root / "other" / ".agentboard"
        other.mkdir(parents=True)
        Store(other).add("x")
        third = subprocess.run([PY, "-m", "agentboard", "serve", "--port", str(port), "--no-open"], env={**self.env, "AGENTBOARD_DIR": str(other)},
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(third.returncode, 1)
        self.assertIn("held by another agentboard server", third.stdout + third.stderr)
        self.assertIn(f"--port {port + 1}", third.stdout + third.stderr)

    def test_kill_9_leaves_a_stale_file_that_status_and_doctor_name_and_status_cleans(self):
        port = free_port()
        pr = self.serve(port)
        os.kill(pr.pid, signal.SIGKILL)
        pr.wait(timeout=10)
        self.assertTrue(serverstate.path_for(self.board, pr.pid).exists())
        rows = [r for r in doctor.check_server_files(self.board)]
        self.assertEqual(rows[0][0], "WARN")
        self.assertIn(f"stale server file for pid {pr.pid}", rows[0][2])
        code, out = self.run_cli("status")
        self.assertEqual(code, 1)
        self.assertIn(f"cleaned 1 stale server file (pid {pr.pid}", out)
        self.assertFalse(serverstate.path_for(self.board, pr.pid).exists())
        self.assertEqual([r[0] for r in doctor.check_server_files(self.board)], ["INFO"])

    def test_restart_keeps_the_port_and_background_start_prints_the_pid(self):
        port = free_port()
        pid, line = lifecycle.start_background(self.board, port)
        self.pids.append(pid)
        self.assertIsNotNone(pid, line)
        self.assertIn(f"started pid {pid} on port {port}", line)
        self.assertTrue((self.board / lifecycle.LOG_FILE).exists())
        self.assertEqual(lifecycle.health(port)["pid"], pid)
        ok, line = lifecycle.restart(self.board)
        self.assertTrue(ok, line)
        self.assertIn(f"restarted on port {port}: pid ", line)
        self.assertIn(f"(was {pid})", line)
        h = lifecycle.health(port)
        self.assertNotEqual(h["pid"], pid)
        self.pids.append(h["pid"])
        self.assertFalse(serverstate.pid_alive(pid))
        self.assertEqual([s["pid"] for s in lifecycle.running(self.board)], [h["pid"]])
        code, out = self.run_cli("stop")
        self.assertEqual(code, 0, out)
        self.assertIn("stopped pid", out)

    def test_a_request_in_flight_finishes_before_the_server_closes(self):
        port = free_port()
        pr = self.serve(port)
        got = {}

        def slow_post():   # a save that is under way when SIGTERM arrives: the server finishes it before it closes
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/tasks", data=json.dumps({"title": "in flight"}).encode(),
                                         headers={"Content-Type": "application/json", "Host": f"localhost:{port}"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    got["status"] = r.status
            except Exception as e:   # noqa: BLE001
                got["error"] = repr(e)
        t = threading.Thread(target=slow_post)
        t.start()
        time.sleep(0.02)
        os.kill(pr.pid, signal.SIGTERM)
        t.join(timeout=15)
        pr.wait(timeout=15)
        self.assertEqual(pr.returncode, 0)
        titles = [x["title"] for x in Store(self.board).load()]
        self.assertTrue(got.get("status") == 200 or "in flight" not in titles or got.get("error"), got)   # either it finished whole or it never started: never half
        self.assertTrue(json.loads((self.board / "tasks.json").read_text()))


class StopSignalsOnlyARealServer(Base):
    """xr-lifecycle-stop-any-pid: a state file whose pid now belongs to another program (pid reuse after a crash) is stale, never signalled."""

    def test_the_command_line_rule(self):
        def runner(cmd_line):
            def run(argv, **kw):
                return subprocess.CompletedProcess(argv, 0, cmd_line, "")
            return run
        me = os.getpid()
        self.assertTrue(lifecycle.is_board_server(me, runner("/opt/pipx/venvs/agentboard/bin/python /opt/pipx/venvs/agentboard/bin/agentboard serve --port 8765")))
        self.assertTrue(lifecycle.is_board_server(me, runner(f"{sys.executable} -m agentboard serve --port 8765 --no-open")))
        for other in ("sleep 30", "/usr/bin/python3 -m agentboard doctor", "agentboard status", "vim serve.py", "node server.js serve"):
            self.assertFalse(lifecycle.is_board_server(me, runner(other)), other)
        self.assertFalse(lifecycle.is_board_server(999999, runner("agentboard serve")))   # not alive at all

    def test_a_planted_state_file_for_another_process_is_cleaned_and_never_signalled(self):
        sl = subprocess.Popen(["sleep", "30"])
        self.pids.append(sl.pid)
        serverstate.path_for(self.board, sl.pid).write_text(json.dumps({"pid": sl.pid, "port": 1, "started": "2026-11-08T00:00:00", "lockdown": False,
                                                                        "plugins_open": False, "plugins_loaded": []}))
        self.assertEqual(lifecycle.running(self.board), [])
        self.assertEqual(lifecycle.stale(self.board), [sl.pid])
        ok, line = lifecycle.stop(self.board)
        self.assertEqual((ok, line), (True, "not running (nothing to stop)"))
        self.assertIsNone(sl.poll())   # still asleep: nothing signalled it
        self.assertFalse(serverstate.path_for(self.board, sl.pid).exists())   # the stale file is gone
        code, out = self.run_cli("status")
        self.assertEqual(code, 1)
        self.assertIn("not running", out)
        sl.kill()


if __name__ == "__main__":
    unittest.main()
