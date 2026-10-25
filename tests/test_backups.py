import gzip
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from agentboard import backup, cli
from agentboard.store import BoardError, Store


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / ".agentboard"
        self.s = Store(self.dir)
        self.s.add("A", status="todo")
        self.b = self.s.backups

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = StringIO(), StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.dir)}), redirect_stdout(out), redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                err.write(str(e.code) if not isinstance(e.code, int) else "")
        return code, out.getvalue(), err.getvalue()


class AtomicWriteTests(Base):
    def test_every_save_keeps_the_previous_version_as_a_bak(self):
        first = json.loads(self.s.path.read_text())
        self.s.add("B", status="todo")
        prev = json.loads(Path(f"{self.s.path}.bak").read_text())
        self.assertEqual([t["id"] for t in prev["tasks"]], [t["id"] for t in first["tasks"]])
        self.assertEqual([t["id"] for t in json.loads(self.s.path.read_text())["tasks"]], ["a", "b"])

    def test_a_failed_write_leaves_the_file_and_no_temp_behind(self):
        before = self.s.path.read_text()
        with mock.patch("agentboard.backup.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            backup.write_atomic(self.s.path, "{}")
        self.assertEqual(self.s.path.read_text(), before)
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])

    def test_the_file_is_never_missing_during_a_save(self):
        seen = []
        real = os.replace

        def spy(a, b):
            seen.append(Path(self.s.path).exists())
            return real(a, b)

        with mock.patch("agentboard.backup.os.replace", side_effect=spy):
            self.s.add("C", status="todo")
        self.assertTrue(all(seen))

    def test_a_broken_file_says_how_to_get_the_board_back(self):
        self.s.path.write_text("{ nope")
        with self.assertRaises(BoardError) as c:
            self.s.load()
        self.assertIn("agentboard restore latest", str(c.exception))


class SnapshotTests(Base):
    def test_a_save_takes_a_snapshot_when_none_is_an_hour_old(self):
        names = [p.name for p in self.b.snapshots()]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith(".json.gz"))
        self.s.add("B", status="todo")   # saved again within the hour: no second snapshot
        self.assertEqual(len(self.b.snapshots()), 1)
        self.assertEqual(len(json.loads(gzip.open(self.b.latest()).read())["tasks"]), 1)

    def test_an_hour_later_the_next_save_snapshots_again(self):
        for p in self.b.snapshots():
            p.unlink()
        self.b.tick(at(25, 12, 0))
        self.assertIsNotNone(self.b.tick(at(25, 13, 5)))
        self.assertIsNone(self.b.tick(at(25, 13, 30)))

    def test_a_bad_board_file_is_never_snapshotted(self):
        for p in self.b.snapshots():
            p.unlink()
        self.s.path.write_text("{ nope")
        self.assertIsNone(self.b.tick(at(25, 12)))
        self.assertEqual(self.b.snapshots(), [])

    def test_retention_keeps_48_hourly_and_30_daily_and_never_touches_hand_made_files(self):
        for p in self.b.snapshots():
            p.unlink()
        now = at(25, 12, 0)
        made = []
        for h in range(0, 24 * 40):   # 40 days of hourly snapshots, newest first
            when = now - timedelta(hours=h)
            made.append(self.b.take(when=when))
        manual = self.b.take("before-clear", when=now - timedelta(days=90))
        keep_manual = self.b.snap_dir / "tasks-20261025-1409-before-clear.json"
        keep_manual.write_text("{}")
        self.b.prune(now)
        left = {p.name for p in self.b.snapshots()}
        hourly = [n for n in left if self.b.stamp(n) and self.b.stamp(n) > now - timedelta(hours=48)]
        self.assertEqual(len(hourly), 48)
        days = {self.b.stamp(n).date() for n in left if self.b.stamp(n)}
        self.assertEqual(len(days), 31)   # today + the 30 daily ones (the newest of each day)
        self.assertIn(manual.name, left)   # named snapshots stay
        self.assertIn(keep_manual.name, left)
        oldest_day = min(days)
        newest_that_day = max(self.b.stamp(n) for n in left if self.b.stamp(n) and self.b.stamp(n).date() == oldest_day)
        self.assertEqual(newest_that_day.hour, 23)


class SyncTests(Base):
    def setUp(self):
        super().setUp()
        self.sync = self.root / "iCloud" / "agentboard-backups"
        (self.dir / "config.toml").write_text(f'[backup]\nsync_dir = "{self.sync}"\n')
        self.b = self.s.backups

    def test_the_nightly_copy_happens_once_a_day_after_two_in_the_morning(self):
        self.assertIsNone(self.b.sync(at(26, 1, 30)))   # too early
        dest = self.b.sync(at(26, 3, 0))
        self.assertTrue(dest.exists() and dest.parent == self.sync)
        self.assertEqual(json.loads(gzip.open(dest).read())["tasks"][0]["id"], "a")
        self.assertIsNone(self.b.sync(at(26, 9, 0)))   # already done today
        self.assertIsNotNone(self.b.sync(at(27, 3, 0)))
        self.assertEqual(len(list(self.sync.glob("agentboard-*.json.gz"))), 2)

    def test_old_copies_are_removed_after_30_days_and_nothing_else_is(self):
        self.sync.mkdir(parents=True)
        stem = self.dir.parent.name
        old = self.sync / f"agentboard-{stem}-20260801.json.gz"
        old.write_bytes(b"x")
        other = self.sync / "holiday-photos.zip"
        other.write_bytes(b"x")
        self.b.sync(at(26, 3, 0))
        self.assertFalse(old.exists())
        self.assertTrue(other.exists())

    def test_without_a_sync_dir_nothing_is_copied(self):
        (self.dir / "config.toml").write_text("")
        self.assertIsNone(self.s.backups.sync(at(26, 3, 0), force=True))

    def test_a_sync_problem_never_stops_a_save(self):
        (self.dir / "config.toml").write_text('[backup]\nsync_dir = "/proc/nope/agentboard"\n')
        self.s.add("Z", status="todo")
        self.assertIn("z", [t["id"] for t in self.s.load()])


class CommandTests(Base):
    def test_backup_restore_roundtrip_keeps_a_safety_copy(self):
        code, out, _ = self.run_cli("backup", "--label", "before-cleanup")
        self.assertEqual(code, 0)
        snap = out.strip().rsplit("/", 1)[-1]
        self.assertIn("before-cleanup", snap)
        self.s.add("B", status="todo")
        self.s.add("C", status="todo")
        self.assertEqual(len(self.s.load()), 3)
        code, out, err = self.run_cli("restore", snap)
        self.assertNotEqual(code, 0)
        self.assertIn("--yes", err + out)   # not on a terminal: it refuses to guess
        self.assertEqual(len(self.s.load()), 3)
        code, out, _ = self.run_cli("restore", snap, "--yes")
        self.assertEqual(code, 0)
        self.assertEqual([t["id"] for t in self.s.load()], ["a"])
        self.assertIn("before-restore", out)   # the board as it was is kept
        saved = [p for p in self.b.snapshots() if "before-restore" in p.name]
        self.assertEqual(len(json.loads(gzip.open(saved[0]).read())["tasks"]), 3)

    def test_restore_latest_and_previous(self):
        self.s.add("B", status="todo")
        code, _, _ = self.run_cli("restore", "previous", "--yes")   # the version before the last save
        self.assertEqual(code, 0)
        self.assertEqual([t["id"] for t in self.s.load()], ["a"])
        self.s.path.write_text("{ nope")
        code, _, _ = self.run_cli("restore", "latest", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual([t["id"] for t in self.s.load()], ["a"])

    def test_restore_refuses_a_bad_file_and_a_missing_one(self):
        bad = self.root / "bad.json"
        bad.write_text('{"tasks": [{"id": "x", "status": "weird"}]}')
        self.assertNotEqual(self.run_cli("restore", str(bad), "--yes")[0], 0)
        self.assertNotEqual(self.run_cli("restore", "nope.json", "--yes")[0], 0)
        self.assertEqual([t["id"] for t in self.s.load()], ["a"])

    def test_verify_passes_on_a_good_board_and_fails_when_it_is_not(self):
        code, out, _ = self.run_cli("verify", "--all")
        self.assertEqual(code, 0, out)
        self.assertIn("newest snapshot", out)
        self.s.path.write_text("{ nope")
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("BAD tasks.json", out)

    def test_verify_fails_when_the_newest_snapshot_is_stale_or_missing(self):
        for p in self.b.snapshots():
            old = (datetime.now() - timedelta(hours=5)).timestamp()
            os.utime(p, (old, old))
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("5 h ago", out)
        for p in self.b.snapshots():
            p.unlink()
        self.assertEqual(self.run_cli("verify")[0], 1)

    def test_verify_finds_a_damaged_snapshot(self):
        (self.b.snap_dir / "tasks-20260101-0000.json.gz").write_bytes(b"not gzip")
        code, out, _ = self.run_cli("verify", "--all")
        self.assertEqual(code, 1)
        self.assertIn("tasks-20260101-0000.json.gz", out)

    def test_backup_list_shows_the_snapshots(self):
        code, out, _ = self.run_cli("backup", "--list")
        self.assertEqual(code, 0)
        self.assertIn("1 snapshots", out)
        self.assertIn("not set", out)

    def test_hud_data_carries_the_age_of_the_newest_backup(self):
        st = self.b.status()
        self.assertEqual(st["snapshots"], 1)
        self.assertLessEqual(st["last_backup_min"], 1)
        self.assertEqual(backup.human_age(3), "3 min ago")
        self.assertEqual(backup.human_age(None), "never")
        self.assertEqual(backup.human_age(200), "3 h ago")


class ServerTests(Base):
    def test_api_hud_includes_the_backup_note(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from agentboard.server import make_handler

        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/hud", headers={"Host": f"localhost:{port}"})
            data = json.loads(urllib.request.urlopen(req, timeout=5).read())
        finally:
            srv.shutdown()
        self.assertIn("last_backup_min", data["backup"])


if __name__ == "__main__":
    unittest.main()
