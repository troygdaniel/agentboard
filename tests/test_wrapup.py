"""The end-of-day wrap-up (Nov 12): `agentboard checkpoint` is an agent's hand-off note on a card it holds; `agentboard wrapup` sorts every
Doing card into finish / needs / carry / running, nudges agents for what they owe (`--ask`), releases the carry cards best first and saves the
page (`--apply`); the ORCH drawer has an End of day button that sends ORCH one line."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import cli, listeners, prompt, wrapup
from agentboard.store import Store

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
REPO = Path(cli.__file__).parents[2]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def doing(self, id_, agent, pct=40, text="working"):
        self.s.add(id_, task_id=id_, status="todo")
        self.s.claim(id_, agent)
        self.s.update(id_, pct, text)
        return id_

    def get(self, id_):
        return next(t for t in self.s.load() if t["id"] == id_)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def refuses(self, *argv):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.cli(*argv)


class Checkpoint(Base):
    def test_it_writes_the_note_and_the_account_without_moving_the_card(self):
        self.doing("a", "AGENT-1", 60)
        self.s.checkpoint("a", "header parsed · next the trailer", body_md="- header is 12 bytes", by="AGENT-1")
        t = self.get("a")
        self.assertEqual((t["status"], t["progress"], t["agent"]), ("doing", 60, "AGENT-1"))
        self.assertEqual(t["status_text"], "header parsed · next the trailer")
        self.assertEqual(t["body_md"], "- header is 12 bytes")
        self.assertTrue(t["checkpoint_at"])
        self.assertEqual(t["log"][-1]["text"], "Checkpoint: header parsed · next the trailer")

    def test_a_release_keeps_it_as_what_was_learned_and_the_marker_goes(self):
        self.doing("a", "AGENT-1", 60)
        self.s.checkpoint("a", "header parsed · next the trailer", body_md="- trailer is optional", by="AGENT-1")
        self.s.move("a", "todo")
        t = self.get("a")
        self.assertNotIn("checkpoint_at", t)
        self.assertEqual(t["learned"]["status"], "header parsed · next the trailer")
        self.assertIn("trailer is optional", t["learned"]["notes"])

    def test_only_the_holder_orch_or_the_owner_may_and_only_on_a_doing_card_with_nothing_asked(self):
        self.doing("a", "AGENT-1")
        with self.assertRaisesRegex(Exception, "held by AGENT-1"):
            self.s.checkpoint("a", "x", by="AGENT-2")
        self.s.checkpoint("a", "by orch", by="ORCH")
        self.s.add("q", task_id="q", status="todo")
        with self.assertRaisesRegex(Exception, "not doing"):
            self.s.checkpoint("q", "x")
        self.s.claim("q", "AGENT-1"); self.s.ask("q", "Which one?")
        with self.assertRaisesRegex(Exception, "waiting on"):
            self.s.checkpoint("q", "x")
        with self.assertRaisesRegex(Exception, "say where it stands"):
            self.s.checkpoint("a", "   ")

    def test_the_cli_and_a_second_claim_start_clean(self):
        self.doing("a", "AGENT-1")
        os.environ["AGENTBOARD_NAME"] = "AGENT-1"
        self.assertIn("checkpoint saved at 40%", self.cli("checkpoint", "a", "done · next · learned"))
        self.s.move("a", "todo"); self.s.claim("a", "AGENT-2")
        self.assertNotIn("checkpoint_at", self.get("a"))


class Sorting(Base):
    def setUp(self):
        super().setUp()
        self.doing("close", "AGENT-1", 100)
        self.doing("asks", "AGENT-2", 10); self.s.ask("asks", "Rotate now?")
        self.doing("rev", "AGENT-3", 90); self.s.review("rev", "Shipped")
        self.doing("low", "AGENT-4", 20, "early days")
        self.doing("high", "AGENT-5", 70, "nearly there")
        self.doing("live", "AGENT-6", 50, "busy now")

    def ids(self, p, k):
        return [c["id"] for c in p[k]]

    def test_each_doing_card_lands_in_one_outcome(self):
        p = wrapup.plan(self.s)
        self.assertEqual(self.ids(p, "finish"), ["close"])
        self.assertEqual(sorted(self.ids(p, "needs")), ["asks", "rev"])
        self.assertEqual(sorted(self.ids(p, "carry")), ["high", "live", "low"])
        self.assertEqual(p["running"], [])

    def test_a_listening_agent_with_a_recent_update_is_left_running_unless_all_is_asked(self):
        with mock.patch.object(listeners, "listening", return_value={"AGENT-6": {"since": "", "what": "", "sessions": 1}}):
            p = wrapup.plan(self.s)
            self.assertEqual(self.ids(p, "running"), ["live"])
            self.assertNotIn("live", self.ids(p, "carry"))
            self.assertEqual(self.ids(wrapup.plan(self.s, include_running=True), "carry").count("live"), 1)

    def test_tomorrow_starts_with_the_card_nearest_done_and_a_checkpoint_beats_none(self):
        self.doing("tie-a", "AGENT-7", 70)
        self.doing("tie-b", "AGENT-8", 70)
        self.s.checkpoint("tie-b", "where it stands", by="AGENT-8")
        order = self.ids(wrapup.plan(self.s), "carry")
        self.assertEqual(order[0], "tie-b")                          # 70% first, the checkpointed one ahead of the others at 70% ...
        self.assertEqual(set(order[1:3]), {"high", "tie-a"})         # (their own order is by how recently each was touched: not asserted, a minute can tick between them)
        self.assertEqual(order[-2:], ["live", "low"])                # ... then 50%, 20%

    def test_the_first_sentence_says_the_one_thing_to_do_first(self):
        p = wrapup.plan(self.s)
        self.assertEqual(wrapup.first_move(p), "Answer or sign off 2 cards waiting on you; 3 more go back to Todo tonight.")

    def test_with_nothing_waiting_on_a_person_it_asks_for_the_missing_checkpoints_then_says_go(self):
        s = Store(Path(self.tmp.name) / ".agentboard2")
        for i, a in enumerate(("AGENT-1", "AGENT-2")):
            s.add(f"c{i}", task_id=f"c{i}", status="todo"); s.claim(f"c{i}", a); s.update(f"c{i}", 40, "x")
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(s.dir)}):
            self.assertEqual(wrapup.first_move(wrapup.plan(s)), "Run `agentboard wrapup --ask` so 2 agents leave a checkpoint; 2 cards go back to Todo tonight.")
            for i, a in enumerate(("AGENT-1", "AGENT-2")):
                s.checkpoint(f"c{i}", "where it stands", by=a)
            self.assertEqual(wrapup.first_move(wrapup.plan(s)), "Say go and ORCH runs `agentboard wrapup --apply`: 2 cards go back to Todo with their notes.")

    def test_done_today_carries_the_learned_lines(self):
        self.doing("shipped", "AGENT-9", 100)
        self.s.review("shipped", "Shipped", body_md="## Learned\n- the cache key needs the tenant id")
        self.s.move("shipped", "done")
        d = wrapup.plan(self.s)["done_today"]
        self.assertEqual((d[0]["id"], d[0]["learned"]), ("shipped", ["the cache key needs the tenant id"]))
        self.assertEqual(wrapup.plan(self.s, now=datetime.now() + timedelta(days=1))["done_today"], [])   # tomorrow it is yesterday's


class AskAndApply(Base):
    def test_ask_leaves_one_note_per_card_that_owes_something_and_never_two(self):
        self.doing("carry", "AGENT-1", 40)
        self.doing("fin", "AGENT-2", 100)
        self.doing("held", "AGENT-3", 30); self.s.checkpoint("held", "where it stands", by="AGENT-3")
        sent = wrapup.ask(self.s, wrapup.plan(self.s), ab="agentboard")
        self.assertEqual(sorted(sent), [("carry", "AGENT-1"), ("fin", "AGENT-2")])
        self.assertIn("agentboard checkpoint carry", self.get("carry")["reply"]["text"])
        self.assertTrue(self.get("carry")["reply"]["text"].startswith("End of day:"))
        self.assertEqual(self.get("carry")["reply"]["by"], "ORCH")
        self.assertIn("review fin", self.get("fin")["reply"]["text"])
        self.assertIn("## Learned", self.get("fin")["reply"]["text"])
        self.assertNotIn("reply", self.get("held"))                                          # it already handed off
        self.assertEqual(wrapup.ask(self.s, wrapup.plan(self.s), ab="agentboard"), [])       # the unread note is not repeated

    def test_apply_releases_best_first_keeps_what_is_waiting_and_saves_the_page(self):
        self.doing("low", "AGENT-1", 20); self.doing("high", "AGENT-2", 80); self.doing("mid", "AGENT-3", 50)
        self.doing("asks", "AGENT-4", 10); self.s.ask("asks", "Which?")
        self.s.add("old todo", task_id="old", status="todo")
        order, path = wrapup.apply(self.s, wrapup.plan(self.s))
        self.assertEqual(order, ["high", "mid", "low"])
        self.assertEqual([t["id"] for t in self.s.load() if t["status"] == "todo"], ["high", "mid", "low", "old"])   # the best on top, the old card after
        self.assertEqual(self.get("asks")["status"], "doing")                                # waiting on the owner: stays
        self.assertEqual(self.get("high")["learned"]["progress"], 80)                        # and each keeps what it had learned
        text = path.read_text()
        self.assertEqual(path.parent, self.s.dir / "wrapups")
        self.assertIn("· wrapped", text.splitlines()[0])
        self.assertIn("1. high (AGENT-2) 80%", text)
        self.assertEqual(wrapup.last(self.s), path)

    def test_the_cli_plan_is_read_only_and_apply_and_last_work(self):
        self.doing("a", "AGENT-1", 60)
        out = self.cli("wrapup")
        self.assertIn("## Back in Todo tonight, start here tomorrow (1)", out)
        self.assertEqual(self.get("a")["status"], "doing")                                   # nothing moved
        self.assertIn("1 card(s) back in Todo, best first: a", self.cli("wrapup", "--apply"))
        self.assertEqual(self.get("a")["status"], "todo")
        self.assertIn("· wrapped", self.cli("wrapup", "--last"))

    def test_last_says_so_when_nothing_was_saved(self):
        self.assertIn("no wrap-up saved yet", self.cli("wrapup", "--last"))

    def test_the_page_runs_finished_waiting_carry_running_then_next(self):
        self.doing("a", "AGENT-1", 60); self.doing("q", "AGENT-2", 10); self.s.ask("q", "Which?")
        heads = re.findall(r"^## (.+)$", wrapup.render(wrapup.plan(self.s)), re.M)
        self.assertEqual(heads, ["Finished today (0)", "Waiting on the owner (1), stays where it is", "Back in Todo tonight, start here tomorrow (1)", "Next"])


class TheProtocolAndThePage(unittest.TestCase):
    def test_agents_and_orch_are_told_how(self):
        self.assertIn("## End of day", cli.INSTRUCTIONS)
        self.assertIn('agentboard checkpoint "$ID" "<done so far · the next step · what you learned>"', cli.INSTRUCTIONS)
        self.assertIn("## End of day", (REPO / "CLAUDE.md").read_text())
        orch = prompt.ORCH_TEMPLATE
        self.assertIn("## End of day", orch)
        self.assertIn("`{ab} wrapup --ask`", orch)
        self.assertIn("Release nothing until {owner} says go.", orch)

    def test_the_drawer_has_an_end_of_day_button_that_sends_orch_one_line(self):
        self.assertIn('id="eod-btn"', PAGE)
        self.assertIn("body.no-dispatch #eod-btn { display: none; }", PAGE)
        self.assertIn("await api('/api/chat', { text: EOD_TEXT, to: 'ORCH' });", PAGE)
        text = re.search(r"const EOD_TEXT = '(.*?)';", PAGE).group(1)
        self.assertTrue(text.startswith("End of day. Run `agentboard wrapup`"))
        self.assertIn("Release nothing until I say go.", text)


if __name__ == "__main__":
    unittest.main()
