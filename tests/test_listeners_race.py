"""chat-listeners.json under concurrent register/unregister (rev1107-listeners-race): before the lock, twenty threads registering at
once left 0 of 20 entries, so the panel said nobody was listening and offered Nudge for sessions whose wait was running. Now every
change is a locked read-modify-write and an atomic replace. A throwaway board; nothing reaches a real one."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from agentboard import listeners

SRC = str(Path(__file__).resolve().parents[1] / "src")


class ListenersRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        self.board.mkdir()

    def test_twenty_threads_registering_at_once_all_survive(self):
        names = [f"T-{i}" for i in range(20)]
        go = threading.Barrier(len(names))

        def one(n):
            go.wait()
            listeners.register(self.board, n, "inbox")

        ts = [threading.Thread(target=one, args=(n,)) for n in names]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(listeners.listening(self.board)), sorted(names))
        self.assertFalse((self.board / "chat-listeners.json.bak").exists())   # the small file keeps no .bak
        # each unregisters its own entry, at once: nothing else is lost, and the file ends empty
        ts = [threading.Thread(target=lambda n=n: (go.wait(), listeners.unregister(self.board, n))) for n in names]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(listeners.listening(self.board), {})
        self.assertEqual(json.loads((self.board / "chat-listeners.json").read_text()), {})

    def test_twelve_processes_registering_at_once_all_survive(self):
        n = 12
        code = ("import sys, time; from agentboard import listeners; name, board, at = sys.argv[1], sys.argv[2], float(sys.argv[3]); "
                "time.sleep(max(0.0, at - time.time())); listeners.register(board, name, 'inbox', pid=1); print('ok')")
        import time
        at = time.time() + 2.5
        env = {"PATH": os.environ["PATH"], "PYTHONPATH": SRC, "PYTHONDONTWRITEBYTECODE": "1", "HOME": self.tmp.name}
        procs = [subprocess.Popen([sys.executable, "-c", code, f"P-{i}", str(self.board), str(at)], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True) for i in range(n)]
        outs = [p.communicate(timeout=60)[0] for p in procs]
        self.assertTrue(all(o.strip() == "ok" for o in outs), outs)
        d = json.loads((self.board / "chat-listeners.json").read_text())
        self.assertEqual(sorted(d), sorted(f"P-{i}" for i in range(n)))   # pid 1 is alive on any Unix, so none is pruned

    def test_a_reader_never_sees_half_a_file(self):
        stop = threading.Event()
        bad = []

        def reader():
            while not stop.is_set():
                try:
                    (self.board / "chat-listeners.json").read_text() and json.loads((self.board / "chat-listeners.json").read_text())
                except ValueError as e:
                    bad.append(e)
                except OSError:
                    pass

        r = threading.Thread(target=reader)
        r.start()
        for i in range(200):
            listeners.register(self.board, f"W-{i % 7}", "x" * 60)
        stop.set()
        r.join()
        self.assertEqual(bad, [])
