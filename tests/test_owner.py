"""The human's name is the board's setting, not the code's: [board] owner in config.toml, "you" until it is set."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import agentchat, cli, hooks, prompt, runs, summary, voice
from agentboard.server import make_handler
from agentboard.store import DEFAULT_OWNER, Store, owner_name


class OwnerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)

    def conf(self, text):
        (self.s.dir / "config.toml").write_text(text)


class NameTests(OwnerTestCase):
    def test_the_owner_is_you_until_the_config_says_otherwise(self):
        self.assertEqual((DEFAULT_OWNER, self.s.owner), ("you", "you"))
        self.conf('[board]\nowner = "Alex"\n')
        self.assertEqual(self.s.owner, "Alex")   # read fresh: no restart after editing the config

    def test_a_bad_value_falls_back_to_you(self):
        for text in ('[board]\nowner = ""\n', "[board]\nowner = 5\n", '[board]\nowner = "  "\n', "[board\nowner =", 'owner = "top-level is not it"\n', "board = 3\n"):
            self.conf(text)
            self.assertEqual(owner_name(self.s.dir), "you", text)

    def test_a_long_name_is_cut(self):
        self.conf('[board]\nowner = "' + "x" * 80 + '"\n')
        self.assertEqual(len(self.s.owner), 40)


class StoreUsesItTests(OwnerTestCase):
    def test_what_the_owner_does_is_logged_under_their_name(self):
        self.conf('[board]\nowner = "Alex"\n')
        self.s.start("Ask me", "atlas")
        self.s.ask("ask-me", "Which port?")
        self.assertEqual(self.s.reply("ask-me", "8080")["log"][-1]["by"], "Alex")
        self.assertEqual(self.s.answer("ask-me")["by"], "Alex")
        self.assertEqual(self.s.edit("ask-me", title="Ask me now")["log"][-1]["by"], "Alex")
        self.s.review("ask-me", "done")
        sent = self.s.send_back("ask-me", "change the colour")
        self.assertEqual((sent["reply"]["by"], sent["log"][-1]["by"]), ("Alex", "Alex"))

    def test_the_default_name_is_you(self):
        self.s.start("Ask me", "atlas")
        self.assertEqual(self.s.reply("ask-me", "ok")["log"][-1]["by"], "you")

    def test_chat_switch_and_decisions_are_the_owners(self):
        self.conf('[board]\nowner = "Alex"\n')
        self.s.set_chat_agents(True)
        self.assertEqual(self.s.chat_list()[0]["sender"], "Alex")
        m = self.s.chat_send("AGENT-1", "may I?", propose="deploy to staging")
        self.assertEqual(self.s.chat_decide(m["seq"], "approved")["action"]["by"], "Alex")


class ElsewhereTests(OwnerTestCase):
    def test_the_hook_never_files_the_owner_as_an_agent_session(self):
        self.conf('[board]\nowner = "Alex"\n')
        self.assertIsNone(hooks.remember_session(self.s.dir, "Alex", session_id="s1"))
        hooks.remember_session(self.s.dir, "AGENT-1", session_id="s2")
        self.assertEqual(list(hooks.read_sessions(self.s.dir)), ["s2"])

    def test_the_summary_chips_and_trims_the_owners_name(self):
        self.assertEqual(summary.one_line("Alex: reinstall it", owner="Alex"), "reinstall it")
        self.assertIn('class="who-chip">Alex<', summary._inline("Alex: look", "Alex"))

    def test_the_voice_hints_carry_the_owner_and_the_boards_own_words(self):
        self.assertNotIn("Alex", voice.vocab(self.s.dir))
        self.conf('[board]\nowner = "Alex"\n[voice]\nwords = ["Acme", "Zed"]\n')
        self.assertTrue(voice.vocab(self.s.dir).endswith(", Alex, Acme, Zed"))
        self.conf('[board]\nowner = "Alex"\n[voice]\nwords = 7\n')
        self.assertTrue(voice.vocab(self.s.dir).endswith(", Alex"))


class PageGetsItTests(OwnerTestCase):
    def get(self, path):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": f"localhost:{port}"})
            return json.loads(urllib.request.urlopen(req, timeout=5).read())
        finally:
            srv.shutdown()

    def test_config_and_hud_carry_the_owner_and_the_hud_ranks_their_asks_first(self):
        self.assertEqual(self.get("/api/config")["owner"], "you")
        self.conf('[board]\nowner = "Alex"\n')
        self.s.start("A", "atlas")
        self.s.review("a", "ACTION AGENT-2: add the field | STATUS a done-ready")
        self.s.start("B", "bolt")
        self.s.review("b", "ACTION Alex: look at it | STATUS b done-ready")
        self.assertEqual(self.get("/api/config")["owner"], "Alex")
        hud = self.get("/api/hud")
        self.assertEqual(hud["owner"], "Alex")
        self.assertEqual([(a["who"], a["id"]) for a in hud["actions"]], [("Alex", "b"), ("AGENT-2", "a")])


class PromptTests(OwnerTestCase):
    """Every prompt names the board's owner; a board with none says "the user", and no placeholder is ever left in the text."""
    def texts(self):
        self.s.add("Plain card", status="todo")
        self.s.add("Parent card", status="todo")
        self.s.claim("parent-card", "alice")
        self.s.add("Child card", parent_id="parent-card")
        tasks = self.s.load()
        out = {card: prompt.build_prompt(Store.get(tasks, card), self.s.dir, tasks=tasks)[0] for card in ("plain-card", "parent-card", "child-card")}
        out["orch"] = prompt.build_orch_prompt(tasks, self.s.dir)
        out["instructions"] = prompt.say(cli.INSTRUCTIONS, self.s.dir)
        out["run"] = runs.build_run_prompt(Store.get(tasks, "plain-card"), self.s.dir, tasks, "RUN-1", 2, 10)
        self.s.set_chat_agents(True)
        out["protocol"] = agentchat.protocol(self.s.dir, "AGENT-1")
        out["orch-protocol"] = agentchat.ORCH_PROTOCOL.format(ab="ab", owner=prompt.owner_ref(self.s.dir))
        out["voice"] = agentchat.VOICE.format(owner=prompt.owner_ref(self.s.dir))
        return out

    def test_a_named_owner_is_in_every_prompt(self):
        self.conf('[board]\nowner = "Alex"\n')
        texts = self.texts()
        for name, text in texts.items():
            with self.subTest(name):
                self.assertIn("Alex", text)
                self.assertNotIn("the user's own", text)
                self.assertNotIn("{owner}", text)
                self.assertNotIn("{Owner}", text)
        self.assertIn("Report to Alex in one sentence, one idea: the ACTION they must take first", texts["plain-card"])
        self.assertIn("Alex answers on the card", texts["plain-card"])
        self.assertIn("Never without Alex's own words", texts["orch"])
        self.assertIn("with Alex watching", texts["protocol"])

    def test_without_an_owner_the_prompts_say_the_user(self):
        for name, text in self.texts().items():
            with self.subTest(name):
                self.assertNotIn("{owner}", text)
                self.assertNotIn("{Owner}", text)
                self.assertNotIn("Alex", text)
        self.assertIn("The user answers on the card", self.texts()["plain-card"])

    def test_a_custom_template_may_use_the_owner_too(self):
        self.conf('[board]\nowner = "Alex"\n[prompt]\ntemplate = "Do {title}; tell {owner}. {Owner} reads it."\n')
        self.s.add("Mine", status="todo")
        self.assertEqual(prompt.build_prompt(Store.get(self.s.load(), "mine"), self.s.dir)[0], "Do Mine; tell Alex. Alex reads it.")

    def test_no_prompt_is_left_with_a_pronoun_for_a_named_person(self):
        self.conf('[board]\nowner = "Alex"\n')
        for name, text in self.texts().items():
            for pronoun in (" he ", " him ", " his "):
                self.assertNotIn(pronoun, text, name)

    def test_the_board_text_names_the_owner_on_a_report(self):
        from agentboard import reports
        self.conf('[board]\nowner = "Alex"\n')
        self.s.start("Quiet", "atlas")
        task = dict(Store.get(self.s.load(), "quiet"), status_text="", result="", question="")
        self.assertIn("Nothing was written for Alex.", reports.build_html(task, self.s.dir))


class SourceTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_the_source_names_nobody(self):
        """Nothing under src/ may name the board's author: the name comes from [board] owner."""
        hits = [str(p.relative_to(self.ROOT)) for p in (self.ROOT / "src").rglob("*") if p.is_file() and p.suffix in (".py", ".html", ".js", ".css", ".md", ".toml")
                and "troy" in p.read_text(errors="ignore").lower()]
        self.assertEqual(hits, [])


class PageSourceTests(unittest.TestCase):
    PAGE = (Path(__file__).resolve().parent.parent / "src" / "agentboard" / "static" / "index.html").read_text()

    def test_the_page_names_nobody(self):
        self.assertNotIn("Troy", self.PAGE)
        self.assertIn("let OWNER = 'you';", self.PAGE)
        self.assertIn("OWNER = c.owner || OWNER;", self.PAGE)   # /api/config
        self.assertIn("OWNER = d.owner || OWNER;", self.PAGE)   # /api/hud (the pop-out page too)


if __name__ == "__main__":
    unittest.main()
