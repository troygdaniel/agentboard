"""Secret-shaped text is masked on its way into the board and in reports (sec-data-redact-store), and nothing else is: a commit hash, a card id,
a path, a sentence, a phone number or a code snippet reads exactly as written."""
import contextlib
import gzip
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publiccheck  # noqa: E402

from agentboard import cli, redact, reports  # noqa: E402
from agentboard.store import Store  # noqa: E402

# Fakes are assembled from pieces so this file never holds a whole one (the repo scan stays clean).
AWS = "AK" + "IA" + "Q3Z7K9M2P5R8T1V4"
SK = "sk" + "-ant-" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2"
GH = "gh" + "p_" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
SLACK = "xo" + "xb-" + "12345" + "67890-abcdefghij"
ACCT = "A" + "C" + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e"
HEX40 = "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a"
HEX32 = "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e"
TOKEN = "q3Z7k9M2p5R8t1V4w6Y0a2C4"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END " + "RSA PRIVATE KEY-----"
MAIL = "some" + "one" + "@" + "corp" + ".test"      # an email outside the repo guard's allow-list, built from parts
PH = "416" + "-867-" + "4410"        # looks like a real number, built from parts (no whole one in the repo)
PH2 = "(212) " + "867-" + "4410"
PH3 = "+1212" + "8674410"
JWT = "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


class Masks(unittest.TestCase):
    def test_each_shape_is_masked_and_what_you_read_stays(self):
        cases = [
            (f"ran: curl -H 'Authorization: Token {HEX40}' https://x.invalid", "ran: curl -H 'Authorization: Token [redacted secret]' https://x.invalid"),
            (f"Authorization: Bearer {TOKEN} ok", "Authorization: Bearer [redacted secret] ok"),
            (f"Authorization: Basic {TOKEN}==", "Authorization: Basic [redacted secret]"),
            (f"key {AWS} now", "key [redacted aws-key] now"),
            (f"use {SK}.", "use [redacted api-key]."),
            (f"use {GH}.", "use [redacted github-token]."),
            (f"hook {SLACK}", "hook [redacted slack-token]"),
            (f"account {ACCT}", "account [redacted account-sid]"),
            (f"jwt {JWT} end", "jwt [redacted jwt] end"),
            (f'api_key = "{TOKEN}"', 'api_key = "[redacted secret]"'),
            (f"API_KEY={TOKEN}", "API_KEY=[redacted secret]"),
            (f"password: {TOKEN}", "password: [redacted secret]"),
            (f"token: {HEX40}", "token: [redacted hex]"),
            (f"the secret {HEX32}", "the secret [redacted hex]"),
            (f"before\n{PEM}\nafter", "before\n[redacted private-key]\nafter"),
            ("a cut-off key\n-----BEGIN " + "PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnz", "a cut-off key\n[redacted private-key]"),
        ]
        for text, want in cases:
            self.assertEqual(redact.scrub(text), want, text[:50])

    def test_several_in_one_text_and_the_result_is_stable(self):
        text = f"{AWS} {SK} Authorization: Token {HEX40}"
        once = redact.scrub(text)
        self.assertEqual(once, "[redacted aws-key] [redacted api-key] Authorization: Token [redacted secret]")
        self.assertEqual(redact.scrub(once), once)

    def test_found_lists_what_was_masked_by_kind_and_four_characters(self):
        found = []
        redact.scrub(f"{AWS} and {SK}", found=found)
        self.assertEqual(found, [("aws-key", "AKIA"), ("api-key", "sk-a")])


class LeavesOrdinaryTextAlone(unittest.TestCase):
    ORDINARY = [
        f"commit {HEX40} fixed it", f"sha256: {HEX40}", f"merged {HEX40[:7]} and {HEX40[:12]}", "card ap-123 and text-card-title-list-recall",
        "see http://localhost:8765/api/tasks?id=a-card", "/Users/you/dev/agentboard/src/agentboard/redact.py:42", "2026-11-07T01:02:03",
        "uuid 123e4567-e89b-12d3-a456-426614174000", "password reset flow", "the token_count was 12345678", "get_password_from_user()",
        "secret = os.environ['X']", 'password = input("Password: ")', "api key is needed", "an API key must be rotated", "key 12345", "a long-winded-hyphenated-word-without-meaning",
        f"call 416-555-0123 or {PH2} or +14165550123", f"mail a@b.example.org and {MAIL}", "ACb" + "b" * 31, "AC" + "0" * 32,
        "AKIA" + "EXAMPLE" + "EXAMPLE12", "sk-...", "sk-" + "x" * 30, "Authorization: Bearer $TOKEN", "Authorization: Token <token>", 'api_key = "your-api-key-goes-here"',
        'password = "changeme1changeme2"', "token: " + "a" * 40, "Bundle 412kb -> 271kb, verified in prod build", "756 tests pass · render-check wide and narrow",
        "## Changed\n- one\n## Checked\n- two\n```flow\nA -> B\n```", "ssh-rsa is an algorithm; sk is Slovakia", "Base64 of hello: aGVsbG8gd29ybGQ=", "",
    ]

    def test_ordinary_text_is_unchanged(self):
        for text in self.ORDINARY:
            self.assertEqual(redact.scrub(text), text, text[:60])

    def test_phone_numbers_are_left_by_default(self):
        self.assertEqual(redact.scrub(f"lawyer: {PH}"), f"lawyer: {PH}")

    def test_anything_that_is_not_text_comes_back_as_it_was(self):
        for v in (None, 5, 1.5, ["x"], {"a": AWS}, b"bytes"):
            self.assertEqual(redact.scrub(v), v)


class TheSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / ".agentboard"
        self.dir.mkdir()

    def conf(self, text):
        p = self.dir / "config.toml"
        p.write_text(text)
        os.utime(p, ns=(time.time_ns() + 10**9 * self.n, time.time_ns() + 10**9 * self.n))   # a new modification time, whatever the clock
        self.n += 1

    n = 1

    def test_defaults_without_a_file(self):
        self.assertEqual(redact.settings(self.dir), {"enabled": True, "phones": False, "extra": []})
        self.assertEqual(redact.scrub(f"k {AWS}", self.dir), "k [redacted aws-key]")

    def test_it_can_be_switched_off(self):
        self.conf("[redact]\nenabled = false\n")
        self.assertEqual(redact.scrub(f"k {AWS}", self.dir), f"k {AWS}")

    def test_phones_are_opt_in_and_fictional_ones_stay(self):
        self.conf("[redact]\nphones = true\n")
        self.assertEqual(redact.scrub(f"call {PH} or 416-555-0123 or {PH3}", self.dir), "call [redacted phone] or 416-555-0123 or [redacted phone]")

    def test_your_own_patterns(self):
        self.conf('[redact]\nextra = ["ACME-[0-9]{6}", "(unclosed"]\n')
        self.assertEqual(redact.scrub("ticket ACME-123456 and (unclosed paren", self.dir), "ticket [redacted match] and [redacted match] paren")

    def test_a_changed_config_is_picked_up_and_a_broken_one_means_defaults(self):
        self.conf("[redact]\nenabled = false\n")
        self.assertEqual(redact.scrub(AWS, self.dir), AWS)
        self.conf("[redact]\nenabled = true\n")
        self.assertEqual(redact.scrub(AWS, self.dir), "[redacted aws-key]")
        self.conf("this is [not toml")
        self.assertEqual(redact.scrub(AWS, self.dir), "[redacted aws-key]")


class OnTheWayIntoTheStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def everything(self):
        """Every byte the board keeps: tasks.json, its .bak, each snapshot, each report."""
        d = self.s.dir
        out = [(d / "tasks.json").read_text()]
        if (d / "tasks.json.bak").exists():
            out.append((d / "tasks.json.bak").read_text())
        for g in (d / "backups").glob("*.gz"):
            out.append(gzip.decompress(g.read_bytes()).decode())
        for r in (d / "reports").glob("*.html"):
            out.append(r.read_text())
        return "\n".join(out)

    def test_every_way_an_agent_can_write_text_is_masked(self):
        s = self.s
        s.set_chat_agents(True)       # a detail, like the other agent-to-agent extras, needs the board-wide switch
        s.add(f"Use {AWS}", f"description with {SK}", status="todo", task_id="c")
        s.claim("c", "AGENT-1")
        s.add("step", parent_id="c", task_id="step")
        s.update("step", 30, f"ran curl -H 'Authorization: Token {HEX40}'", body_md=f"body {GH}")
        s.ask("c", f"is {SLACK} right?", body_md=f"detail {ACCT}")
        s.edit("c", description=f"edited {AWS}")
        s.chat_send("AGENT-1", f"heads up {SK}", detail=f"detail {GH}")
        s.chat_send("AGENT-1", f"first line\nsecond line has {AWS}")
        s.update("step", 100, "done")
        s.review("c", f"result with {JWT}", body_md=f"## Changed\n- {PEM}\n- {HEX32}")
        s.backups.take("manual")
        reports.write_report(s, "c")
        data = self.everything()
        for secret in (AWS, SK, GH, SLACK, ACCT, HEX40, JWT, "MIIBOgIBAAJBAKj34", ):
            self.assertNotIn(secret, data, secret[:12])
        self.assertIn("[redacted aws-key]", data)
        self.assertIn("Authorization: Token [redacted secret]", data)

    def test_a_card_made_from_a_text_is_masked_too(self):
        self.s.add(f"my key is {AWS}", "From a text", status="todo", source={"kind": "text", "key": "k1", "sid": "SM1", "at": "2026-11-07T01:00:00+00:00"})
        self.assertNotIn(AWS, (self.s.dir / "tasks.json").read_text())

    def test_what_the_owner_types_is_left_as_written(self):
        s = self.s
        s.add("Card", status="todo", task_id="c")
        s.claim("c", "AGENT-1")
        s.add("step", parent_id="c", task_id="step")
        s.update("step", 10, "working")
        s.ask("c", "which key?")
        s.reply("c", f"use {AWS}")
        s.chat_send("Troy", f"please use {SK}", kind="user")
        self.assertIn(AWS, (self.s.dir / "tasks.json").read_text())
        self.assertIn(SK, (self.s.dir / "tasks.json").read_text())

    def test_ordinary_card_text_is_stored_exactly_as_written(self):
        title, desc = f"Fix {HEX40[:7]} regression", f"commit {HEX40} on /Users/you/x; call {PH}; password reset flow"
        t = self.s.add(title, desc, status="todo")
        self.assertEqual((t["title"], t["description"]), (title, desc))

    def test_the_setting_off_means_nothing_is_masked(self):
        (self.s.dir).mkdir(exist_ok=True)
        (self.s.dir / "config.toml").write_text("[redact]\nenabled = false\n")
        t = self.s.add(f"Use {AWS}", status="todo")
        self.assertIn(AWS, t["title"])

    def test_a_secret_cut_by_the_length_cap_is_still_masked(self):
        self.s.add("Card", status="todo", task_id="c")
        self.s.claim("c", "AGENT-1")
        self.s.add("step", parent_id="c", task_id="step")
        text = "x" * 990 + AWS      # the cap would cut the key in half: it is masked first, then capped
        self.s.update("step", 10, text)
        self.assertNotIn("AKIA", (self.s.dir / "tasks.json").read_text())


class InReportsOfOlderCards(unittest.TestCase):
    def test_a_secret_already_in_tasks_json_is_masked_in_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Old card", status="todo", task_id="old")
            s.claim("old", "AGENT-1")
            s.add("step", parent_id="old", task_id="step")
            s.update("step", 100, "done")
            s.review("old", "finished")
            data = json.loads(s.path.read_text())
            card = next(t for t in data["tasks"] if t["id"] == "old")
            card["result"] = f"finished with {AWS}"
            card["body_md"] = f"## Changed\n- key {SK}"
            card["log"].append({"at": "2026-11-06T22:00:00", "text": f"used {GH}", "by": "AGENT-1"})
            s.path.write_text(json.dumps(data))      # as an older version would have left it
            name = reports.write_report(s, "old")
            html = (reports.reports_dir(s.dir) / name).read_text() if name else ""
            self.assertTrue(html)
            for secret in (AWS, SK, GH):
                self.assertNotIn(secret, html)


class TheCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        # an older board: secrets already stored, written the way an older version did (straight into the file)
        self.s.add("Old", status="todo", task_id="old")
        self.s.claim("old", "AGENT-1")
        self.s.add("step", parent_id="old", task_id="step")
        self.s.update("step", 10, "working")
        self.s.ask("old", "which key?")
        self.s.reply("old", f"use {AWS}")                   # the owner's: left alone
        self.s.chat_send("Troy", f"please use {SK}", kind="user")
        data = json.loads(self.s.path.read_text())
        old = next(t for t in data["tasks"] if t["id"] == "old")
        old["status_text"] = f"tried {GH}"
        old["log"].append({"at": "2026-11-06T22:00:00", "text": f"ran with Authorization: Token {HEX40}", "by": "AGENT-1"})
        data["chat"].append({"seq": 99, "kind": "agent", "sender": "AGENT-1", "text": f"found {SLACK}", "detail": None, "at": "2026-11-06T22:00:00"})
        self.s.path.write_text(json.dumps(data))

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            cli.main(list(argv))
        return out.getvalue()

    def test_it_shows_where_and_what_kind_without_printing_the_secret_and_changes_nothing(self):
        before = self.s.path.read_text()
        out = self.run_cli("redact")
        self.assertIn("card old status_text: github-token (ghp_...)", out)
        self.assertIn("card old log #", out)
        self.assertIn("chat #99 text: slack-token (xoxb...)", out)
        self.assertIn("nothing changed", out)
        for secret in (GH, HEX40, SLACK):
            self.assertNotIn(secret, out)
        self.assertEqual(self.s.path.read_text(), before)

    def test_apply_masks_after_a_snapshot_and_skips_the_owners_own_words(self):
        out = self.run_cli("redact", "--apply")
        self.assertIn("masked 3 string(s)", out)
        data = self.s.path.read_text()
        for secret in (GH, HEX40, SLACK):
            self.assertNotIn(secret, data)
        self.assertIn(AWS, data)       # the owner's reply
        self.assertIn(SK, data)        # the owner's chat line
        snaps = [p.name for p in (self.s.dir / "backups").glob("*before-redact*")]
        self.assertEqual(len(snaps), 1)
        self.assertIn(GH, gzip.decompress((self.s.dir / "backups" / snaps[0]).read_bytes()).decode())   # the old text is recoverable from it
        self.assertIn("nothing on the board looks like a secret", self.run_cli("redact"))

    def test_it_says_so_when_redaction_is_off(self):
        (self.s.dir / "config.toml").write_text("[redact]\nenabled = false\n")
        self.assertIn("redaction is off", self.run_cli("redact", "--apply"))
        self.assertIn(GH, self.s.path.read_text())


class AgreesWithTheRepoGuard(unittest.TestCase):
    """tests/publiccheck.py keeps secrets out of the repo, redact.py out of the board: they must see the same shapes."""

    def test_whatever_the_board_masks_the_repo_scan_would_flag(self):
        for text in (AWS, SK, GH, SLACK, ACCT, f"Authorization: Token {TOKEN}", f'api_key = "{TOKEN}"', f"token: {HEX40}", "-----BEGIN " + "RSA PRIVATE KEY-----"):
            self.assertNotEqual(redact.scrub(text), text, text[:30])
            self.assertTrue(publiccheck.scan_text(text), text[:30])


if __name__ == "__main__":
    unittest.main()
