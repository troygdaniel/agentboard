"""The night queue (card retro-night-queue, docs/night-queue-design.md): a board-wide switch that is off until the owner or ORCH turns it on, an ordered
queue only they edit, and `night next`, which an agent with a free hand uses to claim the first ready card itself. Nothing here reaches the network."""
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, night, server
from agentboard.store import BoardError, Store

NOON = datetime(2026, 11, 15, 12, 0, 0)
LATE = datetime(2026, 11, 15, 23, 30, 0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(self.root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(self.root / "proj" / ".agentboard")
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)

    def card(self, title, **kw):
        return self.s.add(title, status=kw.pop("status", "todo"), **kw)["id"]

    def run_cli(self, *argv, name=None):
        out = io.StringIO()
        env = {"AGENTBOARD_NAME": name} if name else {}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        if isinstance(code, str):   # a refusal: the interpreter would print it to stderr and exit 1
            out.write(code + "\n")
            code = 1
        return code, out.getvalue()

    def on(self, until="23:59", now=NOON):
        return night.turn_on(self.s, until, now=now)


class Switch(Base):
    def test_off_by_default_and_reading_it_writes_nothing(self):
        self.card("Calm the star field")   # a board with a card in it, so tasks.json exists
        st = night.status(self.s, NOON)
        self.assertEqual((st["on"], st["ended"], st["queue"], st["until"]), (False, False, [], None))
        self.assertFalse(night.path(self.s.dir).exists())
        self.assertNotIn("night", json.loads(self.s.path.read_text()))   # tasks.json has no new key: a board that never uses it is the board it was

    def test_it_ends_by_itself_at_until_and_the_next_one_is_tomorrow_when_the_time_has_passed(self):
        self.assertEqual(night.parse_until("08:00", NOON), datetime(2026, 11, 16, 8, 0))
        self.assertEqual(night.parse_until("23:59", NOON), datetime(2026, 11, 15, 23, 59))
        self.assertEqual(night.parse_until(None, NOON), datetime(2026, 11, 16, 8, 0))   # the default
        self.on("23:59")
        self.assertTrue(night.status(self.s, LATE)["on"])
        after = datetime(2026, 11, 16, 0, 1)
        st = night.status(self.s, after)
        self.assertEqual((st["on"], st["ended"]), (False, True))
        self.assertFalse(night.active(self.s.dir, after)[0])

    def test_a_bad_time_is_refused_with_the_fix(self):
        for bad in ("25:00", "8", "noon", "07:60", ""):
            if bad == "":
                continue   # an empty --until is the default
            with self.assertRaises(BoardError) as cm:
                night.turn_on(self.s, bad, now=NOON)
            self.assertIn("a time of day like 07:30", str(cm.exception))
        self.assertFalse(night.path(self.s.dir).exists())

    def test_a_change_posts_one_line_and_the_same_state_posts_nothing(self):
        self.card("Calm the star field")
        night.queue_add(self.s, ["calm-the-star-field"])
        self.on()
        lines = [m["text"] for m in self.s.chat_list()]
        self.assertEqual(len(lines), 1)
        self.assertIn("night mode is on until 23:59: 1 card queued", lines[0])
        self.assertIn("no push, no spend, no live restarts, no personal cards", lines[0])
        self.on()   # on again: nothing new
        self.assertEqual(len(self.s.chat_list()), 1)
        night.turn_off(self.s, now=NOON)
        self.assertEqual(len(self.s.chat_list()), 2)
        self.assertIn("night mode is off", self.s.chat_list()[-1]["text"])
        night.turn_off(self.s, now=NOON)   # off again: nothing new
        self.assertEqual(len(self.s.chat_list()), 2)

    def test_only_orch_or_the_owner_runs_the_switch_and_the_queue(self):
        self.card("Calm the star field")
        for who in ("DreamBot", "AGENT-2"):
            with self.assertRaises(BoardError) as cm:
                night.turn_on(self.s, "23:59", by=who, now=NOON)
            self.assertIn("only ORCH or the owner", str(cm.exception))
            with self.assertRaises(BoardError):
                night.queue_add(self.s, ["calm-the-star-field"], by=who)
            with self.assertRaises(BoardError):
                night.turn_off(self.s, by=who, now=NOON)
        night.queue_add(self.s, ["calm-the-star-field"], by="ORCH")     # ORCH, in any case
        night.turn_on(self.s, "23:59", by="orch", now=NOON)
        night.turn_off(self.s, by="you", now=NOON)                      # the owner by name
        night.turn_on(self.s, "23:59", by=None, now=NOON)               # a terminal with no session name


class Queue(Base):
    def test_only_a_todo_card_nobody_holds_can_be_queued_in_the_order_given(self):
        a, b, c = self.card("Alpha"), self.card("Bravo"), self.card("Charlie")
        self.assertEqual(night.queue_add(self.s, [a, b]), [a, b])
        night.queue_add(self.s, [c, a])                          # a is already there: it keeps its place
        self.assertEqual([r["id"] for r in night.status(self.s, NOON)["queue"]], [a, b, c])
        night.queue_add(self.s, [c], first=True)                 # --first moves it to the front
        self.assertEqual([r["id"] for r in night.status(self.s, NOON)["queue"]], [c, a, b])
        night.queue_remove(self.s, [a])
        self.assertEqual([r["id"] for r in night.status(self.s, NOON)["queue"]], [c, b])
        night.queue_clear(self.s)
        self.assertEqual(night.status(self.s, NOON)["queue"], [])

    def test_refusals_say_why(self):
        held = self.card("Held")
        self.s.claim(held, "AGENT-1")
        parent = self.card("Parent")
        sub = self.s.add("A step", parent_id=parent)["id"]
        backlog = self.s.add("Backlog one", status="backlog")["id"]
        for bad in (held, sub, backlog):
            with self.assertRaises(BoardError) as cm:
                night.queue_add(self.s, [bad])
            self.assertIn("only a Todo card nobody holds", str(cm.exception))
        with self.assertRaises(BoardError) as cm:
            night.queue_add(self.s, ["no-such-card"])
        self.assertIn("no such card", str(cm.exception))
        self.assertFalse(night.path(self.s.dir).exists())   # a refused add leaves nothing behind

    def test_a_blocked_card_is_queued_listed_blocked_and_skipped_until_its_blocker_is_done(self):
        first = self.card("First")
        second = self.card("Second", blocked_by=[first])
        night.queue_add(self.s, [second, first])
        rows = night.status(self.s, NOON)["queue"]
        self.assertEqual([(r["id"], r["ready"], r["blocked_by"]) for r in rows], [(second, False, [first]), (first, True, [])])
        self.on()
        got = night.take(self.s, "AGENT-1", now=NOON)
        self.assertEqual((got["card"]["id"], got["blocked"], got["left"]), (first, [second], 1))   # the blocked one waits, the next ready one goes
        self.s.review(first, "done")
        self.s.move(first, "done")
        got = night.take(self.s, "AGENT-2", now=NOON)
        self.assertEqual(got["card"]["id"], second)

    def test_cards_that_stop_waiting_drop_out_of_the_list(self):
        a, b = self.card("Alpha"), self.card("Bravo")
        night.queue_add(self.s, [a, b])
        self.s.claim(a, "AGENT-1")                               # claimed some other way
        self.assertEqual([r["id"] for r in night.status(self.s, NOON)["queue"]], [b])


class Take(Base):
    def test_it_refuses_when_night_is_off_or_ended(self):
        self.card("Alpha")
        night.queue_add(self.s, ["alpha"])
        with self.assertRaises(BoardError) as cm:
            night.take(self.s, "AGENT-1", now=NOON)
        self.assertEqual(str(cm.exception), "night mode is off: take only the cards ORCH assigns")
        self.on("23:59")
        with self.assertRaises(BoardError) as cm:
            night.take(self.s, "AGENT-1", now=datetime(2026, 11, 16, 0, 5))
        self.assertIn("night mode ended at 23:59", str(cm.exception))
        self.assertEqual(self.s.get(self.s.load(), "alpha")["status"], "todo")   # nothing was claimed

    def test_it_claims_the_first_ready_card_as_claim_does(self):
        a, b = self.card("Alpha"), self.card("Bravo")
        night.queue_add(self.s, [b, a])
        self.on()
        got = night.take(self.s, "AGENT-1", now=NOON)
        t = self.s.get(self.s.load(), b)
        self.assertEqual((got["card"]["id"], got["left"], got["blocked"]), (b, 1, []))
        self.assertEqual((t["status"], t["agent"]), ("doing", "AGENT-1"))
        log = " | ".join(x["text"] if isinstance(x, dict) else str(x) for x in t["log"])
        self.assertIn("Claimed by AGENT-1", log)
        self.assertIn("Taken from the night queue", log)
        self.assertEqual([r["id"] for r in night.status(self.s, NOON)["queue"]], [a])   # it left the queue

    def test_an_agent_with_an_unfinished_card_is_told_to_hand_it_in_first(self):
        self.card("Alpha")
        self.card("Bravo")
        night.queue_add(self.s, ["alpha", "bravo"])
        self.on()
        night.take(self.s, "AGENT-1", now=NOON)
        with self.assertRaises(BoardError) as cm:
            night.take(self.s, "agent-1", now=NOON)              # the name is not case-sensitive
        self.assertIn("you hold alpha: hand it in with review first", str(cm.exception))
        self.s.review("alpha", "done")                           # handed in: its holder is free
        self.assertEqual(night.take(self.s, "AGENT-1", now=NOON)["card"]["id"], "bravo")

    def test_a_card_waiting_on_an_answer_does_not_hold_its_agent(self):
        self.card("Alpha")
        self.card("Bravo")
        night.queue_add(self.s, ["alpha", "bravo"])
        self.on()
        night.take(self.s, "AGENT-1", now=NOON)
        self.s.ask("alpha", "which one?")
        self.assertEqual(night.take(self.s, "AGENT-1", now=NOON)["card"]["id"], "bravo")

    def test_nothing_ready_is_none_not_an_error(self):
        self.on()
        self.assertIsNone(night.take(self.s, "AGENT-1", now=NOON))
        self.card("Alpha", blocked_by=[self.card("Bravo")])
        night.queue_add(self.s, ["alpha"])
        self.assertIsNone(night.take(self.s, "AGENT-1", now=NOON))   # only a blocked card is left
        self.assertEqual([r["id"] for r in night.status(self.s, NOON)["queue"]], ["alpha"])   # and it stays queued

    def test_two_agents_at_once_never_take_the_same_card(self):
        ids = [self.card(f"Card {n}") for n in range(2)]
        night.queue_add(self.s, ids)
        self.on()
        results, barrier = {}, threading.Barrier(2)

        def go(who):
            barrier.wait()
            results[who] = night.take(Store(self.s.dir), who, now=NOON)
        ts = [threading.Thread(target=go, args=(w,)) for w in ("AGENT-1", "AGENT-2")]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(sorted(r["card"]["id"] for r in results.values()), sorted(ids))   # one each, no card twice

    def test_one_card_two_takers_exactly_one_gets_it(self):
        night.queue_add(self.s, [self.card("Only")])
        self.on()
        results, barrier = {}, threading.Barrier(2)

        def go(who):
            barrier.wait()
            results[who] = night.take(Store(self.s.dir), who, now=NOON)
        ts = [threading.Thread(target=go, args=(w,)) for w in ("AGENT-1", "AGENT-2")]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(sorted(r is None for r in results.values()), [False, True])


class Commands(Base):
    def test_the_whole_night_from_the_terminal(self):
        self.card("Calm the star field")
        self.card("Mark unknown galaxies")
        code, out = self.run_cli("night", "status")
        self.assertEqual(code, None)
        self.assertIn("night mode is off (0 queued", out)
        code, out = self.run_cli("night", "next", "--name", "AGENT-1")
        self.assertIn("night mode is off: take only the cards ORCH assigns", out)
        self.assertEqual(code, 1)
        code, out = self.run_cli("night", "queue", "add", "calm-the-star-field", "mark-unknown-galaxies", name="DreamBot")
        self.assertEqual(code, 1)
        self.assertIn("only ORCH or the owner", out)
        code, out = self.run_cli("night", "queue", "add", "calm-the-star-field", "mark-unknown-galaxies", name="ORCH")
        self.assertIn("queued calm-the-star-field, mark-unknown-galaxies", out)
        self.assertIn("  2  mark-unknown-galaxies  Mark unknown galaxies", out)
        code, out = self.run_cli("night", "queue")                       # no word lists it
        self.assertIn("night mode is off (2 queued", out)
        code, out = self.run_cli("night", "on", "--until", "23:59", name="ORCH")
        self.assertIn("night mode is on until 23:59 (2 queued)", out)
        code, out = self.run_cli("night", "next", "--name", "AGENT-1")
        self.assertIn("took calm-the-star-field: Calm the star field", out)
        self.assertIn("no push, no spend, no live restarts, no personal cards", out)
        self.assertIn("add at least two now", out)                       # the same nudge a claim gives
        self.assertIn("read it with: agentboard prompt calm-the-star-field   (1 left in the queue)", out)
        code, out = self.run_cli("night", "next", "--name", "AGENT-1")
        self.assertEqual(code, 1)
        self.assertIn("you hold calm-the-star-field", out)
        code, out = self.run_cli("night", "next", "--name", "AGENT-2")
        self.assertIn("took mark-unknown-galaxies", out)
        self.assertIn("the queue is now empty", out)
        code, out = self.run_cli("night", "next", "--name", "AGENT-3")
        self.assertEqual(code, 1)
        self.assertIn("the night queue is empty, or every card in it is blocked", out)
        code, out = self.run_cli("night", "off", name="ORCH")
        self.assertIn("night mode is off", out)

    def test_a_bad_until_is_one_plain_line(self):
        code, out = self.run_cli("night", "on", "--until", "7pm", name="ORCH")
        self.assertEqual((code, out), (1, "agentboard: --until takes a time of day like 07:30, not '7pm'\n"))


class Routes(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_the_page_reads_the_state_and_flips_the_switch_but_never_the_queue(self):
        self.card("Calm the star field")
        night.queue_add(self.s, ["calm-the-star-field"])
        st = self.get("/api/night")
        self.assertEqual((st["on"], st["until"], st["ended"]), (False, None, False))
        self.assertEqual(st["queue"], [{"id": "calm-the-star-field", "title": "Calm the star field", "blocked_by": [], "ready": True}])
        st = self.post("/api/night", {"on": True, "until": "23:59"})
        self.assertTrue(st["on"])
        self.assertTrue(self.get("/api/night")["on"])
        self.assertFalse(self.post("/api/night", {"on": False})["on"])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/night", {"on": True, "until": 7})
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/night", {"on": True, "until": "later"})
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()

    def test_the_state_carries_titles_and_ids_only(self):
        self.card("Calm the star field", description="a private note that must not leave the card")
        night.queue_add(self.s, ["calm-the-star-field"])
        raw = json.dumps(self.get("/api/night"))
        self.assertNotIn("private note", raw)


class Page(unittest.TestCase):
    HTML = (Path(cli.__file__).parent / "static" / "index.html").read_text()

    def test_the_chip_is_hidden_until_night_mode_is_on_and_the_row_sits_under_agent_chat(self):
        self.assertIn('<button class="ab-cfg ab-night" id="night-chip" type="button" hidden', self.HTML)
        pane = self.HTML[self.HTML.index('id="pane-agents"'):self.HTML.index('id="pane-security"')]
        self.assertLess(pane.index('id="cfg-agents"'), pane.index('id="cfg-night"'))
        self.assertLess(pane.index('id="cfg-night"'), pane.index('id="cfg-listen"'))

    def test_a_card_title_is_escaped_where_it_is_drawn(self):
        body = self.HTML[self.HTML.index("function renderNightPane()"):self.HTML.index("document.addEventListener('click', async e => {\n  const t = e.target.closest('[data-night]")]
        self.assertIn("esc(r.title)", body)
        self.assertNotIn("${r.title}", body)
        self.assertNotIn("innerHTML = r.title", body)


if __name__ == "__main__":
    unittest.main()
