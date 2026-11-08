"""Five LOW findings of the Nov 7 merge review (AGENT-8), fixed on one branch: one rule for a hard-off variable (doctor-dup-env), a NUL in
a config path no longer crashes under lockdown (lockdown-nul-crash), a hex run with one dash is not words (redact-wordy-hex), three small
masker gaps (redact-small-gaps), and one stamp parser, one name resolver, one reason cap (cursor-file-dup). Throwaway boards only."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agentboard import cli, cursors, doctor, hooks, listeners, lockdown, plugins, providers, redact
from agentboard.store import Store, parse_stamp, _seconds_between


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(root / "proj" / ".agentboard")
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.s.add("seed")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()


class OneEnvRule(unittest.TestCase):
    def test_lockdown_env_on_is_the_rule_doctor_and_plugins_use(self):
        for v, want in (("1", True), ("yes", True), (" on ", True), ("", False), ("0", False), ("false", False), ("No", False)):
            self.assertEqual(lockdown.env_on("X", {"X": v}), want, v)
        self.assertFalse(lockdown.env_on("X", {}))
        self.assertEqual(doctor._env_on({"A": "1"}, "A"), True)
        self.assertFalse(hasattr(doctor, "_OFF"))
        self.assertFalse(hasattr(plugins, "_OFF"))
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": "", plugins.LOCK_ENV: "true"}):
            self.assertIn(plugins.LOCK_ENV, plugins.disabled_reason())
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": "", plugins.LOCK_ENV: "0", plugins.ENV: "0"}):
            self.assertIn(plugins.ENV, plugins.disabled_reason())


class NulInAPath(Base):
    def test_inside_project_and_doctor_survive_an_embedded_nul(self):
        self.assertFalse(providers.inside_project("a\0b", self.s.dir))
        self.assertFalse(providers.inside_project(self.s.dir.parent / "no\0tes.md", self.s.dir))
        conf = {"prompt": {"template_file": "tem\0plate.md"}, "providers": {"notes": {"type": "markdown", "path": "no\0tes.md"}}}   # a NUL cannot be written in TOML; a hand-built config stands in
        rows = doctor.config_reads(conf, self.s.dir)   # used to raise ValueError('embedded null character') and take doctor down with it
        self.assertEqual([r[2] for r in rows], [False, False])
        from agentboard import prompt
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": "1"}), mock.patch.object(prompt, "load_config", return_value=conf):
            results = doctor.run(self.s.dir, runner=lambda *a, **k: mock.Mock(returncode=1, stdout="", stderr=""))
        self.assertTrue(any(r[1] == "config" for r in results))   # the config line is there: no crash under lockdown


class WordyHex(unittest.TestCase):
    def test_a_hex_run_with_one_dash_or_dot_is_masked_and_words_are_not(self):
        for text in ("token=a1b2c3d4e5f6a7b8c9d0e1f2-a3b4c5d6", "key: a1b2c3d4.e5f6a7b8c9d0e1f2a3b4c5d6e7f8", "sk-live-0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d",
                     "token: key-0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d", "api_key=0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d"):
            out = redact.scrub(text, None)
            self.assertNotIn(text.split("=")[-1].split(": ")[-1][-12:], out, text)
        for text in ("key=task-queue-implementation-notes-v2", "token=user_profile_cache_v2_final_version", "pages 3-5 of the 2026-11-08 report, sk-learn 1.4.2",
                     "sk-learn-pipeline-for-the-model-build-2026", "risk-assessment-2026-plan-final-version"):
            self.assertEqual(redact.scrub(text, None), text, text)
        self.assertTrue(redact._wordy("user_profile_cache_v2_final"))
        self.assertTrue(redact._wordy("risk-assessment-2026-plan-final-version"))
        self.assertFalse(redact._wordy("a1b2c3d4e5f6-a3b4c5d6"))


class SmallGaps(Base):
    def test_a_zero_length_owner_pattern_does_not_duplicate_the_character_after_it(self):
        import re
        text = "ab\u200bcd"
        out = redact._sub_visible(re.compile(r"z*"), lambda m: "" if not m.group(0) else "X", text)
        self.assertEqual(out, text)
        out = redact._sub_visible(re.compile(r"(?=c)"), lambda m: "-", text)   # an insertion before c: once, and the c stays
        self.assertEqual(out, "ab\u200b-cd")

    def test_the_audit_sees_a_key_in_a_chat_lines_files_and_proposed_action(self):
        self.s.set_chat_agents(True)
        self.s.chat_send("AGENT-1", "touching the config", topic="heads-up", files=["src/app.py"], propose="deploy with key")
        data = json.loads(self.s.path.read_text())
        key = "sk-" + "A1b2" * 10
        data["chat"][-1]["files"] = [f"notes-{key}.md"]
        data["chat"][-1]["action"]["text"] = f"deploy with {key}"
        hits = redact.scrub_data(data, self.s.dir, apply=True)
        self.assertEqual(sorted(h[0] for h in hits), [f"chat #{data['chat'][-1]['seq']} action", f"chat #{data['chat'][-1]['seq']} file #1"])
        self.assertNotIn(key, json.dumps(data))

    def test_a_cut_off_pem_with_header_lines_keeps_no_body(self):
        pem = ("-----BEGIN " + "RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,A0B1C2D3E4F5A6B7C8D9E0F1A2B3C4D5\n\n"   # built from parts: the repo scan flags a whole one
               + "MIIEpAIBAAKCAQEA7x9f" * 3 + "\nQ2d0Zm9vYmFyYmF6cXV4" * 2 + "\nand then the sentence after it.")
        out = redact.scrub(pem, None)
        self.assertNotIn("MIIEpAIBAAKCAQEA7x9f", out)
        self.assertNotIn("Q2d0Zm9vYmFyYmF6cXV4", out)
        self.assertNotIn("DEK-Info", out)
        self.assertIn("and then the sentence after it.", out)

    def test_a_key_shaped_name_is_masked_before_it_reaches_sessions_listeners_and_cursors(self):
        key = "sk-" + "Z9y8" * 10
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "sess-1"}):
            self.run_cli("me", "--name", key)
            self.run_cli("claim", "seed", "--name", key)
            self.s.chat_send(self.s.owner, "hi", kind="user", to=redact.scrub(key, None))   # the owner writes to the name as the board shows it (an owner's own line is never masked)
            self.run_cli("chat", "inbox", "--name", key, "--wait", "0.3", "--interval", "0.1")
        for f in ("sessions.json", "chat-cursors.json", "chat-delivered.json", "chat-listeners.json", "tasks.json"):
            p = self.s.dir / f
            if p.exists():
                self.assertNotIn("Z9y8Z9y8", p.read_text(), f)


class OneParserOneResolverOneCap(Base):
    def test_parse_stamp_is_the_one_parser(self):
        self.assertEqual(parse_stamp("2026-11-08T01:02:03"), datetime(2026, 11, 8, 1, 2, 3))
        self.assertEqual(parse_stamp("2026-11-08T01:02:03.123"), datetime(2026, 11, 8, 1, 2, 3))
        self.assertIsNone(parse_stamp(None))
        self.assertIsNone(parse_stamp("yesterday"))
        self.assertEqual(_seconds_between("2026-11-08T01:00:00", "2026-11-08T01:01:30"), 90)
        self.assertEqual(_seconds_between("x", "2026-11-08T01:01:30"), float("inf"))
        from agentboard import agentchat, hud
        self.assertEqual(hud._t("2026-11-08T01:02:03"), datetime(2026, 11, 8, 1, 2, 3))
        self.assertEqual(agentchat._t("2026-11-08T01:02:03"), datetime(2026, 11, 8, 1, 2, 3))
        self.assertEqual(cursors._age_s("nope"), float("inf"))
        src = "".join(Path(cli.__file__).parent.joinpath(n).read_text() for n in ("cli.py", "hud.py", "agentchat.py", "cursors.py", "hooks.py", "listeners.py"))
        self.assertNotIn('strptime(', src)   # every board stamp goes through store.parse_stamp

    def test_known_name_is_resolve_sender_without_the_fallback_and_the_reason_is_cut_at_the_max(self):
        hooks.remember_session(self.s.dir, "AGENT-4", session_id="s4")
        self.assertEqual(hooks.resolve_sender(self.s.dir, {"session_id": "s4"}), "AGENT-4")
        self.assertEqual(hooks.resolve_sender(self.s.dir, {"session_id": "nope"}), "session-nope")
        self.assertIsNone(hooks.resolve_sender(self.s.dir, {"session_id": "nope"}, fallback=False))
        self.assertEqual(hooks.known_name(self.s.dir, {"session_id": "s4"}), "AGENT-4")
        self.assertIsNone(hooks.known_name(self.s.dir, {"session_id": "nope"}))
        self.s.chat_send(self.s.owner, "x" * 300, kind="user", to="AGENT-4")
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "AGENT-4"}):
            d = hooks.stop_decision(self.s, {"session_id": "s4", "stop_hook_active": False})
        self.assertLessEqual(len(d["reason"]), hooks.REASON_MAX)
        self.assertIn("chat inbox --name AGENT-4 --wait 3600", d["reason"])   # the commands still fit
