"""The masker sees through fullwidth look-alikes (low-core-masker-fullwidth-lookalikes): a fullwidth underscore in a ghp_ key, a fullwidth "=" after
api_key, a fullwidth ":" after token, or fullwidth letters in an AKIA key passed through whole, because the patterns want ASCII. It now also folds
the fullwidth block (U+FF01 to U+FF5E) to ASCII on the matching copy, one for one, and masks the original by span, so ordinary text that uses it
(Japanese and Chinese punctuation, fullwidth words) is never rewritten."""
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

from agentboard import redact, transcript
from timing import Mixin
from agentboard.store import Store

# Fakes are assembled from pieces so this file never holds a whole one.
R = "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
SHAPES = {
    "aws": "AK" + "IA" + "Q3Z7K9M2P5R8T1V4", "sk-ant": "sk" + "-ant-" + R[:28], "sk": "sk" + "-" + R[:40], "github": "gh" + "p_" + R,
    "slack": "xo" + "xb-" + "12345" + "67890-abcdefghij", "account": "A" + "C" + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e", "stripe": "sk" + "_live_" + R[:24],
    "google": "AI" + "za" + "SyA-" + R[:31], "npm": "np" + "m_" + R[:36], "sendgrid": "S" + "G." + R[:22] + "." + R[14:36],
    "hook": "https://hooks" + ".slack.com/services/" + "T0123ABCD" + "/" + "B0123ABCD" + "/" + R[:24],
    "jwt": "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "auth header": "Authorization: Bearer " + R[:24], "bearer": "Bearer " + R[:24], "assigned": "api_key = " + R[:24], "assigned no spaces": "api_key=" + R[:24],
    "client secret": "client_secret: " + R[:24], "key-hex": "token: " + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a", "generic": "token=" + R[:24],
    "url password": "postgres://admin:" + "s3cr3t" + "Pw" + "@" + "db.internal/app", "pem line": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


def fw(text, only=None):
    """text with its printable ASCII (not the space) turned into the fullwidth forms: every character, or only the one at index `only`."""
    return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E and (only is None or i == only) else c for i, c in enumerate(text))


def unfw(text):
    return "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in text)


class EveryShapeSurvivesFullwidthForms(unittest.TestCase):
    def test_the_cases_from_the_card(self):
        self.assertEqual(redact.scrub("gh" + "p＿" + R), "[redacted github-token]")
        self.assertEqual(redact.scrub("api_key＝" + R[:24]), "api_key=[redacted secret]")
        self.assertEqual(redact.scrub("token： " + R[:24]), "token: [redacted secret]")
        self.assertEqual(redact.scrub(fw("AK" + "IA") + "Q3Z7K9M2P5R8T1V4"), "[redacted aws-key]")

    def test_each_shape_written_wholly_in_fullwidth(self):
        for name, secret in SHAPES.items():
            want = redact.scrub(secret)
            self.assertNotEqual(want, secret, name)
            self.assertEqual(unfw(redact.scrub(fw(secret))), want, name)

    def test_each_shape_with_a_fullwidth_character_at_every_position(self):
        for name, secret in SHAPES.items():
            want = redact.scrub(secret)
            for i, c in enumerate(secret):
                if not 0x21 <= ord(c) <= 0x7E:
                    continue
                self.assertEqual(unfw(redact.scrub(fw(secret, only=i))), want, f"{name}: character {i} ({c!r}) fullwidth")

    def test_mixed_with_look_alike_dashes_and_invisible_characters(self):
        self.assertEqual(redact.scrub("sk" + "–" + fw("ant") + "－" + R[:28]), "[redacted api-key]")
        self.assertEqual(redact.scrub("gh" + "​" + "p＿" + R[:20] + "‮" + R[20:]), "[redacted github-token]")
        self.assertEqual(redact.scrub("Authorization：​ Bearer " + R[:24]), "Authorization: Bearer [redacted secret]")

    def test_the_words_around_a_masked_key_keep_their_own_forms(self):
        text = "パスワード（仮） — key " + "gh" + "p＿" + R + " ！ end ？"
        self.assertEqual(redact.scrub(text), "パスワード（仮） — key [redacted github-token] ！ end ？")

    def test_a_key_after_a_great_many_fullwidth_characters_is_not_shifted(self):
        out = redact.scrub(("Ａ" * 1500) + " gh" + "p＿" + R + " end")
        self.assertTrue(out.endswith(" [redacted github-token] end"))
        self.assertEqual(out.count("Ａ"), 1500)


class OrdinaryTextIsNeverRewritten(unittest.TestCase):
    ORDINARY = [
        "こんにちは，世界！　テスト：完了（仮）", "日本語で書く？ 「引用」を使う",
        "price ＄５０ and ０１２３", "ＡＢＣ ａｂｃ fullwidth words", "ｔａｓｋ－ｑｕｅｕｅ－ｉｍｐｌｅｍｅｎｔａｔｉｏｎ－ｎｏｔｅｓ",
        "ｋｅｙ＝ｖａｌｕｅ", "ｔｏｋｅｎ： some-long-kebab-case-identifier-here", "ａｐｉ＿ｋｅｙ = os.environ",
        "Is the backup tested？", "密码：已重置，请查收", "commit 3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a， fixed",
        "ＩＤ： 12345", "ｋｅｙ： 一二三",
    ]

    def test_none_of_it_changes(self):
        for text in self.ORDINARY:
            self.assertEqual(redact.scrub(text), text, repr(text))


class TheSetIsSound(unittest.TestCase):
    def test_the_fold_is_what_unicode_normalisation_does(self):
        for cp in range(0xFF01, 0xFF5F):
            self.assertEqual(redact._FOLD[cp], unicodedata.normalize("NFKC", chr(cp)), hex(cp))
        self.assertEqual(len([c for c in redact._FOLD if 0xFF01 <= c <= 0xFF5E]), 94)

    def test_everything_folded_is_one_character_to_one_character_and_ascii_or_a_hyphen(self):
        for cp, to in redact._FOLD.items():
            self.assertEqual(len(to), 1)
            self.assertGreater(cp, 0x7F, hex(cp))
            self.assertTrue(0x21 <= ord(to) <= 0x7E, hex(cp))
            self.assertFalse(redact._INVISIBLE.match(chr(cp)), hex(cp))

    def test_the_dashes_still_fold_and_the_two_tables_agree(self):
        for cp in redact._DASHES:
            self.assertEqual(redact._FOLD[cp], "-", hex(cp))
        self.assertEqual(redact._FOLD[0xFF0D], "-")

    def test_what_it_leaves_alone(self):
        for cp in (0x3000, 0x3001, 0x3002, 0x300C, 0x30FB, 0xFF5F, 0xFF65, 0xFFE0):          # ideographic space and punctuation, halfwidth forms, fullwidth signs
            self.assertNotIn(cp, redact._FOLD, hex(cp))


class StillFast(Mixin, unittest.TestCase):
    def test_hostile_amounts_of_fullwidth_text(self):
        for name, text in (("only fullwidth", "Ａ" * 1_000_000), ("gh and a fullwidth underscore", ("gh" + "p＿") * 250_000), ("fullwidth prose", ("ｗｏｒｄ " * 200_000)),
                           ("key split by fullwidth", ("keｙ＝" + "a" * 19 + " ") * 25_000)):
            self.assertFast(redact.scrub, 3.0, text, msg=name)   # 3 s idle; tests/timing.py stretches it with the load and retries

    def test_the_bound_still_applies(self):
        out = redact.scrub("word " * 100 + "Ａ" * 10, bound=50)
        self.assertLessEqual(len(out), 50)


class WhereItMatters(unittest.TestCase):
    def test_the_store_and_the_card_id(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            k = "gh" + "p＿" + R
            t, _ = s.start_card(f"started with {k}", "AGENT-1", description=f"d {k}")
            self.assertEqual(t["title"], "started with [redacted github-token]")
            self.assertEqual(t["description"], "d [redacted github-token]")
            self.assertNotIn("q3z7", t["id"])
            self.assertNotIn("q3Z7k9M2", (s.dir / "tasks.json").read_text())

    def test_the_terminal_tab(self):
        raw = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the key is " + fw("AK" + "IA") + "Q3Z7K9M2P5R8T1V4"}]}})
        self.assertEqual(transcript.parse_line(raw)[0]["text"], "the key is [redacted aws-key]")

    def test_the_audit_command_finds_one_that_is_already_stored(self):
        data = {"tasks": [{"id": "c", "title": "t", "description": "api_key＝" + R[:24], "log": []}], "chat": []}
        hits = redact.scrub_data(data, None)
        self.assertEqual([(w, k) for w, k, _h in hits], [("card c description", "assigned-secret")])


if __name__ == "__main__":
    unittest.main()
