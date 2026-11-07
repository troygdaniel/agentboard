"""The once-a-minute pull of your texts (Nov 7): OFF until switched on in Settings, locked by AGENTBOARD_NO_SMS, stopped by any error.
Fake Twilio only: no network. Builds on test_pull_texts' fixtures."""
import json
import os
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from agentboard import texts
from agentboard.store import BoardError, Store

from test_pull_texts import HTML, NOW, SID, STRANGER, TOKEN, TROY, Base, ThePullButton, at


class TheTimer(Base):
    def tick(self, **kw):
        kw.setdefault("now", NOW)
        return texts.tick(self.s, http=self.tw, **kw)

    def state_text(self):
        return (self.s.dir / texts.STATE_FILE).read_text()

    def test_off_by_default_a_tick_calls_nothing(self):
        self.tw.text("buy milk", at(6))
        self.assertIsNone(self.tick())
        self.assertEqual(self.tw.calls, [])
        self.assertEqual(self.cards(), [])
        st = texts.status(self.s.dir)
        self.assertFalse(st["on"])
        self.assertEqual(st["line"], "Off")
        self.assertTrue(st["show"])

    def test_a_restart_starts_off_unless_the_switch_was_left_on(self):
        self.assertFalse(texts.status(self.s.dir)["on"])
        texts.set_auto(self.s.dir, True)
        again = Store(self.s.dir)   # the server came back: the switch is in the state file, not in memory
        self.assertTrue(texts.status(again.dir)["on"])
        texts.set_auto(self.s.dir, False)
        self.assertFalse(texts.status(Store(self.s.dir).dir)["on"])

    def test_the_lock_beats_the_switch_and_the_tick(self):
        texts.set_auto(self.s.dir, True)
        self.tw.text("buy milk", at(6))
        with mock.patch.dict(os.environ, {"AGENTBOARD_NO_SMS": "1"}):
            with self.assertRaises(BoardError) as cm:
                texts.set_auto(self.s.dir, True)
            self.assertIn("locked off", str(cm.exception))
            self.assertIsNone(self.tick())   # the lock was set after the switch: still no call
            st = texts.status(self.s.dir)
            self.assertTrue(st["locked"])
            self.assertFalse(st["on"])
            self.assertIn("Locked off", st["line"])
        self.assertEqual(self.tw.calls, [])
        self.assertEqual(self.cards(), [])

    def test_switched_on_a_tick_pulls_once_and_says_so(self):
        texts.set_auto(self.s.dir, True)
        self.tw.text("buy milk", at(6))
        res = self.tick()
        self.assertEqual(len(res["created"]), 1)
        self.assertEqual(self.titles(), ["buy milk"])
        self.assertEqual((self.cards()[0].get("source") or {}).get("kind"), "text")   # the same From a text chip as a hand pull
        st = texts.status(self.s.dir)
        self.assertTrue(st["on"])
        self.assertEqual(st["line"], "Pulling every minute")
        self.assertEqual(st["last_made"], 1)
        self.assertEqual(st["last_at"], NOW.isoformat())
        self.assertEqual(len(self.tick()["created"]), 0)   # the next minute: nothing new, no twin
        self.assertEqual(self.titles(), ["buy milk"])

    def test_once_per_text_across_a_restart_a_flip_and_the_button(self):
        texts.set_auto(self.s.dir, True)
        self.tw.text("buy milk", at(6))
        self.tick()
        self.s = Store(self.s.dir)   # restart
        texts.set_auto(self.s.dir, False)
        texts.set_auto(self.s.dir, True)
        self.pull()                   # the button, by hand
        self.tick()
        self.tick(now=NOW + timedelta(minutes=1))
        self.assertEqual(self.titles(), ["buy milk"])

    def test_a_stranger_is_counted_never_read(self):
        texts.set_auto(self.s.dir, True)
        self.tw.text("secret words", at(6), sender=STRANGER)
        res = self.tick()
        self.assertEqual(res["ignored"], 1)
        self.assertEqual(self.cards(), [])
        self.assertNotIn(STRANGER, self.state_text())
        self.assertNotIn("secret", self.state_text())

    def test_a_twilio_error_stops_the_timer_and_nothing_retries(self):
        texts.set_auto(self.s.dir, True)

        def refused(path, sid, token):
            raise BoardError("Twilio refused the account SID and auth token: check both are the ones from your Twilio console")

        res = texts.tick(self.s, http=refused, now=NOW)
        self.assertIsInstance(res, BoardError)
        st = texts.status(self.s.dir)
        self.assertFalse(st["on"])
        self.assertTrue(st["line"].startswith("Stopped: Twilio refused"))
        self.assertIsNone(texts.tick(self.s, http=refused, now=NOW))   # the next minute does nothing: Troy switches it on again
        for secret in (SID, TOKEN, TROY):
            self.assertNotIn(secret, st["line"])
            self.assertNotIn(secret, self.state_text())
        texts.set_auto(self.s.dir, True)   # switching on again clears the reason and retries once
        self.assertEqual(texts.status(self.s.dir)["error"], "")
        self.tw.text("buy milk", at(6))
        self.assertEqual(len(self.tick()["created"]), 1)

    def test_a_network_error_stops_it_too(self):
        texts.set_auto(self.s.dir, True)

        def offline(path, sid, token):
            raise BoardError("could not reach Twilio (URLError)")

        self.assertIsInstance(texts.tick(self.s, http=offline, now=NOW), BoardError)
        self.assertFalse(texts.status(self.s.dir)["on"])
        self.assertIsNone(texts.tick(self.s, http=offline, now=NOW))

    def test_an_unexpected_error_stops_it_too_and_names_only_its_class(self):
        texts.set_auto(self.s.dir, True)

        def broken(path, sid, token):
            raise ConnectionResetError(f"peer closed while reading {token}")   # not a BoardError, and a message that must never be shown

        res = texts.tick(self.s, http=broken, now=NOW)
        self.assertIsInstance(res, BoardError)
        st = texts.status(self.s.dir)
        self.assertFalse(st["on"])
        self.assertEqual(st["line"], "Stopped: unexpected error (ConnectionResetError)")
        self.assertNotIn(TOKEN, self.state_text())
        self.assertIsNone(texts.tick(self.s, http=broken, now=NOW))   # no retry loop

    def test_a_token_that_vanishes_after_start_stops_it_without_naming_it(self):
        texts.set_auto(self.s.dir, True)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTBOARD_TWILIO_AUTH_TOKEN")
            res = self.tick()
        self.assertIsInstance(res, BoardError)
        st = texts.status(self.s.dir)
        self.assertIn("AGENTBOARD_TWILIO_AUTH_TOKEN", st["line"])   # the variable's name, so Troy knows what to fix
        self.assertNotIn(TOKEN, st["line"])
        self.assertNotIn("\n", st["line"])
        self.assertEqual(self.tw.calls, [])

    def test_the_switch_will_not_go_on_until_the_board_is_set_up(self):
        (self.s.dir / "config.toml").write_text("[texts]\nenabled = true\n")
        with self.assertRaises(BoardError) as cm:
            texts.set_auto(self.s.dir, True)
        self.assertIn("number", str(cm.exception))
        self.assertFalse(texts.status(self.s.dir)["on"])
        self.assertIsNone(self.tick())
        self.assertEqual(self.tw.calls, [])

    def test_no_two_timed_pulls_at_once(self):
        texts.set_auto(self.s.dir, True)
        self.tw.text("buy milk", at(6))
        inside, go, calls = threading.Event(), threading.Event(), []

        def slow(path, sid, token):
            calls.append(path)
            inside.set()
            go.wait(5)
            return self.tw(path, sid, token)

        first = {}
        t = threading.Thread(target=lambda: first.setdefault("res", texts.tick(self.s, http=slow, now=NOW)))
        t.start()
        self.assertTrue(inside.wait(5))
        self.assertIsNone(texts.tick(self.s, http=slow, now=NOW))   # the second beat finds one running and steps aside
        go.set()
        t.join(5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(first["res"]["created"]), 1)
        self.assertEqual(self.titles(), ["buy milk"])

    def test_the_state_file_holds_the_switch_and_no_secrets(self):
        texts.set_auto(self.s.dir, True)
        self.tw.text("buy milk", at(6))
        self.tick()
        d = json.loads(self.state_text())
        self.assertIs(d["auto"], True)
        self.assertEqual(d["last"]["made"], 1)
        for secret in (SID, TOKEN, TROY, "buy milk"):
            self.assertNotIn(secret, self.state_text())


class TheSwitch(ThePullButton):
    def test_the_page_is_told_the_timer_state_with_the_tasks(self):
        code, d = self.call("/api/tasks")
        self.assertEqual(code, 200)
        self.assertEqual(d["texts"]["on"], False)
        self.assertEqual(d["texts"]["line"], "Off")

    def test_the_switch_flips_on_and_off(self):
        code, d = self.call("/api/texts-auto", {"on": True})
        self.assertEqual((code, d["on"], d["line"]), (200, True, "Pulling every minute"))
        self.assertTrue(self.call("/api/tasks")[1]["texts"]["on"])
        code, d = self.call("/api/texts-auto", {"on": False})
        self.assertEqual((code, d["on"], d["line"]), (200, False, "Off"))

    def test_locked_the_switch_is_refused_and_the_page_knows(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_NO_SMS": "1"}):
            code, d = self.call("/api/texts-auto", {"on": True})
            self.assertEqual(code, 400)
            self.assertIn("locked off", d["error"])
            tx = self.call("/api/tasks")[1]["texts"]
            self.assertTrue(tx["locked"])
            self.assertFalse(tx["on"])
        self.assertEqual(self.tw.calls, [])

    def test_a_board_without_texts_sends_no_timer_state(self):
        (self.s.dir / "config.toml").write_text("")
        self.assertNotIn("texts", self.call("/api/tasks")[1])

    def test_the_switch_answer_never_carries_a_secret(self):
        raw = json.dumps(self.call("/api/texts-auto", {"on": True})[1]) + json.dumps(self.call("/api/tasks")[1]["texts"])
        for secret in (SID, TOKEN, TROY):
            self.assertNotIn(secret, raw)


class TheSecondKey(Base):
    """Texts need the machine's say-so (AGENTBOARD_TEXTS=1) as well as the board's ([texts] enabled). Without it nothing texts-related exists."""

    def no_key(self):
        return mock.patch.dict(os.environ, {texts.OPTIN_ENV: ""})

    def test_without_it_the_command_the_switch_and_the_timer_all_refuse(self):
        texts.set_auto(self.s.dir, True)   # switched on while the key was there…
        self.tw.text("buy milk", at(6))
        with self.no_key():
            self.assertFalse(texts.available(self.s.dir))
            with self.assertRaises(BoardError) as cm:
                self.pull(dry_run=True)
            self.assertIn("AGENTBOARD_TEXTS=1", str(cm.exception))
            with self.assertRaises(BoardError):
                texts.set_auto(self.s.dir, True)
            self.assertIsNone(texts.tick(self.s, http=self.tw, now=NOW))   # …and taken away after: the beat does nothing
            st = texts.status(self.s.dir)
            self.assertFalse(st["show"])
            self.assertFalse(st["on"])
        self.assertEqual(self.tw.calls, [])
        self.assertEqual(self.cards(), [])

    def test_the_lock_still_wins_over_both_keys(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_NO_SMS": "1", texts.OPTIN_ENV: "1"}):
            ok, why = texts.allowed(self.s.dir)
            self.assertFalse(ok)
            self.assertIn("locked off", why)
            st = texts.status(self.s.dir)
            self.assertTrue(st["show"] and st["locked"])   # shown, disabled, with the reason
            self.assertIn("Locked off", st["line"])

    def test_every_gate_goes_through_one_function(self):
        src = Path(texts.__file__).read_text()
        self.assertEqual(src.count("def allowed("), 1)
        for fn in ("def settings(", "def available(", "def status(", "def set_auto(", "def tick("):
            start = src.index(fn)
            end = src.find("\ndef ", start + 1)
            body = src[start:end if end > 0 else len(src)]
            self.assertIn("allowed(", body, fn)


class TheSecondKeyOnTheServer(ThePullButton):
    def test_without_it_the_page_has_no_button_no_state_and_the_switch_is_refused(self):
        with mock.patch.dict(os.environ, {texts.OPTIN_ENV: ""}):
            self.assertFalse(self.call("/api/config")[1]["texts"])
            self.assertNotIn("texts", self.call("/api/tasks")[1])
            code, d = self.call("/api/texts-auto", {"on": True})
            self.assertEqual(code, 400)
            self.assertIn("AGENTBOARD_TEXTS=1", d["error"])
            self.assertEqual(self.call("/api/pull-texts", {})[0], 400)
        self.assertEqual(self.tw.calls, [])


class ThePageHasTheSwitch(unittest.TestCase):
    def test_the_switch_and_the_chip_are_there_and_quiet(self):
        self.assertIn('id="cfg-tx"', HTML)
        self.assertIn('id="texts-chip"', HTML)
        self.assertIn("'/api/texts-auto'", HTML)
        self.assertIn('role="status"', HTML[HTML.index('id="texts-chip"') - 80:HTML.index('id="texts-chip"') + 160])
        body = HTML[HTML.index("function renderTexts"):HTML.index("$('texts-chip').onclick")]
        self.assertNotIn("toast(", body)
        self.assertNotIn("showError(", body)
        self.assertNotIn("cue.", body)

    def test_security_md_says_the_board_can_call_out_when_the_timer_is_on(self):
        text = (Path(texts.__file__).parents[2] / "SECURITY.md").read_text()
        self.assertIn("once a minute", text)
        self.assertIn("api.twilio.com", text)


if __name__ == "__main__":
    unittest.main()
