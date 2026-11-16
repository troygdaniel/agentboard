"""Night sweep (sweep-sec-data, Nov 15): every text an agent hands the store is masked for secrets on the way in (redact.py). Three side fields were not:
a card's `ctx` list (`add --ctx`), the model recorded at claim (`claim --model`, `$AGENTBOARD_MODEL`) and the `to` name on a chat line. Fakes are assembled
from pieces so this file never holds a whole one."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard.store import BoardError, Store

KEY = "sk" + "-ant-" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2"   # 39 characters of letters, digits and dashes: a model name's shape, a key's content


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

    def dump(self):
        return (self.s.dir / "tasks.json").read_text()


class TheContextList(Base):
    def test_a_ctx_entry_is_masked(self):
        t = self.s.add("A card", ctx=["file:README.md", f"note:{KEY}"])
        self.assertEqual(t["ctx"][0], "file:README.md")          # a plain provider spec is left alone
        self.assertNotIn(KEY, t["ctx"][1])
        self.assertIn("[redacted", t["ctx"][1])
        self.assertNotIn(KEY, self.dump())


class TheModelOnClaim(Base):
    def test_an_explicit_model_that_looks_like_a_key_is_refused_and_nothing_changes(self):
        t = self.s.add("A card", status="todo")
        with self.assertRaises(BoardError) as cm:
            self.s.claim(t["id"], "AGENT-1", model=KEY)
        self.assertIn("key", str(cm.exception).lower())
        again = Store.get(self.s.load(), t["id"])
        self.assertEqual(again["status"], "todo")
        self.assertIsNone(again.get("agent"))
        self.assertNotIn(KEY, self.dump())

    def test_a_key_in_the_environment_is_ignored_not_recorded(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text("[insights]\nenabled = true\n")
        t = self.s.add("A card", status="todo")
        with mock.patch.dict(os.environ, {"AGENTBOARD_MODEL": KEY}):
            got = self.s.claim(t["id"], "AGENT-1")
        self.assertIsNone(got.get("model"))
        self.assertNotIn(KEY, self.dump())

    def test_a_real_model_name_still_lands(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text("[insights]\nenabled = true\n")
        t = self.s.add("A card", status="todo")
        got = self.s.claim(t["id"], "AGENT-1", model="claude-sonnet-5-5")
        self.assertEqual(got["model"], "claude-sonnet-5-5")


class TheToName(Base):
    def setUp(self):
        super().setUp()
        self.s.set_chat_agents(True)   # a line to another agent needs the board-wide switch

    def test_the_to_name_on_a_mirrored_line_is_masked(self):
        m = self.s.chat_send("AGENT-1", "a private line, mirrored", to=KEY, via="mirror")
        self.assertNotIn(KEY, json.dumps(m))
        self.assertNotIn(KEY, self.dump())

    def test_a_plain_name_is_left_alone(self):
        self.s.chat_send("AGENT-2", "hello", to=None)
        m = self.s.chat_send("AGENT-1", "hi there", to="AGENT-2", via="mirror")
        self.assertEqual(m["to"], "AGENT-2")


if __name__ == "__main__":
    unittest.main()
