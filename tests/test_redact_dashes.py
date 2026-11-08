"""The masker sees through look-alike dashes (low-core-masker-sk-a-unicode-hyphen-even): "sk" + U+2010 + the key, or an en dash, a minus sign, a
fullwidth hyphen, passed through whole because the patterns want a plain "-". It now folds every Unicode dash to "-" on the matching copy (one for
one, so no position moves) and masks the original by span, so ordinary text that uses them ("pages 3-5" with an en dash) is never rewritten."""
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

from agentboard import redact, transcript
from agentboard.store import Store
from timing import Mixin

# Fakes are assembled from pieces so this file never holds a whole one.
R = "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
SHAPES = {
    "sk-ant": "sk" + "-ant-" + R[:28], "sk-proj": "sk" + "-proj-" + R[:28], "sk": "sk" + "-" + R[:40], "slack": "xo" + "xb-" + "12345" + "67890-abcdefghij",
    "google": "AI" + "za" + "SyA-" + R[:31], "x-api-key": "x-api-key: " + R[:24], "client-secret": "client-secret=" + R[:24],
    "jwt": "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N-XgL0n3I9PlFUP0THsR8U",
    "pem line": "-----BEGIN " + "RSA PRIVATE KEY-----",
}
# one of each kind of look-alike (the whole set is checked below); chr() keeps this file free of the characters themselves
FORMS = {"hyphen U+2010": 0x2010, "non-breaking hyphen": 0x2011, "figure dash": 0x2012, "en dash": 0x2013, "em dash": 0x2014, "horizontal bar": 0x2015,
         "minus sign": 0x2212, "fullwidth hyphen-minus": 0xFF0D, "small hyphen-minus": 0xFE63, "small em dash": 0xFE58, "hyphen bullet": 0x2043,
         "Hebrew maqaf": 0x05BE, "Armenian hyphen": 0x058A, "double hyphen": 0x30A0, "wave dash": 0x301C, "heavy minus": 0x2796}


def swapped(text, ch):
    """text with all of its "-" replaced by ch."""
    return text.replace("-", ch)


class EveryShapeSurvivesALookAlikeDash(unittest.TestCase):
    def test_all_of_them_at_once_and_one_at_a_time(self):
        # Inside a masked match the part that is KEPT (an assignment's name, "x-api-key: ") reads with plain hyphens, as invisible characters
        # inside it are dropped too; so compare the dashes' form away. What matters is that the secret is gone and the shape still matched.
        fold = lambda t: t.translate(redact._DASHES)
        for name, secret in SHAPES.items():
            want = redact.scrub(secret)
            self.assertNotEqual(want, secret, name)
            for fname, cp in FORMS.items():
                ch = chr(cp)
                self.assertEqual(fold(redact.scrub(swapped(secret, ch))), want, f"{name} with every dash as {fname}")
                parts = secret.split("-")
                for n in range(len(parts) - 1):
                    one = "-".join(parts[:n + 1]) + ch + "-".join(parts[n + 1:])
                    self.assertEqual(fold(redact.scrub(one)), want, f"{name}: dash {n} as {fname}")

    def test_the_card_case(self):
        key = "sk" + "‐" + "ant-" + R[:28]
        self.assertEqual(redact.scrub(f"use {key} now"), "use [redacted api-key] now")
        self.assertEqual(redact.scrub("use sk" + "–" + R[:30] + " now"), "use [redacted api-key] now")

    def test_mixed_forms_in_one_key_and_with_an_invisible_character(self):
        key = "sk" + "–" + "ant" + "−" + R[:28]
        self.assertEqual(redact.scrub(key), "[redacted api-key]")
        self.assertEqual(redact.scrub("sk" + "​" + "‐" + "ant-" + R[:28]), "[redacted api-key]")
        self.assertEqual(redact.scrub("sk" + "‐" + "​" + "ant-" + R[:14] + "‮" + R[14:28]), "[redacted api-key]")

    def test_the_words_around_a_masked_key_keep_their_own_dashes(self):
        en = "–"
        text = f"pages 3{en}5 and the key sk{en}ant{en}{R[:28]} {en} end of the report 2026{en}11{en}07"
        self.assertEqual(redact.scrub(text), f"pages 3{en}5 and the key [redacted api-key] {en} end of the report 2026{en}11{en}07")

    def test_a_key_after_a_great_many_dashes_is_not_shifted(self):
        en = "–"
        out = redact.scrub((en * 1500) + " sk" + en + "ant-" + R[:28] + " end")
        self.assertTrue(out.endswith(" [redacted api-key] end"))
        self.assertEqual(out.count(en), 1500)


class OrdinaryTextIsNeverRewritten(unittest.TestCase):
    ORDINARY = [
        "pages 3–5", "2026–11–07 nightly run", "the em dash — like this — in a sentence", "a minus sign: −5 degrees and 3 − 2 = 1",
        "sk–learn is a library", "sk‐learn‐pipeline‐for‐the‐model‐build‐2026", "the task–queue–implementation–notes card",
        "risk–assessment–of–the–deployment–plan", "x–api–key: some words here", "client–secret=get_secret_from_vault()",
        "・゠ katakana", "wave 1〜5 range", "fullwidth － dash", "ask–user–question–about–something–long–here",
        "commit 3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a – fixed", "Authorization: Bearer unauthorised–deletion planned",
    ]

    def test_none_of_it_changes(self):
        for text in self.ORDINARY:
            self.assertEqual(redact.scrub(text), text, repr(text))

    def test_the_same_ordinary_words_with_plain_hyphens_also_stay(self):
        for text in self.ORDINARY:
            plain = text.translate(redact._DASHES)
            self.assertEqual(redact.scrub(plain), plain, repr(plain))


class TheSetIsSound(unittest.TestCase):
    def test_every_unicode_dash_punctuation_character_is_folded(self):
        missing = [hex(i) for i in range(0x110000) if unicodedata.category(chr(i)) == "Pd" and chr(i) != "-" and i not in redact._DASHES]
        self.assertEqual(missing, [], "a new dash in this Python's Unicode data: add it to _DASH_RANGES")

    def test_what_it_folds_is_not_ascii_and_not_invisible_and_maps_to_a_plain_hyphen(self):
        self.assertTrue(redact._DASHES)
        for cp, to in redact._DASHES.items():
            self.assertEqual(to, "-")
            self.assertGreater(cp, 0x7F, hex(cp))
            self.assertFalse(redact._INVISIBLE.match(chr(cp)), hex(cp))

    def test_the_forms_in_this_test_are_all_in_the_set(self):
        for name, cp in FORMS.items():
            self.assertIn(cp, redact._DASHES, name)
        self.assertNotIn(0x2D, redact._DASHES)          # the plain hyphen needs no fold
        for cp in (0x5F, 0x2E, 0x3D, 0x3A):             # nothing else that a key is made of
            self.assertNotIn(cp, redact._DASHES)


class StillFast(Mixin, unittest.TestCase):
    def test_hostile_amounts_of_dashes(self):
        en = "–"
        for name, text in (("only en dashes", en * 1_000_000), ("sk and an en dash", ("sk" + en) * 250_000), ("prose with dashes", ("word " + en + " word ") * 100_000),
                           ("key split by dashes", ("ke" + en + "y=" + "a" * 19 + " ") * 25_000)):
            self.assertFast(redact.scrub, 3.0, text, msg=name)   # 3 s idle; tests/timing.py stretches it with the load and retries

    def test_the_bound_still_applies(self):
        out = redact.scrub("word " * 100 + "–" * 10, bound=50)
        self.assertLessEqual(len(out), 50)


class WhereItMatters(unittest.TestCase):
    def test_the_store_and_the_card_id(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            k = "sk" + "‐" + "ant" + "–" + R[:28]
            t, _ = s.start_card(f"started with {k}", "AGENT-1", description=f"d {k}")
            self.assertEqual(t["title"], "started with [redacted api-key]")
            self.assertEqual(t["description"], "d [redacted api-key]")
            self.assertNotIn("q3z7", t["id"])
            self.assertNotIn("q3Z7k9M2", (s.dir / "tasks.json").read_text())

    def test_the_terminal_tab(self):
        raw = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the key is sk‑ant‑" + R[:28]}]}})
        self.assertEqual(transcript.parse_line(raw)[0]["text"], "the key is [redacted api-key]")

    def test_the_audit_command_finds_one_that_is_already_stored(self):
        data = {"tasks": [{"id": "c", "title": "t", "description": "sk−ant−" + R[:28], "log": []}], "chat": []}
        hits = redact.scrub_data(data, None)
        self.assertEqual([(w, k) for w, k, _h in hits], [("card c description", "api-key")])


if __name__ == "__main__":
    unittest.main()
