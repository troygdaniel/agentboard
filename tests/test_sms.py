"""Text the board: fake Twilio requests only. Nothing here touches Twilio, the network beyond localhost, or a real board."""
import base64
import hashlib
import hmac
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import sms
from agentboard.store import BoardError, Store

TOKEN = "test-auth-token"
URL = "https://example.trycloudflare.com/sms"
MOBILE = "+14165550123"


def sign(params, token=TOKEN, url=URL):
    """Twilio's algorithm written out again here, independent of the module under test."""
    data = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        self.conf = {"allowed": [MOBILE], "public_url": URL, "token": TOKEN, "rate_per_hour": 30, "name": "Troy"}
        self.n = 0

    def params(self, body, sender=MOBILE, sid=None):
        self.n += 1
        return {"From": sender, "To": "+16475550100", "Body": body, "MessageSid": sid or f"SM{self.n:032d}"}

    def post(self, params, header=None, conf=None):
        form = {k: [v] for k, v in params.items()}
        return sms.handle_request(self.store, conf or self.conf, form, sign(params) if header is None else header)

    def titles(self, status):
        return [t["id"] for t in self.store.load() if t["status"] == status]


class SignatureTests(Base):
    def test_a_good_signature_passes_and_any_change_fails(self):
        p = {"From": MOBILE, "Body": "status", "MessageSid": "SM" + "1" * 32}
        form = {k: [v] for k, v in p.items()}
        self.assertEqual(sms.signature(TOKEN, URL, form), sign(p))
        self.assertTrue(sms.valid_signature(TOKEN, URL, form, sign(p)))
        self.assertFalse(sms.valid_signature(TOKEN, URL, {**form, "Body": ["done everything"]}, sign(p)))   # body tampered
        self.assertFalse(sms.valid_signature(TOKEN, URL + "x", form, sign(p)))                                # another URL
        self.assertFalse(sms.valid_signature("other-token", URL, form, sign(p)))
        self.assertFalse(sms.valid_signature(TOKEN, URL, form, ""))
        self.assertFalse(sms.valid_signature("", URL, form, sign(p, token="")))                                # no token configured: nothing passes

    def test_repeated_fields_are_sorted_like_twilio_does(self):
        form = {"B": ["2", "1"], "A": ["x"]}
        data = URL + "Ax" + "B1" + "B2"
        want = base64.b64encode(hmac.new(TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(sms.signature(TOKEN, URL, form), want)


class RefusalTests(Base):
    def test_a_bad_signature_changes_nothing_and_says_nothing(self):
        code, body, _ = self.post(self.params("add: sneaky"), header="AAAA")
        self.assertEqual((code, body), (403, b""))
        self.assertEqual(self.store.load(), [])

    def test_a_stranger_with_a_valid_signature_is_ignored_too(self):
        p = self.params("add: sneaky", sender="+15555550123")
        code, body, line = self.post(p)
        self.assertEqual((code, body), (403, b""))
        self.assertIn("not allowed", line)
        self.assertEqual(self.store.load(), [])

    def test_the_sender_may_be_written_any_way_in_the_allowlist(self):
        self.assertEqual(sms.e164("416-555-0123"), MOBILE)
        self.assertEqual(sms.e164("(416) 555 0123"), MOBILE)
        self.assertEqual(sms.e164("1 416 555 0123"), MOBILE)
        self.assertEqual(sms.e164("+14165550123"), MOBILE)
        self.assertNotIn(sms.e164("hello"), [MOBILE])

    def test_a_replayed_request_is_not_applied_twice(self):
        p = self.params("add: buy milk", sid="SM" + "a" * 32)
        self.assertEqual(self.post(p)[0], 200)
        code, body, line = self.post(p)                           # the exact same signed request again
        self.assertEqual(code, 200)
        self.assertIn(b"Already handled", body)
        self.assertIn("replay", line)
        self.assertEqual(self.titles("todo"), ["buy-milk"])
        self.assertTrue((self.store.dir / "sms-state.json").exists())

    def test_a_request_without_a_message_sid_is_refused(self):
        p = self.params("status")
        p.pop("MessageSid")
        self.assertEqual(self.post(p)[0], 403)

    def test_the_hourly_cap_stops_a_runaway(self):
        conf = {**self.conf, "rate_per_hour": 2}
        self.assertEqual(self.post(self.params("status"), conf=conf)[0], 200)
        self.assertEqual(self.post(self.params("status"), conf=conf)[0], 200)
        code, body, line = self.post(self.params("add: one too many"), conf=conf)
        self.assertIn(b"Too many", body)
        self.assertEqual(self.store.load(), [])
        self.assertEqual(sms.Seen(self.store.dir).check_and_record("SM" + "z" * 32, 2, now=time.time() + 7200), "ok")   # an hour later it works again


class CommandTests(Base):
    def say(self, text):
        code, body, _ = self.post(self.params(text))
        self.assertEqual(code, 200)
        return body.decode()

    def test_add_puts_a_new_card_on_top_of_todo_and_replies_with_its_id(self):
        self.store.add("Old one", status="todo")
        reply = self.say("add: buy toothpaste for dad")
        self.assertIn("buy-toothpaste-for-dad", reply)
        self.assertEqual(self.titles("todo"), ["buy-toothpaste-for-dad", "old-one"])
        self.assertIn("<Response><Message>", reply)

    def test_later_with_text_parks_an_idea(self):
        self.say("later: think about the garden")
        self.assertEqual(self.titles("backlog"), ["think-about-the-garden"])

    def test_move_commands_take_an_id_or_its_first_letters(self):
        self.store.add("Renew passports", status="todo")
        self.store.add("Renew licence", status="todo")
        self.assertIn("which one", self.say("start renew"))        # ambiguous: no change
        self.assertEqual(self.titles("doing"), [])
        self.assertIn("renew-passports: doing", self.say("start renew-p"))
        self.assertIn("ready for review", self.say("review renew-p"))
        self.assertTrue(Store.get(self.store.load(), "renew-passports")["review"])
        self.assertIn("renew-passports: done", self.say("done renew-passports"))
        self.assertEqual(self.titles("done"), ["renew-passports"])

    def test_todo_and_later_move_an_existing_card_between_columns(self):
        self.store.add("Idea", status="backlog")
        self.assertIn("idea: todo", self.say("todo idea"))
        self.assertIn("idea: later", self.say("later idea"))
        self.assertEqual(self.titles("backlog"), ["idea"])

    def test_status_is_one_short_line_that_names_what_needs_troy(self):
        self.store.add("A", status="todo")
        self.store.start("B", "alice")
        self.store.ask("b", "which port?")
        self.store.start("C", "bob")
        self.store.review("c", "done")
        reply = self.say("status")
        self.assertIn("2 doing, 1 need you, 1 to review, 1 todo", reply)
        self.assertIn("b", reply)
        self.assertNotIn("\n", reply)

    def test_help_is_one_sentence_and_a_lone_unknown_word_is_not_made_a_card(self):
        self.assertIn("Text a task to add it", self.say("help"))
        self.assertIn("Text a task to add it", self.say(""))
        self.assertIn("Don't know 'frobnicate'", self.say("frobnicate"))
        self.assertEqual(self.titles("todo"), [])

    def test_plain_words_become_a_card_on_top_of_todo(self):
        self.store.add("Old one", status="todo")
        reply = self.say("buy toothpaste for dad")
        self.assertIn("Added to Todo: buy-toothpaste-for-dad", reply)
        self.assertEqual(self.titles("todo"), ["buy-toothpaste-for-dad", "old-one"])

    def test_questions_are_not_turned_into_cards(self):
        self.say("what is the meaning of life?")
        self.assertEqual(self.titles("todo"), [])

    def test_whats_ready_names_the_cards_waiting_for_review(self):
        self.assertIn("Nothing is waiting", self.say("what's ready for review?"))
        self.store.start("Fix login", "alice")
        self.store.review("fix-login", "done")
        self.assertIn("Ready for review: fix-login", self.say("what's ready for review?"))
        self.assertIn("Ready for review: fix-login", self.say("ready"))

    def test_status_of_a_card_or_an_agent_is_one_line(self):
        self.store.start("Fix login", "alice")
        self.store.update("fix-login", 40, "halfway through the form")
        for q in ("status of fix-login", "how is fix login going?", "what's alice doing?", "alice status?"):
            r = self.say(q)
            self.assertIn("fix-login: 40% (alice), halfway through the form", r, q)
            self.assertNotIn("\n", r)
        self.assertIn("can't find", self.say("status of ghost"))

    def test_what_blocks_what(self):
        self.assertIn("Nothing is blocked", self.say("what's blocked?"))
        a = self.store.add("Build API", status="todo")
        self.store.add("Build UI", status="todo", blocked_by=[a["id"]])
        self.assertIn("build-ui waits on build-api", self.say("what blocks what?"))

    def test_what_changed_today_counts_starts_reviews_and_dones(self):
        self.assertIn("Nothing has moved today", self.say("what changed today?"))
        self.store.start("One", "alice")
        self.store.start("Two", "bob")
        self.store.review("two", "ok")
        self.assertIn("Today: 2 started, 1 sent to review, 0 done.", self.say("what changed today?"))

    def test_an_ask_can_be_answered_by_text_and_the_agent_reads_it(self):
        self.store.start("Pick limit", "alice")
        self.store.ask("pick-limit", "Retry limit: 3 or 5?")
        self.assertIn("pick-limit asks: Retry limit: 3 or 5?", self.say("what needs me?"))
        self.assertIn("Sent to alice on pick-limit.", self.say("reply 5"))
        self.assertEqual(self.store.answer("pick-limit")["text"], "5")
        self.assertEqual(self.store.answer("pick-limit")["by"], "Troy (text)")

    def test_a_bare_yes_answers_the_only_open_ask_but_is_a_normal_word_otherwise(self):
        self.say("yes")
        self.assertEqual(self.titles("todo"), [])   # nothing is asking: a lone word is not a card
        self.store.start("Pick limit", "alice")
        self.store.ask("pick-limit", "Go ahead?")
        self.assertIn("Sent to alice", self.say("yes"))
        self.assertEqual(self.store.answer("pick-limit")["text"], "yes")

    def test_with_two_asks_the_reply_must_name_one(self):
        self.store.start("One", "alice")
        self.store.ask("one", "a?")
        self.store.start("Two", "bob")
        self.store.ask("two", "b?")
        self.assertIn("which one", self.say("reply 5"))
        self.assertIn("Sent to bob on two", self.say("reply two 5"))
        self.assertEqual(self.store.answer("two")["text"], "5")
        self.assertIsNone(self.store.answer("one"))

    def test_every_reply_is_one_short_sentence(self):
        for i in range(8):
            self.store.start(f"Card number {i} with a long title", f"agent{i}")
            self.store.ask(f"card-number-{i}-with-a-long-title", "q" * 300)
        for q in ("status", "what needs me?", "what's ready for review?", "list"):
            self.assertLessEqual(len(self.say(q)), 160 + 100, q)   # 160 of text plus the XML wrapper

    def test_a_bad_command_is_a_reply_not_a_crash(self):
        self.assertIn("No: no card starting with 'ghost'", self.say("done ghost"))
        self.assertIn("No: add what", self.say("add:"))

    def test_replies_are_xml_safe_and_short(self):
        self.assertIn(b"a &amp; &lt;b&gt;", sms.twiml("a & <b>"))
        self.assertLessEqual(len(sms.twiml("x" * 1000)), 400)
        self.assertNotIn("<now>", self.say("add: fish & chips <now>"))

    def test_commands_go_through_the_normal_store_so_the_save_keeps_its_backup(self):
        self.say("add: one")
        self.say("add: two")
        self.assertTrue(Path(f"{self.store.path}.bak").exists())
        self.assertTrue(self.store.backups.snapshots())


class SettingsTests(Base):
    def write_conf(self, text):
        self.store.dir.mkdir(parents=True, exist_ok=True)
        (self.store.dir / "config.toml").write_text(text)

    def test_it_is_off_until_enabled_allowlisted_and_given_a_token(self):
        conf, problems = sms.settings(self.store.dir)
        self.assertGreaterEqual(len(problems), 4)
        self.write_conf('[sms]\nenabled = true\nallowed = ["416-555-0123"]\npublic_url = "https://t.example/sms"\n')
        with mock.patch.dict(os.environ, {sms.DEFAULT_TOKEN_ENV: "tok"}):
            conf, problems = sms.settings(self.store.dir)
        self.assertEqual(problems, [])
        self.assertEqual((conf["allowed"], conf["token"]), ([MOBILE], "tok"))

    def test_the_machine_lock_stops_it_even_when_everything_else_is_set(self):
        self.write_conf('[sms]\nenabled = true\nallowed = ["416-555-0123"]\npublic_url = "https://t.example/sms"\n')
        with mock.patch.dict(os.environ, {sms.DEFAULT_TOKEN_ENV: "tok", "AGENTBOARD_NO_SMS": "1"}):
            _conf, problems = sms.settings(self.store.dir)
            self.assertTrue(any("locked off on this machine" in p for p in problems))
            with self.assertRaises(BoardError):
                sms.serve(self.store, 0)
        with mock.patch.dict(os.environ, {sms.DEFAULT_TOKEN_ENV: "tok", "AGENTBOARD_NO_SMS": "0"}):
            self.assertEqual(sms.settings(self.store.dir)[1], [])

    def test_a_plain_http_url_is_refused_and_the_token_is_never_read_from_the_board(self):
        self.write_conf('[sms]\nenabled = true\nallowed = ["+14165550123"]\npublic_url = "http://insecure/sms"\ntoken = "from-a-file"\n')
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(sms.DEFAULT_TOKEN_ENV, None)
            conf, problems = sms.settings(self.store.dir)
        self.assertTrue(any("https" in p for p in problems))
        self.assertTrue(any("auth token" in p for p in problems))
        self.assertEqual(conf["token"], "")

    def test_serve_refuses_to_start_while_anything_is_missing(self):
        with self.assertRaises(Exception) as e:
            sms.serve(self.store, port=0)
        self.assertIn("will not start", str(e.exception))


class HttpTests(Base):
    """A fake Twilio POST over real HTTP to the endpoint on localhost."""

    def setUp(self):
        super().setUp()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), sms.make_handler(self.store, self.conf, log=lambda *_: None))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def twilio(self, body, sig=None, path="/sms", sender=MOBILE):
        p = self.params(body, sender=sender)
        data = urllib.parse.urlencode(p).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sign(p) if sig is None else sig})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, ""

    def test_a_signed_text_from_troy_adds_a_card_and_gets_one_line_back(self):
        code, xml = self.twilio("add: renew passports")
        self.assertEqual(code, 200)
        self.assertIn("<Message>Added to Todo: renew-passports</Message>", xml)
        self.assertEqual(self.titles("todo"), ["renew-passports"])

    def test_forged_and_stranger_requests_get_a_bare_403(self):
        self.assertEqual(self.twilio("add: x", sig="nope"), (403, ""))
        self.assertEqual(self.twilio("add: x", sender="+15555550123"), (403, ""))
        self.assertEqual(self.store.load(), [])

    def test_only_the_sms_route_exists_and_only_by_post(self):
        self.assertEqual(self.twilio("status", path="/api/tasks")[0], 404)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/tasks")
        self.assertEqual(e.exception.code, 404)
        e.exception.close()
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health") as r:
            self.assertEqual(r.read(), b"ok")


if __name__ == "__main__":
    unittest.main()
