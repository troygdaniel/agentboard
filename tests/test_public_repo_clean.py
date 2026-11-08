"""The public repo stays free of secrets, real phone numbers, real emails, home paths and the owner's private words (sec-data-public-repo-guard).
The scanner is tests/publiccheck.py; run it by hand before a push with: python3 tests/publiccheck.py"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publiccheck as pc   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCANNER = Path(pc.__file__)

# Every fake below is assembled from pieces, so this file never contains one whole (and the scan of this repo stays clean).
AWS = "AK" + "IA" + "Q3Z7K9M2P5R8T1V4"
SK = "sk" + "-" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2"
GH = "gh" + "p_" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
SLACK = "xo" + "xb-" + "1234567890-abcdefghij"
TWILIO = "A" + "C" + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e"
PKEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
AUTH = "Authorization: Token " + "q3Z7k9M2p5R8t1V4w6Y0a2C4"
ASSIGNED = 'api_key = "' + "q3Z7k9M2p5R8t1V4w6Y0a2C4" + '"'
HEX40 = "token: " + "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a"
PHONE = "(" + "212" + ") " + "867" + "-" + "4410"
PHONE2 = "+1" + "6135554321"
EMAIL = "some" + "one" + "@" + "corp" + ".test"
HOME = "/Users/" + "jsmith" + "/dev/x"


def kinds(text, words=()):
    return {k for _n, k, _s in pc.scan_text(text, words)}


class TheRepoItself(unittest.TestCase):
    def test_nothing_private_is_committed(self):
        found = pc.scan(ROOT)
        if found is None:
            self.skipTest("not a git checkout")
        self.assertEqual(found, [], "\n".join(f"{f}:{n}: {k} ({s})" for f, n, k, s in found))


class TheScannerSeesEachKind(unittest.TestCase):
    def test_secret_shapes(self):
        for text, kind in ((AWS, "aws-key"), (SK, "api-key (sk-)"), (GH, "github-token"), (SLACK, "slack-token"), (TWILIO, "twilio-id"),
                           (PKEY, "private-key"), (AUTH, "auth-header"), (ASSIGNED, "assigned-secret"), (HEX40, "key-word + 40 hex")):
            self.assertIn(kind, kinds(f"x = 1  # {text}  trailing"), kind)

    def test_phone_numbers_that_could_be_real(self):
        self.assertEqual(kinds(f"call {PHONE}"), {"phone number"})
        self.assertEqual(kinds(f"call {PHONE2}"), {"phone number"})

    def test_an_email_outside_the_allow_list(self):
        self.assertEqual(kinds(f"mail {EMAIL}"), {"email address"})

    def test_the_home_path_of_a_real_account(self):
        self.assertEqual(kinds(f"cd {HOME}"), {"home path of a real account"})

    def test_private_words_from_the_list(self):
        words = [__import__("re").compile("zebra.?crossing", __import__("re").I)]
        self.assertEqual(kinds("we met at the Zebra Crossing", words), {"private word"})
        self.assertEqual(kinds("we met at the lights", words), set())


class AndLeavesTheHarmlessAlone(unittest.TestCase):
    def test_placeholders_and_fakes(self):
        for text in ("sk-...", "sk-" + "x" * 30, "Authorization: Token $TOKEN", "Authorization: Bearer <token>", "Authorization: Token {token}",
                     'api_key = "your-api-key-goes-here"', 'password = "changeme-changeme"', "ACb" + "b" * 31, "AC" + "0" * 32,
                     "AKIA" + "EXAMPLE" + "EXAMPLE12", "token: " + "a" * 40):
            self.assertEqual(kinds(text), set(), text)

    def test_plain_words_that_contain_a_key_prefix_or_follow_an_authorization_header(self):
        for text in ("the task-queue-implementation-notes card", "risk-assessment-of-the-deployment-plan", "disk-backup-job-with-a-long-name-here", "sk-learn-pipeline-for-the-model-build-2026",
                     "Authorization: Bearer unauthorised-deletion planned", "Authorization: Basic authentication-scheme-description", "monkey: " + "3f9a1c7e5b2d4f6a" + "8c0e1b3d5f7a9c2e4b6d8f0a"):
            self.assertEqual(kinds(text), set(), text)

    def test_but_a_generated_looking_value_is_still_flagged(self):
        for text in ("Authorization: Bearer " + "q3Z7k9M2p5R8t1V4w6Y0a2C4", "Authorization: Basic " + "dXNlcjpwYXNzd29yZA==", "sk" + "-" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2"):
            self.assertTrue(kinds(text), text)

    def test_fictional_phone_numbers(self):
        for text in ("416-555-0123", "(212) 555 0123", "+1 416 555 0123", "+14165550123", "555-123-4567", "1 212 555 0199", "416-867-" + "5310", "(212) 867-" + "5309"):   # the last two in pieces: real-looking, so the repo scan (agentboard doctor) must not see them whole
            self.assertEqual(kinds(text), set(), text)

    def test_numbers_that_only_look_like_phones(self):
        for text in ("epoch 1730900000 ok", "id 12345678901234", "v1.2.3.4567", "version 2026-11-07-1234"):
            self.assertEqual(kinds(text), set(), text)

    def test_allowed_emails_and_placeholder_home_paths(self):
        for text in ("t@example.com", "git@github.com:troygdaniel/agentboard.git", "noreply@anthropic.com", "a@b.example.org",
                     "/Users/you/project", "/home/user/x", "/Users/<you>/x", "/Users/alice/dev"):
            self.assertEqual(kinds(text), set(), text)


class TheMaskNeverRevealsWhatItFound(unittest.TestCase):
    def test_a_finding_shows_four_characters_and_a_length(self):
        for secret in (AWS, SK, GH, SLACK, TWILIO, PHONE, EMAIL):
            for _n, _k, sample in pc.scan_text(f"here: {secret}"):
                self.assertNotIn(secret, sample)
                self.assertLessEqual(len(sample), 24)


class InAScratchRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.git = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True, env=env)
        self.git("init", "-q")

    def commit(self, name, text):
        (self.root / name).write_text(text)
        self.git("add", name)

    def test_a_clean_repo_passes_and_a_dirty_one_fails_with_its_locations(self):
        self.commit("ok.md", "just words\nand a fake 416-555-0123\n")
        self.assertEqual(pc.scan(self.root, words=[]), [])
        self.commit("bad.py", f"line one\nKEY = '{AWS}'\ncall = '{PHONE}'\nmail = '{EMAIL}'\nwhere = '{HOME}'\n")
        got = pc.scan(self.root, words=[])
        self.assertEqual({(f, n, k) for f, n, k, _s in got},
                         {("bad.py", 2, "aws-key"), ("bad.py", 3, "phone number"), ("bad.py", 4, "email address"), ("bad.py", 5, "home path of a real account")})

    def test_the_command_exits_1_and_prints_no_secret(self):
        self.commit("bad.py", f"KEY = '{AWS}'\ncall = '{PHONE}'\n")
        r = subprocess.run([sys.executable, str(SCANNER), str(self.root)], capture_output=True, text=True,
                           env={**os.environ, "AGENTBOARD_PRIVATE_WORDS": str(self.root / "none.txt")})
        self.assertEqual(r.returncode, 1)
        self.assertIn("bad.py:1: aws-key", r.stdout)
        for secret in (AWS, PHONE):
            self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertIn("private words file not found", r.stdout)

    def test_the_command_exits_0_on_a_clean_repo(self):
        self.commit("ok.md", "nothing here\n")
        r = subprocess.run([sys.executable, str(SCANNER), str(self.root)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_untracked_binary_and_image_files_are_not_scanned(self):
        (self.root / "untracked.txt").write_text(AWS)           # not added: not part of what gets pushed
        (self.root / "pic.png").write_bytes(AWS.encode())
        (self.root / "blob.bin").write_bytes(b"\0\0" + AWS.encode())
        self.git("add", "pic.png", "blob.bin")
        self.assertEqual(pc.scan(self.root, words=[]), [])

    def test_a_folder_that_is_not_a_repo_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(pc.scan(Path(d), words=[]))


class ThePrivateWordsFileLivesOutsideTheRepo(unittest.TestCase):
    def test_words_come_from_the_file_named_by_the_environment(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "words.txt"
            f.write_text("# my words\n\nzebra.?crossing\n(unclosed\n")
            with mock.patch.dict(os.environ, {"AGENTBOARD_PRIVATE_WORDS": str(f)}):
                words = pc.private_words()
            self.assertEqual(len(words), 2)                          # the comment and the blank line are skipped
            self.assertTrue(words[0].search("Zebra Crossing"))
            self.assertTrue(words[1].search("a (unclosed paren"))     # a bad regex is taken literally, never a crash

    def test_no_file_means_no_words_and_no_error(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_PRIVATE_WORDS": "/nonexistent/words.txt"}):
            self.assertEqual(pc.private_words(), [])


if __name__ == "__main__":
    unittest.main()
