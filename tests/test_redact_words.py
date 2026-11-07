"""The masker never erases ordinary words (sec2-mask-hides-words): masking happens on the way into the store, so what it removes is gone for
good, and an agent (or text it relays) could hide a word from the owner. The Authorization shape masked ANY 10+ character word after
"Authorization: Bearer|Basic|Token"; the sk- shape masked the tail of kebab-case words (task-queue-... became ta[redacted api-key]); a key
block with no END line ran to the end of the text."""
import unittest

from agentboard import redact
from agentboard.store import Store

import tempfile
from pathlib import Path

# Fakes are assembled from pieces so this file never holds a whole one.
R = "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
HEX40 = "3f9a1c7e5b2d4f6a" + "8c0e1b3d5f7a9c2e4b6d8f0a"
BEGIN, END = "-----BEGIN " + "RSA PRIVATE KEY-----", "-----END " + "RSA PRIVATE KEY-----"
BODY = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu"


class TheAuthorizationShape(unittest.TestCase):
    def test_the_words_from_the_card_survive(self):
        for text in ("Authorization: Basic unauthorised-deletion about the deploy", "Authorization: Bearer unauthorised-deletion planned",
                     "Authorization: Token the-quarterly-compliance-review done"):
            self.assertEqual(redact.scrub(text), text)

    def test_plain_words_and_phrases_after_the_header_are_not_tokens(self):
        for word in ("authentication-scheme-description", "unauthorised-deletion", "configuration-management", "implementation_details_here", "documentation.md.old.copy", "tokens-are-required",
                     "short", "authorized"):
            text = f"Authorization: Bearer {word} was discussed"
            self.assertEqual(redact.scrub(text), text, word)

    def test_real_tokens_are_still_masked(self):
        for value in ("3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a", "dXNlcjpwYXNzd29yZA==", R[:24], "AbCdEfGhIjKlMnOpQrStUvWxYz", "abc123def456ghi789",
                      "q3Z7k9M2p5R8t1V4w6Y0a2C4.e6G8i0K2m4O6s8U1", "eyJhbGciOiJIUzI1NiJ9"):
            for scheme in ("Bearer", "Basic", "Token"):
                self.assertEqual(redact.scrub(f"Authorization: {scheme} {value} next"), f"Authorization: {scheme} [redacted secret] next", f"{scheme} {value}")

    def test_the_words_around_a_masked_token_stay(self):
        self.assertEqual(redact.scrub(f"retry with Authorization: Bearer {R[:24]} about the deploy"), "retry with Authorization: Bearer [redacted secret] about the deploy")


class TheSkShapeAndKebabCaseWords(unittest.TestCase):
    ORDINARY = [
        "the task-queue-implementation-notes card", "risk-assessment-of-the-deployment-plan", "disk-backup-job-with-a-long-name-here", "ask-user-question-about-something-long",
        "desk-research-notes-for-the-new-board", "flask-application-factory-pattern-notes", "risk-assessment-2026-plan-final-version", "task-2026-11-07-nightly-report-generation",
        "sk-learn-pipeline-for-the-model-build-2026", "card id ask-user-question-about-something-long is open", "card ids: agentboard-task-text-to-agents, sec2-mask-hides-words",
        "tasks-with-a-very-long-descriptive-kebab-case-name-and-1-digit",
    ]

    def test_none_of_it_changes(self):
        for text in self.ORDINARY:
            self.assertEqual(redact.scrub(text), text, text)

    def test_real_keys_are_still_masked(self):
        for key in ("sk" + "-ant-" + R[:28], "sk" + "-proj-" + R[:28], "sk" + "-" + R[:40], "sk" + "-" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"):
            self.assertEqual(redact.scrub(f"use {key} now"), "use [redacted api-key] now", key[:12])

    def test_a_key_glued_to_other_text_is_still_found(self):
        key = "AK" + "IA" + "Q3Z7K9M2P5R8T1V4"
        for text in (f"x{key}", f"key{key}end", f"KEY={key}", f"({key})"):
            self.assertNotIn("AKIA", redact.scrub(text), text)
        self.assertNotIn("sk-ant", redact.scrub("x" + "sk" + "-ant-" + R[:28]))      # a prefix letter is not an escape hatch


class TheKeyHexAndTheKeyBlock(unittest.TestCase):
    def test_key_hex_does_not_start_inside_a_longer_word(self):
        self.assertEqual(redact.scrub(f"monkey: {HEX40}"), f"monkey: {HEX40}")
        self.assertEqual(redact.scrub(f"key: {HEX40}"), "key: [redacted hex]")

    def test_a_cut_off_key_block_masks_its_body_and_not_the_sentences_after_it(self):
        self.assertEqual(redact.scrub(f"{BEGIN} then an ordinary sentence that must stay readable."), "[redacted private-key] then an ordinary sentence that must stay readable.")
        self.assertEqual(redact.scrub(f"cut off\n{BEGIN}\n{BODY}\n{BODY[:20]}\nThen the explanation follows."), "cut off\n[redacted private-key]\nThen the explanation follows.")

    def test_a_whole_block_goes_to_its_end_line_whatever_is_inside(self):
        self.assertEqual(redact.scrub(f"before\n{BEGIN}\n{BODY}\n{BODY}\n{END}\nafter"), "before\n[redacted private-key]\nafter")
        self.assertEqual(redact.scrub(f"{BEGIN}\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,ABC\n\n{BODY}\n{END}\nafter"), "[redacted private-key]\nafter")
        self.assertEqual(redact.scrub(f"{BEGIN}\\n{BODY}\\n{END}\\nafter (json-escaped)"), "[redacted private-key]\\nafter (json-escaped)")

    def test_two_blocks_and_a_block_without_an_end_before_another(self):
        self.assertEqual(redact.scrub(f"{BEGIN}\n{BODY}\n{END} and {BEGIN}\n{BODY}\n{END}"), "[redacted private-key] and [redacted private-key]")
        self.assertEqual(redact.scrub(f"{BEGIN}\n{BODY} words {BEGIN}\n{BODY}\n{END}"), "[redacted private-key] words [redacted private-key]")


class TheOriginalIsNotLostForGood(unittest.TestCase):
    def test_the_card_text_keeps_every_word_through_the_store(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Card", status="todo", task_id="c")
            s.claim("c", "AGENT-1")
            s.add("step", parent_id="c", task_id="step")
            s.update("step", 100, "done")
            text = "Authorization: Bearer unauthorised-deletion planned; see task-queue-implementation-notes"
            s.review("c", text)
            self.assertEqual(Store.get(s.load(), "c")["result"], text)


if __name__ == "__main__":
    unittest.main()
