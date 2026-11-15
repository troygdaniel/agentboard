"""Agent status, slice 1 (card agent-status-slice-1, docs/status-visibility-design.md): the board-asleep rule (awake.py), the sleep-aware quiet of an agent
(hud.build), the one look and the rows (status.py) and the wiring (/api/hud, the server tick). Everything runs on a throwaway board with made-up cards;
nothing reads a real board, starts a program or sends a message."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import awake, hud, status
from agentboard.store import Store

NOW = datetime(2026, 11, 14, 12, 0, 0)
FMT = "%Y-%m-%dT%H:%M:%S"


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).strftime(FMT)


def card(cid="c1", agent="atlas", updated=1, **kw):
    return dict({"id": cid, "title": "Card " + cid, "status": "doing", "agent": agent, "updated": ago(updated), "created": ago(300),
                 "progress": 40, "status_text": "on it", "log": []}, **kw)


class TheAwakeRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        p = self.dir / awake.FILE
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_a_board_that_ticks_every_minute_has_no_stretch(self):
        for i in range(10):
            self.assertEqual(awake.tick(self.dir, NOW + timedelta(minutes=i)), 0)
        self.assertEqual(self.lines(), [])
        self.assertEqual(awake.windows(self.dir, NOW + timedelta(minutes=10)), [])

    def test_a_tick_after_a_gap_writes_one_line_for_it_and_says_how_long(self):
        awake.tick(self.dir, NOW)
        self.assertEqual(awake.tick(self.dir, NOW + timedelta(minutes=125)), 125 * 60)
        self.assertEqual(self.lines(), [{"from": NOW.strftime(FMT), "to": (NOW + timedelta(minutes=125)).strftime(FMT)}])
        self.assertEqual(awake.tick(self.dir, NOW + timedelta(minutes=126)), 0)   # and only one
        self.assertEqual(len(self.lines()), 1)

    def test_three_minutes_exactly_is_not_a_gap_a_second_more_is(self):
        awake.tick(self.dir, NOW)
        self.assertEqual(awake.tick(self.dir, NOW + timedelta(seconds=awake.GAP_S)), 0)
        awake.tick(self.dir, NOW)
        self.assertEqual(awake.tick(self.dir, NOW + timedelta(seconds=awake.GAP_S + 1)), awake.GAP_S + 1)

    def test_what_is_stored_is_two_times_and_nothing_else(self):
        awake.tick(self.dir, NOW)
        awake.tick(self.dir, NOW + timedelta(hours=1))
        self.assertEqual(sorted(self.lines()[0]), ["from", "to"])
        self.assertEqual(sorted(json.loads((self.dir / awake.HEART).read_text())), ["last"])

    def test_a_reader_right_after_a_wake_already_gets_the_stretch(self):   # before the next tick has written it down
        awake.tick(self.dir, NOW)
        later = NOW + timedelta(minutes=90)
        self.assertEqual(awake.windows(self.dir, later), [(NOW, later)])

    def put(self, *spans):
        (self.dir / awake.FILE).write_text("".join(json.dumps({"from": x.strftime(FMT), "to": y.strftime(FMT)}) + "\n" for x, y in spans))

    def test_windows_keep_only_what_touches_the_last_days(self):
        self.put((NOW - timedelta(days=5), NOW - timedelta(days=5) + timedelta(hours=2)), (NOW - timedelta(hours=3), NOW - timedelta(hours=1)))
        self.assertEqual(len(awake.windows(self.dir, NOW, days=1)), 1)
        self.assertEqual(len(awake.windows(self.dir, NOW, days=10)), 2)

    def test_minutes_of_a_span_inside_a_window_are_not_awake(self):
        w = [(NOW + timedelta(minutes=10), NOW + timedelta(minutes=70))]
        self.assertEqual(awake.overlap_minutes(NOW, NOW + timedelta(minutes=100), w), 60)
        self.assertEqual(awake.awake_minutes(NOW, NOW + timedelta(minutes=100), w), 40)
        self.assertEqual(awake.awake_minutes(NOW, NOW + timedelta(minutes=30), w), 10)              # a span that ends inside it
        self.assertEqual(awake.awake_minutes(NOW + timedelta(minutes=40), NOW + timedelta(minutes=100), w), 30)   # and one that starts inside it
        self.assertEqual(awake.awake_minutes(NOW + timedelta(minutes=80), NOW + timedelta(minutes=95), w), 15)    # one clear of it
        self.assertEqual(awake.awake_minutes(NOW, NOW - timedelta(minutes=5), w), 0)                 # never negative

    def test_a_file_that_is_full_drops_the_old_stretches_and_keeps_the_new(self):
        old = NOW - timedelta(days=awake.KEEP_DAYS + 3)
        self.put((old, old + timedelta(hours=1)), (NOW - timedelta(hours=3), NOW - timedelta(hours=2)))
        (self.dir / awake.HEART).write_text(json.dumps({"last": (NOW - timedelta(hours=1)).strftime(FMT)}))
        with mock.patch.object(awake, "MAX_BYTES", 10):
            self.assertEqual(awake.tick(self.dir, NOW), 3600)   # another stretch, with the file over its size: the old one goes
        got = self.lines()
        self.assertEqual(len(got), 2)
        self.assertTrue(all(g["to"] >= (NOW - timedelta(days=awake.KEEP_DAYS)).strftime(FMT) for g in got))

    def test_junk_in_the_files_is_skipped_and_a_missing_folder_never_raises(self):
        (self.dir / awake.FILE).write_text('not json\n{"from": "x", "to": "y"}\n[1]\n{"from": "2026-11-14T10:00:00", "to": "2026-11-14T11:00:00"}\n')
        (self.dir / awake.HEART).write_text("{{{")
        self.assertEqual(awake.windows(self.dir, NOW), [(datetime(2026, 11, 14, 10), datetime(2026, 11, 14, 11))])
        self.assertEqual(awake.tick(self.dir / "nope" / "deeper", NOW), 0)
        self.assertEqual(awake.windows(self.dir / "nope", NOW), [])

    def test_the_latest_stretch_is_shown_for_six_hours_and_says_when_it_is_open(self):
        w = [(NOW - timedelta(hours=9), NOW - timedelta(hours=8)), (NOW - timedelta(hours=3), NOW - timedelta(hours=1))]
        got = awake.latest(w, NOW)
        self.assertEqual((got["minutes"], got["open"]), (120, False))
        self.assertIsNone(awake.latest(w[:1], NOW))
        self.assertTrue(awake.latest([(NOW - timedelta(minutes=5), NOW)], NOW)["open"])


class TheSleepRule(unittest.TestCase):
    def agent(self, cards, asleep=()):
        return {a["name"]: a for a in hud.build(cards, now=NOW, asleep=asleep)["agents"]}

    def test_without_windows_nothing_changed_two_hours_untouched_is_still_abandoned(self):
        a = self.agent([card(updated=200)])["atlas"]
        self.assertEqual((a["state"], a["quiet_min"]), ("abandoned", 200))

    def test_the_time_the_board_slept_does_not_count(self):
        w = [(NOW - timedelta(minutes=190), NOW - timedelta(minutes=65))]   # 125 of the 200 minutes
        a = self.agent([card(updated=200)], w)["atlas"]
        self.assertEqual((a["state"], a["quiet_min"]), ("quiet", 75))

    def test_a_card_untouched_only_while_the_board_slept_is_working(self):
        w = [(NOW - timedelta(minutes=90), NOW - timedelta(minutes=1))]
        a = self.agent([card(updated=60)], w)["atlas"]
        self.assertEqual(a["state"], "working")

    def test_awake_quiet_over_the_limit_is_abandoned_even_with_a_sleep_in_it(self):
        w = [(NOW - timedelta(minutes=100), NOW - timedelta(minutes=90))]
        self.assertEqual(self.agent([card(updated=300)], w)["atlas"]["state"], "abandoned")


class TheRows(unittest.TestCase):
    def rows(self, cards, listening=(), asleep=()):
        h = hud.build(cards, now=NOW, asleep=asleep, roster=("kite",))
        return status.build(h["agents"], cards, NOW, listening, asleep)

    def by(self, st):
        return {r["name"]: r for r in st["agents"]}

    def test_each_state_word(self):
        cards = [card("w", "work", updated=1), card("s", "silent", updated=40), card("g", "gone", updated=200),
                 card("a", "asks", updated=5, needs_input=True, question="3 or 5?"), card("r", "review", updated=7, review=True, result="done")]
        r = self.by(self.rows(cards))
        self.assertEqual({k: v["state"] for k, v in r.items() if k != "kite"},
                         {"work": "working", "silent": "silent", "gone": "gone", "asks": "waiting", "review": "review"})
        self.assertEqual(r["asks"]["line"], "3 or 5?")
        self.assertEqual(r["asks"]["waits_on"], "you")

    def test_idle_listening_and_away(self):
        self.assertEqual(self.by(self.rows([card()], listening={"kite"}))["kite"]["state"], "idle")
        self.assertEqual(self.by(self.rows([card()]))["kite"]["state"], "away")

    def test_a_card_in_review_waits_on_orch_until_orch_has_signed_it_off_then_on_you(self):
        plain = self.by(self.rows([card(updated=3, review=True)]))["atlas"]
        signed = self.by(self.rows([card(updated=3, review=True, signoff={"merged": "abc1234", "tests": []})]))["atlas"]
        self.assertEqual((plain["state"], plain["waits_on"], plain["group"]), ("review", "orch", "others"))
        self.assertEqual((signed["state"], signed["waits_on"], signed["group"]), ("review", "you", "you"))

    def test_an_agent_whose_card_waits_on_an_unfinished_card_is_blocked_and_names_it(self):
        cards = [card("a", "atlas", blocked_by=["b"]), card("b", status="todo", agent=None)]
        r = self.by(self.rows(cards))["atlas"]
        self.assertEqual((r["state"], r["waits_on"], r["group"]), ("blocked", "b", "stuck"))
        cards[1]["status"] = "done"
        self.assertEqual(self.by(self.rows(cards))["atlas"]["state"], "working")

    def test_the_five_counts_and_how_old_the_oldest_is(self):
        cards = [card("a", "echo", updated=14, needs_input=True), card("n", "nova", updated=22, review=True), card("w", "bolt", updated=2),
                 card("s", "scribe", updated=41)]
        c = self.rows(cards)["counts"]
        self.assertEqual({g: c[g]["n"] for g in c}, {"you": 1, "stuck": 1, "others": 1, "working": 1, "idle": 1})   # kite is the roster's idle one
        self.assertEqual((c["you"]["oldest_min"], c["stuck"]["oldest_min"], c["others"]["oldest_min"]), (14, 41, 22))
        self.assertIsNone(c["idle"]["oldest_min"])

    def test_attention_first_you_then_stuck_then_others_then_working_then_idle(self):
        cards = [card("w", "a-work", updated=1), card("a", "z-asks", updated=5, needs_input=True), card("s", "m-silent", updated=40), card("r", "r-review", updated=7, review=True)]
        self.assertEqual([r["name"] for r in self.rows(cards)["agents"]], ["z-asks", "m-silent", "r-review", "a-work", "kite"])

    def test_a_sleep_shows_and_keeps_the_agent_out_of_stuck(self):
        w = [(NOW - timedelta(minutes=190), NOW - timedelta(minutes=65))]
        st = self.rows([card(updated=200)], asleep=w)
        self.assertEqual(self.by(st)["atlas"]["state"], "silent")
        self.assertEqual(st["asleep"]["minutes"], 125)
        self.assertIsNone(self.rows([card(updated=200)])["asleep"])


class TheWiring(unittest.TestCase):
    def setUp(self):
        import http.client
        from http.server import ThreadingHTTPServer
        from agentboard import server
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store, 0))
        self.port = probe.server_address[1]
        probe.server_close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.http = http.client

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def hud(self):
        c = self.http.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request("GET", "/api/hud", headers={"Host": f"localhost:{self.port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def test_api_hud_carries_the_status_block_and_the_agents_quiet_minutes(self):
        self.store.start("Refactor", "atlas", task_id="r1")
        code, data = self.hud()
        self.assertEqual(code, 200)
        self.assertEqual(sorted(data["status"]), ["agents", "asleep", "counts"])
        self.assertEqual([r["name"] for r in data["status"]["agents"]], ["atlas"])
        self.assertEqual(data["status"]["counts"]["working"]["n"], 1)
        self.assertIn("quiet_min", data["agents"][0])

    def test_a_board_that_slept_says_so_and_does_not_call_its_agents_abandoned(self):
        self.store.start("Refactor", "atlas", task_id="r1")
        data = self.store._read()
        data["tasks"][0]["updated"] = (datetime.now() - timedelta(hours=4)).strftime(FMT)   # untouched for four hours ...
        self.store._write(data)
        (self.store.dir / awake.HEART).write_text(json.dumps({"last": (datetime.now() - timedelta(hours=3, minutes=50)).strftime(FMT)}))   # ... and the board was away for 3 h 50
        code, data = self.hud()
        self.assertEqual(code, 200)
        self.assertEqual(data["agents"][0]["state"], "working")   # ten awake minutes, not four hours
        self.assertEqual(data["status"]["agents"][0]["state"], "working")
        self.assertTrue(data["status"]["asleep"]["open"])
        self.assertGreaterEqual(data["status"]["asleep"]["minutes"], 229)

    def test_the_server_ticks_the_board_s_sleep_whether_or_not_insights_is_on(self):
        src = (Path(status.__file__).parent / "server.py").read_text()
        self.assertIn("awake.tick(store.dir)", src[src.index("def _states():"):src.index("threading.Thread(target=_states")])


if __name__ == "__main__":
    unittest.main()
