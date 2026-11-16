"""ORCH busy in a long job is not "ORCH is not running" (card fix-orch-presence-while-busy).

The board called ORCH up only while a `chat inbox --wait` was open (90 s of grace). A wait ends the moment a line arrives and ORCH cannot open the next one
until its tool call ends, so a merge plus an eight-minute test run left the board saying "ORCH is not running" with a Start ORCH button, and the owner
pasted the start prompt into the live session. Now any board command a named session runs, a wait opened or closed, and the SendMessage and Stop hooks
leave a stamp (presence.py); the page counts ORCH as running while a wait is open or the stamp is younger than `[orch] presence_grace_s` (600 s)."""
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, hooks, listeners, presence
from agentboard.server import make_handler
from agentboard.store import Store

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
T0 = datetime(2026, 11, 15, 19, 0, 0)


def board():
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name) / ".agentboard"
    d.mkdir()
    return tmp, d


class TheStamp(unittest.TestCase):
    def setUp(self):
        self.tmp, self.dir = board()
        self.addCleanup(self.tmp.cleanup)

    def test_a_touch_records_the_lower_cased_name_and_the_time(self):
        self.assertTrue(presence.touch(self.dir, "ORCH", now=T0))
        self.assertEqual(presence.read(self.dir), {"orch": "2026-11-15T19:00:00"})

    def test_a_busy_session_does_not_write_on_every_command(self):
        presence.touch(self.dir, "ORCH", now=T0)
        self.assertFalse(presence.touch(self.dir, "ORCH", now=T0 + timedelta(seconds=presence.TOUCH_S - 1)))
        self.assertEqual(presence.read(self.dir)["orch"], "2026-11-15T19:00:00")
        self.assertTrue(presence.touch(self.dir, "ORCH", now=T0 + timedelta(seconds=presence.TOUCH_S + 1)))
        self.assertEqual(presence.read(self.dir)["orch"], "2026-11-15T19:00:11")

    def test_names_do_not_share_a_stamp_and_case_does_not_make_two(self):
        presence.touch(self.dir, "ORCH", now=T0)
        presence.touch(self.dir, "TaskMaster-3", now=T0 + timedelta(seconds=30))
        presence.touch(self.dir, "orch", now=T0 + timedelta(seconds=60))
        self.assertEqual(set(presence.read(self.dir)), {"orch", "taskmaster-3"})
        self.assertEqual(presence.read(self.dir)["orch"], "2026-11-15T19:01:00")

    def test_nothing_is_written_for_no_name(self):
        for n in (None, "", "   ", 5):
            self.assertFalse(presence.touch(self.dir, n, now=T0))
        self.assertFalse(presence.path(self.dir).exists())

    def test_a_stamp_of_a_session_long_gone_is_dropped(self):
        presence.touch(self.dir, "Old-1", now=T0)
        presence.touch(self.dir, "ORCH", now=T0 + timedelta(seconds=presence.KEEP_S + 60))
        self.assertEqual(set(presence.read(self.dir)), {"orch"})

    def test_a_broken_file_reads_as_nothing_and_the_next_touch_repairs_it(self):
        presence.path(self.dir).write_text("{not json")
        self.assertEqual(presence.read(self.dir), {})
        self.assertTrue(presence.touch(self.dir, "ORCH", now=T0))
        self.assertEqual(set(presence.read(self.dir)), {"orch"})

    def test_a_stamp_never_stops_a_command(self):
        with mock.patch("agentboard.presence.statefile.update", side_effect=OSError("disk full")):
            self.assertFalse(presence.touch(self.dir, "ORCH", now=T0))

    def test_the_grace_is_ten_minutes_unless_the_config_says_otherwise(self):
        self.assertEqual(presence.grace_s({}), 600)
        self.assertEqual(presence.grace_s({"orch": {"presence_grace_s": 900}}), 900)
        for bad in (5, 90000, "600", True, 12.5, None):
            self.assertEqual(presence.grace_s({"orch": {"presence_grace_s": bad}}), 600, bad)


class WhatLeavesAStamp(unittest.TestCase):
    def setUp(self):
        self.tmp, self.dir = board()
        self.addCleanup(self.tmp.cleanup)
        Store(self.dir)

    def run_cli(self, *argv, env=None):
        env = {"AGENTBOARD_DIR": str(self.dir), **(env or {})}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if "AGENTBOARD_NAME" not in env:
                os.environ.pop("AGENTBOARD_NAME", None)   # this shell's own name must not leak in; patch.dict puts it back
            cli.main(list(argv))

    def test_a_board_command_with_a_name_leaves_one(self):
        self.run_cli("chat", "send", "merged, running the suite", "--name", "ORCH")
        self.assertIn("orch", presence.read(self.dir))

    def test_the_name_can_come_from_the_environment(self):
        self.run_cli("list", env={"AGENTBOARD_NAME": "ORCH"})
        self.assertIn("orch", presence.read(self.dir))

    def test_a_command_with_no_name_leaves_none(self):
        self.run_cli("list")
        self.assertEqual(presence.read(self.dir), {})

    def test_opening_and_closing_a_wait_each_leave_one(self):
        pid = listeners.register(self.dir, "ORCH", "inbox")
        first = presence.read(self.dir)["orch"]
        self.assertTrue(first)
        old = (datetime.now() - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%S")
        presence.path(self.dir).write_text(json.dumps({"orch": old}))
        listeners.unregister(self.dir, "ORCH", pid)
        self.assertGreater(presence.read(self.dir)["orch"], old)   # the wait ended: the session was alive just now

    def test_the_hooks_leave_one_for_a_session_that_has_a_name(self):
        store = Store(self.dir)
        payload = json.dumps({"session_id": "abc123", "tool_input": {"to": "TaskMaster-1", "message": "hi"}})
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "ORCH"}):
            hooks.run_hook(store, stdin=io.StringIO(payload))
        self.assertIn("orch", presence.read(self.dir))
        presence.path(self.dir).unlink()
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "ORCH"}):
            hooks.run_stop_hook(store, stdin=io.StringIO(json.dumps({"session_id": "abc123"})), stdout=io.StringIO())
        self.assertIn("orch", presence.read(self.dir))

    def test_a_hook_from_a_session_that_never_gave_a_name_leaves_none(self):
        store = Store(self.dir)
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("AGENTBOARD_NAME", None)
            hooks.run_stop_hook(store, stdin=io.StringIO(json.dumps({"session_id": "zzz"})), stdout=io.StringIO())
        self.assertEqual(presence.read(self.dir), {})


class WhatTheBoardServes(unittest.TestCase):
    def setUp(self):
        self.tmp, self.dir = board()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(self.dir)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": f"localhost:{self.port}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_the_chat_receipts_carry_who_was_seen_and_when(self):
        presence.touch(self.dir, "ORCH", now=datetime.now())
        seen = self.get("/api/chat")["receipts"]["seen"]
        self.assertIn("orch", seen)

    def test_the_page_is_told_the_grace(self):
        self.assertEqual(self.get("/api/config")["orch_grace_s"], 600)
        (self.dir / "config.toml").write_text("[orch]\npresence_grace_s = 120\n")
        self.assertEqual(self.get("/api/config")["orch_grace_s"], 120)


class OnThePage(unittest.TestCase):
    def sync(self):
        return PAGE[PAGE.index("function orchSync()"):PAGE.index("setInterval(orchSync, 1000)")]

    def test_the_default_grace_is_ten_minutes_and_the_config_sets_it(self):
        self.assertIn("orchGraceMs = 600000", PAGE)
        self.assertIn("cfg.orch_grace_s * 1000", self.sync())

    def test_a_recent_sign_of_life_holds_the_line_up(self):
        s = self.sync()
        self.assertIn("chatReceipts.seen", s)
        self.assertIn("else if (seen > orchSince) orchSince = seen", s)
        self.assertIn("const down = !up && Date.now() - orchSince > orchGraceMs", s)   # only a quiet longer than the grace shows Start ORCH

    def test_the_stamp_is_read_as_a_value_not_a_key(self):
        self.assertIn("chatReceipts.seen[sk]", self.sync())   # nameKey returns the key; the time is its value


if __name__ == "__main__":
    unittest.main()
