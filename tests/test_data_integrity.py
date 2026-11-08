"""Overnight reliability (overnight-rel-data-integrity, Nov 7): the data layer survives crashes, concurrent writers and corrupt files.

- every state file is written atomically and updated under a lock (statefile.py), so two agents at once lose nothing;
- several writer processes and a server at once never lose a card, and a writer killed with SIGKILL mid-save leaves a valid board that
  holds every card it had acknowledged;
- the server killed with SIGKILL while clients post keeps every card it answered 200 for, and starts again on the same folder;
- a corrupt tasks.json is refused with one line that says which copy is good and the command that restores it; a corrupt state file is
  read as empty and named by `agentboard verify`, which also restores the newest snapshot into a scratch folder as a test.
Everything runs on throwaway boards in a temp folder; the only network is 127.0.0.1 for the server soak."""
import contextlib
import io
import json
import os
import random
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

from agentboard import agentchat, backup, cli, listeners, statefile
from agentboard.store import BoardError, Store

SRC = str(Path(__file__).resolve().parents[1] / "src")
PY = sys.executable
WRITER = """
import sys
from agentboard.store import Store
s = Store(sys.argv[1])
n = 0
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 9
while n < limit:
    t = s.add(f"card {sys.argv[2]} {n}")
    print(t["id"], flush=True)
    n += 1
"""
BUMPER = """
import sys
from agentboard import statefile
for _ in range(int(sys.argv[2])):
    statefile.update(sys.argv[1], lambda d: d.__setitem__("n", d.get("n", 0) + 1))
"""


def env_for(board):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
    env.update({"PYTHONPATH": SRC, "AGENTBOARD_DIR": str(board)})
    return env


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        self.board.mkdir()
        self.s = Store(self.board)
        p = mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.board)})
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()


# -- the state files -------------------------------------------------------------------------------------------------------------------------
class TheStateFile(Base):
    def test_a_write_is_atomic_and_a_read_tolerates_what_it_finds(self):
        p = self.board / "chat-cursors.json"
        self.assertEqual(statefile.read(p), ({}, ""))
        statefile.write(p, {"AGENT-1": 7})
        self.assertEqual(json.loads(p.read_text()), {"AGENT-1": 7})
        self.assertEqual([x.name for x in self.board.iterdir() if x.name.endswith(".tmp")], [])   # nothing left beside it
        p.write_text("{not json")
        data, why = statefile.read(p)
        self.assertEqual(data, {})
        self.assertIn("chat-cursors.json is not valid JSON", why)
        self.assertEqual(statefile.load(p, []), [])
        statefile.update(p, lambda d: d.__setitem__("x", 1))   # the next write replaces the broken file
        self.assertEqual(json.loads(p.read_text()), {"x": 1})

    def test_threads_updating_at_once_lose_nothing_and_a_reader_never_sees_half_a_file(self):
        p = self.board / "counts.json"
        bad = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    json.loads(p.read_text())
                except FileNotFoundError:
                    pass
                except ValueError as e:
                    bad.append(str(e))

        def bump():
            for _ in range(40):
                statefile.update(p, lambda d: d.__setitem__("n", d.get("n", 0) + 1))
        r = threading.Thread(target=reader)
        r.start()
        ts = [threading.Thread(target=bump) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        stop.set()
        r.join()
        self.assertEqual(json.loads(p.read_text()), {"n": 320})
        self.assertEqual(bad, [])

    def test_processes_updating_at_once_lose_nothing(self):
        p = self.board / "counts.json"
        procs = [subprocess.Popen([PY, "-c", BUMPER, str(p), "25"], env=env_for(self.board)) for _ in range(4)]
        for pr in procs:
            self.assertEqual(pr.wait(timeout=60), 0)
        self.assertEqual(json.loads(p.read_text()), {"n": 100})

    def test_cursors_and_listeners_go_through_it(self):
        agentchat.write_cursor(self.s, "AGENT-1", 5)
        agentchat.write_cursor(self.s, "AGENT-1", 3)   # never backwards
        agentchat.write_cursor(self.s, "AGENT-2", 9)
        self.assertEqual(json.loads((self.board / "chat-cursors.json").read_text()), {"agent-1": 5, "agent-2": 9})   # cursors.py keeps names lower-cased
        listeners.register(self.board, "AGENT-1", "inbox")
        self.assertIn("AGENT-1", json.loads((self.board / "chat-listeners.json").read_text()))
        (self.board / "chat-listeners.json").write_text("garbage")
        self.assertEqual(listeners.listening(self.board), {})   # read as empty, no crash
        listeners.register(self.board, "AGENT-3", "inbox")
        self.assertEqual(list(json.loads((self.board / "chat-listeners.json").read_text())), ["AGENT-3"])

    def test_stray_temp_files_are_found_reported_and_swept(self):
        old = self.board / ".tasks.json-abc123.tmp"
        fresh = self.board / ".tasks.json-def456.tmp"
        for p in (old, fresh):
            p.write_text("{half")
        then = time.time() - 700
        os.utime(old, (then, then))
        self.assertEqual(statefile.stray_temps(self.board), [old])   # the fresh one may be a write in flight
        self.assertTrue(any("1 leftover temp file" in w and "abc123" in w for w in statefile.problems(self.board)))
        self.s.add("a card")   # the next save sweeps it
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(statefile.problems(self.board), [])


# -- concurrent writers and kill -9 ---------------------------------------------------------------------------------------------------------------
class ConcurrentWriters(Base):
    def test_five_processes_adding_at_once_lose_no_card(self):
        procs = [subprocess.Popen([PY, "-c", WRITER, str(self.board), f"w{i}", "20"], env=env_for(self.board), stdout=subprocess.PIPE, text=True)
                 for i in range(5)]
        ids = []
        for pr in procs:
            out, _ = pr.communicate(timeout=120)
            self.assertEqual(pr.returncode, 0)
            ids += out.split()
        self.assertEqual(len(ids), 100)
        self.assertEqual(len(set(ids)), 100)
        tasks = self.s.load()
        self.assertEqual(sorted(t["id"] for t in tasks), sorted(ids))
        self.assertTrue(backup.verify_file(self.board / "tasks.json")[0])
        self.assertTrue(backup.verify_file(self.board / "tasks.json.bak")[0])

    def test_a_writer_killed_mid_save_leaves_a_valid_board_with_every_card_it_acknowledged(self):
        acked = []
        random.seed(7)
        for n in range(8):
            pr = subprocess.Popen([PY, "-c", WRITER, str(self.board), f"k{n}"], env=env_for(self.board), stdout=subprocess.PIPE, text=True)
            time.sleep(random.uniform(0.15, 0.6))
            os.kill(pr.pid, signal.SIGKILL)
            out, _ = pr.communicate(timeout=30)
            acked += out.split()
        self.assertGreater(len(acked), 8, "the writers should have had time to add a few cards")
        ok, msg, n = backup.verify_file(self.board / "tasks.json")
        self.assertTrue(ok, msg)
        tasks = self.s.load()   # the strict read (every card checked) passes too
        have = {t["id"] for t in tasks}
        self.assertTrue(set(acked) <= have, sorted(set(acked) - have))   # an acknowledged card is never lost
        self.assertEqual(len(have), len(tasks))
        self.assertTrue(backup.verify_file(self.board / "tasks.json.bak")[0])
        # a kill between the temp write and the rename leaves a temp file: ten minutes later the next save removes it
        strays = [p for p in self.board.iterdir() if p.name.endswith(".tmp")]
        for p in strays:
            os.utime(p, (time.time() - 700, time.time() - 700))
        self.s.add("after the storm")
        self.assertEqual([p for p in self.board.iterdir() if p.name.endswith(".tmp")], [])
        code, out, _ = self.run_cli("verify")
        self.assertIn("ok  tasks.json", out)


def free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


class TheServerUnderKillNine(Base):
    """`agentboard serve` killed with SIGKILL while clients post cards: every card it answered 200 for is on the board, and a new server
    starts on the same folder."""

    def start(self, port):
        pr = subprocess.Popen([PY, "-c", "from agentboard.cli import main; main(['serve', '--port', '%d', '--no-open'])" % port],
                              env=env_for(self.board), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks", timeout=1) as r:
                    if r.status == 200:
                        return pr
            except (urllib.error.URLError, OSError, ConnectionError):
                time.sleep(0.05)
        pr.kill()
        self.fail("the server did not come up")

    def post(self, port, title):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/tasks", data=json.dumps({"title": title}).encode(),
                                     headers={"Content-Type": "application/json", "Host": f"localhost:{port}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["id"]

    def test_acknowledged_cards_survive_the_kill_and_the_restart(self):
        port = free_port()
        srv = self.start(port)
        self.addCleanup(lambda: srv.poll() is None and srv.kill())
        acked, lock, stop = [], threading.Lock(), threading.Event()

        def client(k):
            n = 0
            while not stop.is_set():
                try:
                    cid = self.post(port, f"card {k} {n}")
                except (urllib.error.URLError, OSError, ConnectionError, ValueError):
                    return   # the server is gone
                with lock:
                    acked.append(cid)
                n += 1
        ts = [threading.Thread(target=client, args=(k,)) for k in range(4)]
        for t in ts:
            t.start()
        time.sleep(1.0)
        os.kill(srv.pid, signal.SIGKILL)
        srv.wait(timeout=10)
        stop.set()
        for t in ts:
            t.join(timeout=15)
        self.assertGreater(len(acked), 4)
        ok, msg, _ = backup.verify_file(self.board / "tasks.json")
        self.assertTrue(ok, msg)
        have = {t["id"] for t in self.s.load()}
        self.assertTrue(set(acked) <= have, sorted(set(acked) - have))
        srv2 = self.start(port)   # the same folder, the same port, straight away
        self.addCleanup(lambda: srv2.poll() is None and srv2.kill())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks", timeout=5) as r:
            d = json.loads(r.read())
        listed = {t["id"] for t in (d["tasks"] if isinstance(d, dict) else d)}
        self.assertTrue(set(acked) <= listed)
        srv2.kill()
        srv2.wait(timeout=10)


# -- corrupt files, clear words, recovery, verify ---------------------------------------------------------------------------------------------
class CorruptFiles(Base):
    def test_a_corrupt_board_file_names_the_good_copy_and_the_command(self):
        self.s.add("one")
        self.s.add("two")   # tasks.json.bak now holds the one-card board
        (self.board / "tasks.json").write_text('{"tasks": [{"id": "one", ')
        with self.assertRaises(BoardError) as cm:
            self.s.load()
        msg = str(cm.exception)
        self.assertIn("is not valid JSON", msg)
        self.assertIn("tasks.json.bak (the version before the last save) is good, 1 tasks", msg)
        self.assertIn("agentboard restore previous", msg)
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("BAD tasks.json", out)
        self.assertIn("ok  tasks.json.bak", out)
        code, out, _ = self.run_cli("restore", "previous", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual([t["id"] for t in self.s.load()], ["one"])

    def test_with_no_bak_the_newest_snapshot_is_named_and_with_nothing_the_place_to_look(self):
        self.s.add("one")
        snap = self.s.backups.take()
        (self.board / "tasks.json.bak").unlink(missing_ok=True)
        (self.board / "tasks.json").write_text("not json")
        with self.assertRaises(BoardError) as cm:
            self.s.load()
        self.assertIn(f"the newest snapshot {snap.name} is good, 1 tasks: run `agentboard restore latest`", str(cm.exception))
        snap.unlink()
        with self.assertRaises(BoardError) as cm:
            self.s.load()
        self.assertIn("no good copy was found beside it", str(cm.exception))

    def test_a_corrupt_state_file_is_read_as_empty_and_named_by_verify(self):
        self.s.add("one")
        self.s.backups.take()
        (self.board / "chat-cursors.json").write_text("{{{")
        (self.board / "sessions.json").write_text("[1, 2")
        self.assertEqual(agentchat.read_cursors(self.s), {})
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("BAD chat-cursors.json is not valid JSON", out)
        self.assertIn("BAD sessions.json is not valid JSON", out)
        self.assertIn("ok  tasks.json", out)
        agentchat.write_cursor(self.s, "AGENT-1", 1)   # the next write heals it
        (self.board / "sessions.json").unlink()
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 0, out)

    def test_verify_restores_the_newest_snapshot_into_a_scratch_folder(self):
        self.s.add("one")
        self.s.add("two")
        snap = self.s.backups.take()
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 0, out)
        self.assertIn(f"ok  restore test: {snap.name} restores to a board of 2 tasks", out)
        self.assertTrue((self.board / "tasks.json").exists())   # the test touched nothing here
        self.assertEqual(len(self.s.load()), 2)
        bad = self.board / "backups" / "tasks-20991231-2359.json"   # a newer-named snapshot that is not a board
        bad.write_text('{"tasks": [{"id": "x", "status": "flying"}]}')
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("BAD tasks-20991231-2359.json", out)

    def test_verify_fix_sweeps_temp_files_and_sets_a_broken_state_file_aside(self):
        self.s.add("one")
        self.s.backups.take()
        old = self.board / ".tasks.json-old.tmp"
        old.write_text("{half")
        os.utime(old, (time.time() - 120, time.time() - 120))
        fresh = self.board / ".tasks.json-fresh.tmp"
        fresh.write_text("{half")
        (self.board / "chat-cursors.json").write_text("{{{")
        code, out, _ = self.run_cli("verify", "--fix")
        self.assertEqual(code, 0, out)
        self.assertIn("fixed removed .tasks.json-old.tmp", out)
        self.assertIn("fixed set chat-cursors.json aside as chat-cursors.json.broken-", out)
        self.assertNotIn("BAD", out)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())   # under a minute old: it may be a write in flight
        self.assertFalse((self.board / "chat-cursors.json").exists())
        self.assertEqual(len(list(self.board.glob("chat-cursors.json.broken-*"))), 1)
        agentchat.write_cursor(self.s, "AGENT-1", 3)   # rebuilt from use
        self.assertEqual(agentchat.read_cursors(self.s), {"agent-1": 3})

    def test_a_half_written_card_list_is_refused_with_the_card_named(self):
        self.s.add("one")
        d = json.loads((self.board / "tasks.json").read_text())
        d["tasks"].append({"title": "no id"})
        (self.board / "tasks.json").write_text(json.dumps(d))
        with self.assertRaises(BoardError) as cm:
            self.s.load()
        self.assertIn("has no id", str(cm.exception))


class EveryWriteIsAtomic(unittest.TestCase):
    def test_no_module_writes_a_state_file_in_place(self):
        """No `write_text(json.dumps(` and no bare open-for-write of a .json beside the board in the package: everything goes through
        backup.write_atomic or statefile (boards.py and serverstate.py have their own temp-and-rename)."""
        src = Path(SRC) / "agentboard"
        offenders = []
        for f in sorted(src.glob("*.py")):
            text = f.read_text()
            for n, line in enumerate(text.splitlines(), 1):
                if "write_text(json.dumps(" in line and f.name not in ("statefile.py",):
                    offenders.append(f"{f.name}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
