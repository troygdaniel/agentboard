"""The masker's second round of shapes (sec2-mask-missing-shapes): Stripe, Google, Slack webhook, npm, SendGrid, URL passwords, longer
assignment names, a bare Bearer; and the rule that ordinary text is still never touched."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publiccheck  # noqa: E402

from agentboard import redact, transcript  # noqa: E402

# Fakes are assembled from pieces so this file never holds a whole one (the repo scan stays clean).
R = "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
STRIPE = "sk" + "_live_" + R[:24]
STRIPE_R = "rk" + "_test_" + R[:24]
WHSEC = "wh" + "sec_" + R[:28]
GOOGLE = "AI" + "za" + "SyA-" + R[:31]
HOOK = "https://hooks" + ".slack.com/services/" + "T0123ABCD" + "/" + "B0123ABCD" + "/" + R[:24]
NPM = "np" + "m_" + R[:36]
SENDGRID = "S" + "G." + R[:22] + "." + R[14:36]
PASSWORD_URL = "postgres://admin:" + "s3cr3t" + "Pw" + "@" + "db.internal/app"
AWS_VALUE = "wJalrXUtnFEMI/" + "K7MDENG/bPxRf" + "iCYq3Z7k9M2p5"
UUID = "123e4567-e89b-12d3-a456-426614174000"


class EachNewShapeIsMasked(unittest.TestCase):
    def test_prefix_shaped_keys(self):
        for text, want in (
            (STRIPE, "[redacted stripe-key]"), (STRIPE_R, "[redacted stripe-key]"), (f"charge with {STRIPE} ok", "charge with [redacted stripe-key] ok"),
            (WHSEC, "[redacted webhook-secret]"),
            (GOOGLE, "[redacted google-key]"), (f"curl https://x.test/api?key={GOOGLE}", "curl https://x.test/api?key=[redacted google-key]"),
            (f"{{\"k\": \"{GOOGLE}\"}}", '{"k": "[redacted google-key]"}'),
            (HOOK, "[redacted slack-webhook]"), (HOOK.replace("https://", ""), "[redacted slack-webhook]"), (f"post to {HOOK}.", "post to [redacted slack-webhook]."),
            (NPM, "[redacted npm-token]"), (f"//registry.npmjs.org/:_authToken={NPM}", "//registry.npmjs.org/:_authToken=[redacted npm-token]"),
            (SENDGRID, "[redacted sendgrid-key]"), (f"SENDGRID_API_KEY={SENDGRID}", "SENDGRID_API_KEY=[redacted sendgrid-key]"),
        ):
            self.assertEqual(redact.scrub(text), want, text[:40])

    def test_a_password_in_a_url_goes_and_the_rest_stays(self):
        self.assertEqual(redact.scrub(PASSWORD_URL), "postgres://admin:[redacted password]@db.internal/app")
        self.assertEqual(redact.scrub("https://user:hunter22@example.org/x?a=1"), "https://user:[redacted password]@example.org/x?a=1")
        self.assertEqual(redact.scrub("mongodb+srv://u:p4ss@cluster0.example.net/db"), "mongodb+srv://u:[redacted password]@cluster0.example.net/db")
        self.assertEqual(redact.scrub(f"clone {PASSWORD_URL} now"), "clone postgres://admin:[redacted password]@db.internal/app now")

    def test_longer_assignment_names(self):
        for text, want in (
            (f"aws_secret_access_key = {AWS_VALUE}", "aws_secret_access_key = [redacted secret]"),
            (f"AWS_VALUE_ACCESS_KEY={AWS_VALUE}", "AWS_VALUE_ACCESS_KEY=[redacted secret]"),
            (f"secret_access_key: {AWS_VALUE}", "secret_access_key: [redacted secret]"),
            (f"client_secret={R[:24]}", "client_secret=[redacted secret]"),
            (f"refresh_token = {R[:30]}", "refresh_token = [redacted secret]"),
            (f"x-api-key: {R[:24]}", "x-api-key: [redacted secret]"),
            (f"APIKEY={R[:24]}", "APIKEY=[redacted secret]"),
        ):
            self.assertEqual(redact.scrub(text), want, text[:40])

    def test_the_generic_names_key_auth_token_in_a_url_or_an_assignment(self):
        for text, want in (
            (f"https://x.test/api?key={R[:24]}&q=1", "https://x.test/api?key=[redacted secret]&q=1"),
            (f"?auth={R[:24]}", "?auth=[redacted secret]"), (f"token: {R[:24]}", "token: [redacted secret]"), (f"credentials = '{R[:24]}'", "credentials = '[redacted secret]'"),
            (f"access_key={R[:24]}", "access_key=[redacted secret]"), (f"token={UUID}", "token=[redacted secret]"),
        ):
            self.assertEqual(redact.scrub(text), want, text[:40])

    def test_a_bare_bearer_token(self):
        self.assertEqual(redact.scrub(f"curl -H 'Bearer {R[:24]}'"), "curl -H 'Bearer [redacted secret]'")
        self.assertEqual(redact.scrub(f"Bearer {R[:20]}=="), "Bearer [redacted secret]")

    def test_each_one_is_masked_once_and_stays_masked(self):
        for text in (STRIPE, GOOGLE, HOOK, NPM, SENDGRID, PASSWORD_URL, f"aws_secret_access_key = {AWS_VALUE}", f"Bearer {R[:24]}"):
            once = redact.scrub(text)
            self.assertEqual(redact.scrub(once), once, text[:30])

    def test_the_terminal_tab_masks_them_too(self):
        raw = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": f"curl https://x.test/api?key={GOOGLE}"}]}})
        self.assertEqual(transcript.parse_line(raw)[0]["text"], "curl https://x.test/api?key=[redacted google-key]")
        raw = json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": f"psql {PASSWORD_URL}"}}]}})
        self.assertEqual(transcript.parse_line(raw)[0]["text"], "Bash psql postgres://admin:[redacted password]@db.internal/app")


class OrdinaryTextIsStillNeverTouched(unittest.TestCase):
    ORDINARY = [
        "the key idea is simple", "key: value pairs", "key=value", "auth=true", "token=abc", "?key=true&debug=1", "a primary key = 12345", "the auth flow and the token budget",
        "cache key = user_profile_cache_v2_final_version", "token: some-long-kebab-case-identifier-here", "api_key = os.environ['X']", "secret = get_secret_from_vault()",
        "Bearer tokens are used here", "Bearer authentication-scheme-description", "Bearer of bad news", "monkey=12345678901234567890", "turkey=Thanksgiving2026Dinner",
        "http://localhost:8765/api/tasks", "https://github.com/org/repo@v1", "git@github.com:org/repo.git", "ssh://git@github.com/org/repo.git", "http://user@host/path",
        "postgres://user:password@localhost/db", "scheme://user:pass@host", "https://user:***@host", "https://user:xxxx@host", "https://user:<password>@host", "https://user:${DB_PASS}@host",
        "sk_live_ and rk_test_ are the prefixes", "AIza is how a Google key starts", "npm_ tokens start with npm_", "SG. then two parts", "hooks.slack.com is Slack's webhook host",
        "risk_test_runner_for_the_deploy_pipeline_stage", "task_live_dashboard_for_the_ops_team_view", "commit 3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a on /Users/you/x",
        "call 416-555-0123", "fixed card ap-123", "Bundle 412kb -> 271kb", "see https://example.org/path?id=12345&ref=abc#top",
    ]

    def test_none_of_it_changes(self):
        for text in self.ORDINARY:
            self.assertEqual(redact.scrub(text), text, text[:50])


class TheRepoGuardKnowsThemToo(unittest.TestCase):
    def test_the_same_new_shapes_would_be_flagged_in_the_repo(self):
        for text in (STRIPE, GOOGLE, NPM, SENDGRID, HOOK):
            self.assertTrue(publiccheck.scan_text(text), text[:20])


if __name__ == "__main__":
    unittest.main()
