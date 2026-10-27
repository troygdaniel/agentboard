"""Troy's reporting rule (one sentence, action first) in every prompt, and answering an agent on its card."""
import contextlib
import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, prompt, runs
from agentboard.store import BoardError, Store

RULE = "Report to Troy in one sentence, one idea: the ACTION he must take first, then one fact."
OFFER = "If more is unavoidable, one sentence, then offer the detail."


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

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()


class PromptTests(Base):
    def prompt_for(self, task_id):
        text, _ = prompt.build_prompt(Store.get(self.s.load(), task_id), self.s.dir, tasks=self.s.load())
        return text

    def test_every_kind_of_card_prompt_ends_with_the_rule(self):
        self.s.add("Plain card", status="todo")
        self.s.add("Parent card", status="todo")
        self.s.claim("parent-card", "alice")
        self.s.add("Child card", parent_id="parent-card")
        for card in ("plain-card", "parent-card", "child-card"):
            text = self.prompt_for(card)
            self.assertIn(RULE, text, card)
            self.assertIn(OFFER, text, card)
            self.assertIn("so Troy answers you there", text, card)
            tail = text.rstrip().splitlines()[-4:]
            self.assertTrue(any("Reporting to Troy" in t for t in text.splitlines()[-9:]), card)   # the rule closes the prompt
            self.assertNotIn("3 lines", " ".join(tail))

    def test_the_prompt_says_how_to_read_troys_answer(self):
        self.s.add("Plain card", status="todo")
        text = self.prompt_for("plain-card")
        self.assertIn("answer plain-card --wait", text)

    def test_the_run_prompt_carries_it_and_drops_the_old_three_line_form(self):
        self.s.add("Plain card", status="todo")
        text = runs.build_run_prompt(Store.get(self.s.load(), "plain-card"), self.s.dir, self.s.load(), "RUN-1", 2, 10)
        self.assertEqual(text.count(RULE), 2)   # the card prompt's closing section and the run rules
        self.assertNotIn("ACTION (who must do what next)", text)

    def test_the_instructions_snippet_carries_it(self):
        self.assertIn("Report to Troy in one sentence, one idea: the ACTION he must take first, then one fact.", cli.INSTRUCTIONS)
        self.assertIn("agentboard answer", cli.INSTRUCTIONS)

    def test_the_orch_prompt_starts_a_new_orch_right(self):
        text = prompt.build_orch_prompt(self.s.load(), self.s.dir, port=8765)
        for want in ("Agents report to Troy directly", "Speak to Troy only when he must act", "Daytime: Troy assigns", "sleep or nap", "Never without Troy's own words",
                     "deploy to production", "any number but Troy's mobile", "railway"):
            self.assertIn(want, text)
        self.assertIn(RULE, text)
        self.assertNotIn("Report to Troy in 3 lines", text)

    def test_a_custom_template_is_left_alone(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text('[prompt]\ntemplate = "Do {title} ({task_id})"\n')
        self.s.add("Mine", status="todo")
        self.assertEqual(self.prompt_for("mine"), "Do Mine (mine)")


class ReplyTests(Base):
    def test_a_reply_is_stored_on_the_card_and_read_with_answer(self):
        self.s.start("Ask me", "alice")
        self.s.ask("ask-me", "Retry 3 or 5?")
        self.assertIsNone(self.s.answer("ask-me"))
        self.s.reply("ask-me", "  five  ")
        self.assertEqual(self.s.answer("ask-me")["text"], "five")
        self.assertEqual(self.s.answer("ask-me")["by"], "Troy")
        self.assertTrue(Store.get(self.s.load(), "ask-me")["needs_input"])       # replying changes no state
        self.assertEqual(self.cli("answer", "ask-me").strip(), "five")

    def test_the_reply_is_cleared_when_the_agent_moves_on(self):
        for step in ("update", "ask", "review", "claim"):
            with self.subTest(step):
                self.s.start(f"Card {step}", "alice")
                cid = f"card-{step}"
                self.s.ask(cid, "q?")
                self.s.reply(cid, "go ahead")
                {"update": lambda: self.s.update(cid, 50, "on it"), "ask": lambda: self.s.ask(cid, "another?"),
                 "review": lambda: self.s.review(cid, "done"), "claim": lambda: self.s.claim(cid, "bob", force=True)}[step]()
                self.assertIsNone(self.s.answer(cid))

    def test_answer_without_a_reply_fails_and_wait_times_out(self):
        self.s.start("Quiet", "alice")
        with self.assertRaises(SystemExit) as e:
            self.cli("answer", "quiet")
        self.assertIn("no reply", str(e.exception))
        with self.assertRaises(SystemExit):
            self.cli("answer", "quiet", "--wait", "--timeout", "0.3", "--interval", "0.1")

    def test_answer_wait_returns_as_soon_as_troy_replies(self):
        self.s.start("Waiting", "alice")
        self.s.ask("waiting", "which one?")
        threading.Timer(0.4, lambda: self.s.reply("waiting", "the second")).start()
        t0 = time.time()
        out = self.cli("answer", "waiting", "--wait", "--timeout", "10", "--interval", "0.1")
        self.assertEqual(out.strip(), "the second")
        self.assertLess(time.time() - t0, 5)

    def test_an_empty_reply_is_refused(self):
        self.s.start("Card", "alice")
        with self.assertRaises(BoardError):
            self.s.reply("card", "   ")


if __name__ == "__main__":
    unittest.main()


class KeepItSimpleTests(Base):
    def card(self):
        self.s.add("Task", status="todo")
        t = self.s.load()[0]
        self.s.claim(t["id"], "A")
        return t["id"]

    def test_orch_prompt_has_the_named_block_and_copy_order(self):
        text = prompt.build_orch_prompt(self.s.load(), self.s.dir)
        self.assertIn("## Keep it simple", text)
        self.assertIn("One sentence, one idea: what Troy should do or reply.", text)
        self.assertIn("into every card description and every assignment you write", text)
        self.assertIn("You speak to Troy the same way.", text)

    def test_every_prompt_says_detail_goes_in_body(self):
        tid = self.card()
        text, _ = prompt.build_prompt(self.s.get(self.s.load(), tid), self.s.dir, tasks=self.s.load())
        self.assertIn("never in the first line", text)
        self.assertIn("never in the first line", runs.RUN_TEMPLATE if hasattr(runs, "RUN_TEMPLATE") else open(runs.__file__).read())

    def test_multiline_review_splits_sentence_and_details(self):
        tid = self.card()
        self.s.review(tid, "Merge it.\nTests pass.\nTouched three files.")
        t = self.s.get(self.s.load(), tid)
        self.assertEqual(t["result"], "Merge it.")
        self.assertEqual(t["body_md"], "Tests pass.\nTouched three files.")

    def test_ask_and_update_take_a_first_line_plus_body(self):
        tid = self.card()
        self.s.ask(tid, "Pick A or B?\nA is faster.", "B is safer.")
        t = self.s.get(self.s.load(), tid)
        self.assertEqual(t["question"], "Pick A or B?")
        self.assertEqual(t["body_md"], "A is faster.\n\nB is safer.")
        self.s.update(tid, 40, "Going with B", body_md="Because safer.")
        t = self.s.get(self.s.load(), tid)
        self.assertEqual((t["status_text"], t["body_md"]), ("Going with B", "Because safer."))
        self.s.update(tid, 50, "Next")
        self.assertNotIn("body_md", self.s.get(self.s.load(), tid))

    def test_cli_body_flag_on_update(self):
        tid = self.card()
        self.cli("update", tid, "30", "Reading", "--body", "Long notes")
        self.assertEqual(self.s.get(self.s.load(), tid)["body_md"], "Long notes")

    def test_card_list_carries_details_for_the_fold(self):
        from agentboard import server
        tid = self.card()
        self.s.review(tid, "Done.\nMore here.")
        src = open(server.__file__).read()
        self.assertIn('d["details"]', src)
        html = (Path(server.__file__).parent / "static" / "index.html").read_text()
        self.assertIn('<details class="fold"><summary>Details</summary>', html)
        self.assertIn("${saidRow}${foldRow}", html)
