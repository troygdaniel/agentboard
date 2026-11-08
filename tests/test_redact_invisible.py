"""The masker sees through invisible characters (sec2-mask-invisible-chars): "sk-" + a zero-width space + the key, or "Authorization:" + a
zero-width space + " Bearer <token>", passed through whole. It now matches on a copy without them and masks the original by span, so
ordinary text that uses them (a ZWJ in an emoji, a ZWNJ in Persian, a soft hyphen) is never rewritten."""
import json
import unicodedata
import unittest

from agentboard import redact, transcript
from agentboard.store import Store
from timing import Mixin

import tempfile
from pathlib import Path

# Fakes are assembled from pieces so this file never holds a whole one.
R = "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
SHAPES = {
    "aws": "AK" + "IA" + "Q3Z7K9M2P5R8T1V4", "sk": "sk" + "-ant-" + R[:28], "github": "gh" + "p_" + R, "slack": "xo" + "xb-" + "12345" + "67890-abcdefghij",
    "account": "A" + "C" + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e", "stripe": "sk" + "_live_" + R[:24], "google": "AI" + "za" + "SyA-" + R[:31], "npm": "np" + "m_" + R[:36],
    "sendgrid": "S" + "G." + R[:22] + "." + R[14:36], "hook": "https://hooks" + ".slack.com/services/" + "T0123ABCD" + "/" + "B0123ABCD" + "/" + R[:24],
    "jwt": "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "auth header": "Authorization: Bearer " + R[:24], "bearer": "Bearer " + R[:24], "assigned": "api_key = " + R[:24], "key-hex": "token: " + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a",
    "url password": "postgres://admin:" + "s3cr3t" + "Pw" + "@" + "db.internal/app", "pem line": "-----BEGIN " + "RSA PRIVATE KEY-----",
}
# the part of a secret that is inside the masked span (a URL password masks only "://user:password@"; the scheme and the host around it are ordinary text)
INSIDE = {"url password": (len("postgres"), len("postgres") + len("://admin:" + "s3cr3t" + "Pw" + "@"))}
INVISIBLE = {"zero-width space": "\u200b", "bidi override": "\u202e", "soft hyphen": "\u00ad", "word joiner": "\u2060", "BOM": "\ufeff", "variation selector": "\ufe0f",
             "tag char": "\U000e0041", "null": "\x00", "hangul filler": "\u3164"}


def insert(text, at, ch):
    return text[:at] + ch + text[at:]


class EveryShapeSurvivesAnInvisibleCharacter(unittest.TestCase):
    def test_inside_the_secret_the_result_is_what_it_would_have_been_without_the_character(self):
        for name, secret in SHAPES.items():
            want = redact.scrub(secret)
            self.assertNotEqual(want, secret, name)
            for cname, ch in INVISIBLE.items():
                lo, hi = INSIDE.get(name, (0, len(secret)))
                for at in sorted({lo + 1, lo + 3, (lo + hi) // 2, hi - 2}):
                    got = redact.scrub(insert(secret, at, ch))
                    self.assertEqual(got, want, f"{name} with a {cname} at {at}")

    def test_inside_a_sentence_and_with_several_characters_at_once(self):
        for name, secret in SHAPES.items():
            lo, hi = INSIDE.get(name, (0, len(secret)))
            noisy = secret[:lo] + "\u200b".join(secret[lo:hi]) + secret[hi:]          # a zero-width space between EVERY character inside the masked part
            tail = "" if name == "pem line" else " after"          # a key block with no end line runs to the end of the text, by design
            got = redact.scrub(f"before {noisy}{tail}")
            self.assertEqual(got, f"before {redact.scrub(secret)}{tail}", name)

    def test_the_two_cases_from_the_card(self):
        self.assertEqual(redact.scrub("sk-\u200b" + "ant-" + R[:28]), "[redacted api-key]")
        self.assertEqual(redact.scrub("Authorization:\u200b Bearer " + R[:24]), "Authorization: Bearer [redacted secret]")


class OrdinaryTextIsNeverRewritten(unittest.TestCase):
    ORDINARY = [
        "family \U0001F468\u200d\U0001F469\u200d\U0001F467 emoji", "heart ❤\ufe0f and flag \U0001F1E8\U0001F1E6", "persian می\u200cخواهم",
        "co\u00adoperate and re\u00adinstall", "hebrew \u200fשלום\u200f mark", "\ufeffa BOM at the start", "tab\tand\nnewline\rand return", "bidi \u202bthing\u202c here",
        "arabic number sign \u0600123", "a\u200bb zero-width in a word", "commit 3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a\u200b",
    ]

    def test_none_of_it_changes(self):
        for text in self.ORDINARY:
            self.assertEqual(redact.scrub(text), text, repr(text))

    def test_characters_around_and_beside_a_masked_secret_stay(self):
        key = SHAPES["aws"]
        self.assertEqual(redact.scrub("\u200b" + key + "\u200b lead and trail"), "\u200b[redacted aws-key]\u200b lead and trail")
        self.assertEqual(redact.scrub(f"\U0001F468\u200d\U0001F469 {key} می\u200cخ"), "\U0001F468\u200d\U0001F469 [redacted aws-key] می\u200cخ")


class SpansLandInTheRightPlace(unittest.TestCase):
    def test_many_hidden_characters_before_a_match_do_not_shift_it(self):
        key = SHAPES["aws"]
        text = ("a\u200b" * 1500) + " " + key + " end"
        out = redact.scrub(text)
        self.assertTrue(out.endswith(" [redacted aws-key] end"))
        self.assertEqual(out.count("\u200b"), 1500)

    def test_two_secrets_with_hidden_characters_between_and_inside_them(self):
        a, b = SHAPES["aws"], SHAPES["sk"]
        text = insert(a, 5, "\u200b") + "\u202e \u200b" + insert(b, 7, "\u00ad")
        self.assertEqual(redact.scrub(text), "[redacted aws-key]\u202e \u200b[redacted api-key]")

    def test_found_reports_the_first_four_characters_of_what_it_saw(self):
        found = []
        redact.scrub("x " + insert(SHAPES["aws"], 2, "\u200b"), found=found)
        self.assertEqual(found, [("aws-key", "AKIA")])

    def test_a_text_with_a_great_many_is_cleaned_instead_of_mapped(self):
        text = ("\u200b" * (redact.MAX_HIDDEN + 10)) + SHAPES["aws"]
        self.assertEqual(redact.scrub(text), "[redacted aws-key]")          # the invisible ones are dropped: this is not prose


class StillFast(Mixin, unittest.TestCase):
    def test_hostile_amounts_of_invisible_characters(self):
        for name, text in (("only zero-width", "\u200b" * 1_000_000), ("sk- and a zwsp", "sk-\u200b" * 250_000), ("key split by zwsp", ("ke\u200by=" + "a" * 19 + " ") * 25_000),
                           ("just under the limit", ("word " * 200_000)[:900_000] + "\u200b" * (redact.MAX_HIDDEN - 1) + SHAPES["aws"])):
            self.assertFast(redact.scrub, 3.0, text, msg=name)   # 3 s idle; tests/timing.py stretches it with the load and retries

    def test_the_bound_still_applies(self):
        out = redact.scrub("word " * 100 + "\u200b" * 10, bound=50)
        self.assertLessEqual(len(out), 50)


class TheSetIsSound(unittest.TestCase):
    def test_everything_it_treats_as_invisible_really_is(self):
        allowed = {"Cc", "Cf", "Co", "Cs", "Mn", "Lo", "So", "Ps"}          # control, format, private, surrogate, and the few invisible fillers and selectors
        tables = tuple(int(x) for x in unicodedata.unidata_version.split("."))   # 3.11 ships Unicode 14, 3.12 15.0, 3.13 15.1, 3.14 16.0
        allchars = "".join(chr(i) for i in range(0x110000))
        for m in redact._INVISIBLE.finditer(allchars):
            ch = m.group(0)
            cat = unicodedata.category(ch)
            if cat == "Cn" and tables < (16, 0, 0):   # unassigned to THIS interpreter's tables: a format control newer than them (U+13439 is Unicode 15), checked on 16.0
                continue
            self.assertIn(cat, allowed, hex(ord(ch)))
            self.assertNotIn(ch, "\t\n\r ")

    def test_the_well_known_ones_are_in(self):
        for cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202E, 0x2060, 0x2066, 0x2069, 0xFEFF, 0xAD, 0x0, 0x7F, 0x9F, 0xE0041, 0xFE0F, 0x34F, 0x3164):
            self.assertTrue(redact._INVISIBLE.match(chr(cp)), hex(cp))
        for cp in (0x09, 0x0A, 0x0D, 0x20, 0x41, 0x2D, 0x3A):
            self.assertFalse(redact._INVISIBLE.match(chr(cp)), hex(cp))


class WhereItMatters(unittest.TestCase):
    def test_the_store_and_the_card_id(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            k = insert(SHAPES["sk"], 4, "\u200b")
            t, _ = s.start_card(f"started with {k}", "AGENT-1", description=f"d {k}")
            self.assertEqual(t["title"], "started with [redacted api-key]")
            self.assertEqual(t["description"], "d [redacted api-key]")
            self.assertNotIn("q3z7", t["id"])
            self.assertNotIn("q3Z7k9M2", (s.dir / "tasks.json").read_text())

    def test_the_terminal_tab(self):
        raw = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the key is " + insert(SHAPES["aws"], 6, "\u202e")}]}})
        self.assertEqual(transcript.parse_line(raw)[0]["text"], "the key is [redacted aws-key]")

    def test_the_audit_command_finds_one_that_is_already_stored(self):
        data = {"tasks": [{"id": "c", "title": "t", "description": insert(SHAPES["aws"], 4, "\u200b"), "log": []}], "chat": []}
        hits = redact.scrub_data(data, None)
        self.assertEqual([(w, k) for w, k, _h in hits], [("card c description", "aws-key")])


if __name__ == "__main__":
    unittest.main()
