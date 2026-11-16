"""A listener whose process died is not "listening" because some other process got its pid (finding-a-dead-listener-whose-pid-is-reu).

`listeners.alive(pid)` asks whether ANY process has that pid. After a wait is killed and the system hands its pid to an unrelated program, the
agent still showed as listening, and ORCH could wait for a reply that never came. A wait now writes a heartbeat into its entry about every
BEAT_S seconds while it runs; an entry with a heartbeat older than STALE_S is not listening, whoever holds the pid. An entry with no heartbeat
(written by an older agentboard) is judged by its pid alone, as before."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agentboard import listeners


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class Heartbeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.pid = os.getpid()   # a pid that is certainly alive: stands in for "another process got the dead wait's pid"

    def write(self, **entry):
        listeners.path(self.dir).write_text(json.dumps({"AGENT-1": [{"pid": self.pid, "since": stamp(datetime.now()), "what": "inbox", **entry}]}))

    def test_a_new_wait_has_a_heartbeat_and_is_listening(self):
        listeners.register(self.dir, "AGENT-1", "inbox")
        entry = json.loads(listeners.path(self.dir).read_text())["AGENT-1"][0]
        self.assertIn("beat", entry)
        self.assertTrue(listeners.is_listening(self.dir, "AGENT-1"))

    def test_a_stale_heartbeat_is_not_listening_though_the_pid_is_alive(self):
        self.write(beat=stamp(datetime.now() - timedelta(seconds=listeners.STALE_S + 30)))
        self.assertFalse(listeners.is_listening(self.dir, "AGENT-1"))
        self.assertEqual(listeners.sessions(self.dir, "AGENT-1"), 0)

    def test_a_fresh_heartbeat_is_listening(self):
        self.write(beat=stamp(datetime.now() - timedelta(seconds=listeners.STALE_S - 30)))
        self.assertTrue(listeners.is_listening(self.dir, "AGENT-1"))

    def test_an_entry_from_an_older_version_is_judged_by_its_pid(self):
        self.write()
        self.assertTrue(listeners.is_listening(self.dir, "AGENT-1"))

    def test_beat_renews_the_entry_and_only_its_own(self):
        old = stamp(datetime.now() - timedelta(seconds=listeners.STALE_S + 30))
        listeners.path(self.dir).write_text(json.dumps({"AGENT-1": [{"pid": self.pid, "since": old, "what": "inbox", "beat": old},
                                                                    {"pid": 1, "since": old, "what": "inbox", "beat": old}]}))
        self.assertTrue(listeners.beat(self.dir, "AGENT-1", self.pid, force=True))
        recs = {r["pid"]: r for r in json.loads(listeners.path(self.dir).read_text())["AGENT-1"]}
        self.assertGreater(recs[self.pid]["beat"], old)
        self.assertTrue(listeners.is_listening(self.dir, "AGENT-1"))
        self.assertEqual(listeners.sessions(self.dir, "AGENT-1"), 1)   # pid 1 is alive but its heartbeat is stale: not a session

    def test_beat_is_cheap_between_heartbeats(self):
        listeners.register(self.dir, "AGENT-1", "inbox")
        self.assertFalse(listeners.beat(self.dir, "AGENT-1", self.pid))   # just registered: nothing to write yet

    def test_the_wait_loops_send_the_heartbeat(self):
        src = (Path(listeners.__file__).parent / "cli.py").read_text()
        self.assertGreaterEqual(src.count("listeners.beat("), 2)   # chat inbox --wait and answer --wait


if __name__ == "__main__":
    unittest.main()
