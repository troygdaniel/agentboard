"""Cleared cards move out of tasks.json into archive.json (morning-troy-decides-move-archived-cards): the live board stays small, and the
readers that want history (recall, lookup, the HUD, list --all, the summary) see both files through load_all. Fake boards in temp folders."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from agentboard import agentchat, cli, hud, lookup
from agentboard.store import BoardError, Store, subtask_counts


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / ".agentboard"
        self.s = Store(self.dir)
        self._env = {k: os.environ.get(k) for k in ("AGENTBOARD_DIR", "AGENTBOARD_BOARD", "AGENTBOARD_NAME")}
        os.environ["AGENTBOARD_DIR"] = str(self.dir)
        os.environ.pop("AGENTBOARD_BOARD", None)
        os.environ.pop("AGENTBOARD_NAME", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def finish(self, task_id, title, agent="AGENT-9"):
        self.s.add(title, status="todo", task_id=task_id)
        self.s.claim(task_id, agent)
        self.s.review(task_id, "finished")
        self.s.update(task_id, status="done")

    def live_ids(self):
        return [t["id"] for t in self.s.load()]

    def archived_ids(self):
        return [t["id"] for t in self.s.load_archived()]

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue()


class ClearMovesCards(Base):
    def test_clear_moves_done_cards_to_archive_json_and_leaves_open_ones(self):
        self.finish("old", "Old thing")
        self.s.add("Open thing", status="todo", task_id="open")
        self.assertEqual(self.s.clear_done(), ["old"])
        self.assertEqual(self.live_ids(), ["open"])
        self.assertEqual(self.archived_ids(), ["old"])
        on_disk = json.loads((self.dir / "archive.json").read_text())
        self.assertEqual(list(on_disk), ["tasks"])
        self.assertTrue(on_disk["tasks"][0]["archived"])
        self.assertEqual([t["id"] for t in self.s.load_all()], ["open", "old"])   # live first, then the archive

    def test_tasks_json_no_longer_carries_the_cleared_card(self):
        self.finish("old", "Old thing")
        self.s.clear_done()
        raw = (self.dir / "tasks.json").read_text()
        self.assertNotIn('"old"', raw)

    def test_a_card_archived_before_the_file_existed_moves_on_the_next_clear(self):
        self.finish("legacy", "From before")
        with self.s.transaction() as tasks:   # what an older agentboard left behind: the flag, in tasks.json
            Store.get(tasks, "legacy")["archived"] = True
        self.finish("fresh", "New one")
        self.assertEqual(self.s.clear_done(), ["fresh"])   # the return value is still what was cleared now
        self.assertEqual(self.live_ids(), [])
        self.assertEqual(sorted(self.archived_ids()), ["fresh", "legacy"])

    def test_clear_with_nothing_to_move_writes_no_archive_file(self):
        self.s.add("Open thing", status="todo", task_id="open")
        self.assertEqual(self.s.clear_done(), [])
        self.assertFalse((self.dir / "archive.json").exists())
        self.assertEqual(self.s.load_archived(), [])
        self.assertEqual(self.s.load_all(), self.s.load())

    def test_second_clear_appends_to_the_archive(self):
        self.finish("one", "One")
        self.s.clear_done()
        self.finish("two", "Two")
        self.s.clear_done()
        self.assertEqual(self.archived_ids(), ["one", "two"])
        self.assertTrue((self.dir / "archive.json.bak").exists())   # the previous version, like tasks.json.bak


class SubtasksKeepTheirSlots(Base):
    def setUp(self):
        super().setUp()
        self.s.add("Big", status="todo", task_id="big")
        for sid in ("one", "two"):
            self.s.add(sid, parent_id="big", task_id=sid)
        self.s.claim("big", "atlas")
        self.s.update("one", 100)

    def test_an_archived_subtask_of_an_open_parent_stays_in_tasks_json(self):
        self.s.bulk_archive(["one"])
        self.assertIn("one", self.live_ids())
        self.assertTrue(Store.get(self.s.load(), "one")["archived"])
        self.assertEqual(self.archived_ids(), [])
        self.assertEqual(subtask_counts(self.s.load())["big"], (2, 1))   # the parent's bar keeps its slot

    def test_the_whole_card_moves_once_the_parent_is_done_and_cleared(self):
        self.s.bulk_archive(["one"])
        self.s.update("two", 100)
        self.s.update("big", status="done")
        self.assertEqual(set(self.s.clear_done()), {"big", "two"})   # "one" was archived earlier; it moves along
        self.assertEqual(self.live_ids(), [])
        self.assertEqual(sorted(self.archived_ids()), ["big", "one", "two"])

    def test_bulk_archive_of_a_parent_moves_it_and_its_subtasks(self):
        self.assertEqual(set(self.s.bulk_archive(["big"])), {"big", "one", "two"})
        self.assertEqual(self.live_ids(), [])
        self.assertEqual(sorted(self.archived_ids()), ["big", "one", "two"])


class ComingBack(Base):
    def test_unarchive_brings_a_cleared_card_back_with_its_subtasks(self):
        self.s.add("Big", status="todo", task_id="big")
        self.s.add("kid", parent_id="big", task_id="kid")
        self.s.add("Other", status="todo", task_id="other")
        self.s.bulk_archive(["big"])
        self.assertEqual(self.live_ids(), ["other"])
        self.s.unarchive(["big"])   # what the page's undo sends
        self.assertEqual(sorted(self.live_ids()), ["big", "kid", "other"])
        self.assertEqual(self.archived_ids(), [])
        self.assertNotIn("archived", Store.get(self.s.load(), "big"))
        self.assertNotIn("archived", Store.get(self.s.load(), "kid"))

    def test_unarchive_of_a_flagged_card_still_in_tasks_json_works_as_before(self):
        self.s.add("Big", status="doing", task_id="big")
        self.s.add("kid", parent_id="big", task_id="kid")
        self.s.bulk_archive(["kid"])   # stays in tasks.json, flagged (open parent)
        self.s.unarchive(["kid"])
        self.assertNotIn("archived", Store.get(self.s.load(), "kid"))
        self.assertFalse((self.dir / "archive.json").exists())

    def test_force_claim_reopens_a_cleared_card_from_the_archive(self):
        self.finish("d", "D")
        self.s.clear_done()
        t = self.s.claim("d", "bob", force=True)
        self.assertEqual((t["status"], t["agent"]), ("doing", "bob"))
        self.assertNotIn("archived", t)
        self.assertEqual(self.live_ids(), ["d"])
        self.assertEqual(self.archived_ids(), [])

    def test_claim_without_force_refuses_a_cleared_card_and_touches_nothing(self):
        self.finish("d", "D")
        self.s.clear_done()
        before = (self.dir / "archive.json").read_text()
        with self.assertRaises(BoardError) as cm:
            self.s.claim("d", "bob")
        self.assertIn("archive.json", str(cm.exception))
        self.assertIn("--force", str(cm.exception))
        self.assertEqual((self.dir / "archive.json").read_text(), before)
        self.assertEqual(self.live_ids(), [])

    def test_a_card_in_both_files_counts_once_and_the_live_one_wins(self):
        self.finish("d", "D")
        self.s.clear_done()
        with self.s.transaction() as tasks:   # an older tasks.json put back by restore still holds the card, not yet cleared
            tasks.append({"id": "d", "title": "D (live copy)", "status": "done", "progress": 100, "status_text": "", "log": []})
        every = self.s.load_all()
        self.assertEqual([t["id"] for t in every], ["d"])
        self.assertEqual(every[0]["title"], "D (live copy)")


class HistoryReaders(Base):
    def setUp(self):
        super().setUp()
        self.s.set_chat_agents(True)
        self.s.start("Old lock fix", "AGENT-2")
        self.s.update("old-lock-fix", 100, "switched the lock to flock on the fd", status="done")
        self.s.clear_done()
        self.s.add("Open pelican question", status="todo", task_id="open-one")

    def test_recall_reaches_the_archive(self):
        rows = agentchat.recall(self.s.load_all(), [], "flock")
        self.assertEqual([(r["kind"], r["id"], r["archived"]) for r in rows], [("card", "old-lock-fix", True)])
        code, out = self.cli("recall", "flock")
        self.assertEqual(code, 0)
        self.assertIn("old-lock-fix", out)
        self.assertIn("(archived)", out)

    def test_lookup_reaches_the_archive(self):
        hits, _ = lookup.lookup(self.s, "flock")
        self.assertEqual([h["where"] for h in hits], ["old-lock-fix [archived]"])

    def test_hud_history_counts_the_cleared_card(self):
        self.assertEqual(hud.build(self.s.load_all())["totals"]["done_today"], 1)
        self.assertEqual(hud.build(self.s.load())["totals"]["done_today"], 0)   # the live file alone does not: the server uses load_all

    def test_list_all_shows_it_and_plain_list_does_not(self):
        code, out = self.cli("list", "--all")
        self.assertEqual(code, 0)
        self.assertIn("old-lock-fix", out)
        code, out = self.cli("list")
        self.assertEqual(code, 0)
        self.assertNotIn("old-lock-fix", out)

    def test_report_counts_the_cleared_card_as_finished_today(self):
        code, out = self.cli("report")
        self.assertEqual(code, 0)
        self.assertIn("Old lock fix", out)


class CardDetail(Base):
    def test_the_detail_route_still_opens_a_cleared_card(self):
        from agentboard import server
        from http.server import ThreadingHTTPServer
        import http.client
        import threading
        self.finish("d", "D")
        self.s.clear_done()
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.s, 0))   # a free port, then a handler that knows it (the Host check)
        port = probe.server_address[1]
        probe.server_close()
        srv = ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(self.s, port))
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/api/task?id=d", headers={"Host": f"localhost:{port}"})   # the handler's own-origin check
            r = c.getresponse()
            body = json.loads(r.read())
            self.assertEqual(r.status, 200)
            self.assertEqual((body["id"], body["status"], body.get("archived")), ("d", "done", True))
            c.request("GET", "/api/task?id=nope", headers={"Host": f"localhost:{port}"})
            self.assertEqual(c.getresponse().status, 404)
        finally:
            srv.shutdown()
            srv.server_close()


class DamagedArchive(Base):
    def test_a_damaged_archive_stops_history_readers_with_one_line_but_not_the_live_board(self):
        self.finish("d", "D")
        self.s.clear_done()
        (self.dir / "archive.json").write_text("{not json")
        self.assertEqual(self.live_ids(), [])   # load() never reads the archive
        self.s.add("Still works", status="todo", task_id="ok")
        with self.assertRaises(BoardError) as cm:
            self.s.load_all()
        self.assertIn("archive.json", str(cm.exception))
        self.assertIn("verify", str(cm.exception))
        self.assertEqual((self.dir / "archive.json").read_text(), "{not json")   # never overwritten with a guess

    def test_clear_refuses_rather_than_overwrite_a_damaged_archive(self):
        self.finish("d", "D")
        self.s.clear_done()
        (self.dir / "archive.json").write_text("[]")   # valid JSON, wrong shape
        self.finish("e", "E")
        with self.assertRaises(BoardError):
            self.s.clear_done()
        self.assertEqual(self.live_ids(), ["e"])   # tasks.json was not saved either: the card is not lost
        self.assertEqual(Store.get(self.s.load(), "e").get("archived"), None)

    def test_verify_reports_the_archive(self):
        self.finish("d", "D")
        self.s.clear_done()
        self.s.backups.take()
        code, out = self.cli("verify")
        self.assertIn("ok  archive.json  1 cleared cards", out)
        (self.dir / "archive.json").write_text("{not json")
        code, out = self.cli("verify")
        self.assertNotEqual(code, 0)
        self.assertIn("BAD archive.json", out)


if __name__ == "__main__":
    unittest.main()
