"""Every way text gets into the board is masked (sec2-start-not-masked): `agentboard start` is how every agent begins a card and it skipped the
masker, so the key landed in the title, the description, the card id (a slug of the title), report file names and later history lines.
This test runs every write path with a key-shaped value and looks at every byte the board keeps."""
import contextlib
import gzip
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, hooks, reports
from agentboard.store import Store

# Fakes are assembled from pieces so this file never holds a whole one.
KEYS = ["AK" + "IA" + "Q3Z7K9M2P5R8T1V4", "sk" + "-ant-" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8", "gh" + "p_" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"]
SECRET_CORES = ["Q3Z7K9M2P5R8T1V4", "q3Z7k9M2p5R8t1V4w6Y0"]        # what must not survive anywhere, in any case


class Board:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def close(self):
        self.tmp.cleanup()

    def every_byte(self):
        """tasks.json, its .bak, each snapshot and each report, lower-cased too (card ids are slugs)."""
        d = self.s.dir
        out = [(d / "tasks.json").read_text()]
        for name in ("tasks.json.bak",):
            if (d / name).exists():
                out.append((d / name).read_text())
        for g in (d / "backups").glob("*.gz"):
            out.append(gzip.decompress(g.read_bytes()).decode())
        for r in (d / "reports").glob("*.html"):
            out += [r.read_text(), r.name]
        text = "\n".join(out)
        return text + "\n" + text.lower()


class EveryWritePath(unittest.TestCase):
    def setUp(self):
        self.b = Board()
        self.addCleanup(self.b.close)
        self.s = self.b.s
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        env["AGENTBOARD_NAME"] = "AGENT-3"
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(list(argv))

    def assert_clean(self, where):
        data = self.b.every_byte()
        for key in KEYS:
            self.assertNotIn(key, data, f"{where}: a whole key is stored")
        for core in SECRET_CORES:
            self.assertNotIn(core, data, f"{where}: part of a key is stored")

    def test_the_repro_agentboard_start_with_a_key_in_the_title_and_description(self):
        k = KEYS[1]
        self.cli("start", f"started with {k}", "--name", "AGENT-9", "-d", f"description {k}")
        card = self.s.load()[0]
        self.assertEqual(card["title"], "started with [redacted api-key]")
        self.assertEqual(card["description"], "description [redacted api-key]")
        self.assertNotIn("q3z7", card["id"])                  # the id is a slug of the title: never of the key
        self.assert_clean("start")

    def test_start_caps_the_description_like_add_does(self):
        t, _ = self.s.start_card("Big", "AGENT-1", description="x " * 50_000)
        self.assertLessEqual(len(t["description"]), 20_000)

    def test_a_key_in_an_agents_name(self):
        self.s.start_card("A card", f"agent-{KEYS[0]}")
        self.s.add("Other", status="todo", task_id="other")
        self.s.claim("other", f"agent-{KEYS[1]}")
        self.assert_clean("agent names")

    def test_add_a_subtask_edit_update_ask_review_chat_and_the_mirror(self):
        s = self.s
        s.set_chat_agents(True)
        for i, k in enumerate(KEYS):
            tid = f"c{i}"
            s.add(f"Card {k}", f"description {k}", status="todo", task_id=tid)
            s.claim(tid, "AGENT-1")
            s.add(f"step {k}", f"sub description {k}", parent_id=tid, task_id=f"{tid}-step")
            s.edit(tid, title=f"edited {k}", description=f"edited description {k}")
            s.update(f"{tid}-step", 40, f"status {k}", body_md=f"## Body\n- {k}")
            s.ask(tid, f"question {k}", body_md=f"detail {k}")
            s.update(f"{tid}-step", 100, f"done {k}")
            s.review(tid, f"result {k}", body_md=f"## Changed\n- {k}")
            s.chat_send(f"AGENT-{k}", f"line {k}", detail=f"detail {k}", propose=f"propose {k}", files=[f"/tmp/x?key={k}"])
            hooks.mirror_send_message(s, {"tool_name": "SendMessage", "session_id": "sid-1234567", "tool_input": {"to": "ORCH", "message": f"first {k}\nsecond {k}"}})
            reports.write_report(s, tid)
        s.backups.take("matrix")
        self.assert_clean("the whole matrix")

    def test_the_mirror_does_not_cut_a_key_in_half_before_masking_it(self):
        s = self.s
        s.set_chat_agents(True)
        k = KEYS[0]
        message = "x" * 290 + k + " tail"          # the key straddles the 300-character cut of the first line
        hooks.mirror_send_message(s, {"tool_name": "SendMessage", "session_id": "sid-1234567", "tool_input": {"to": "ORCH", "message": message}})
        self.assert_clean("mirror cut")
        self.assertNotIn("AKIA", self.b.every_byte())

    def test_the_cli_paths(self):
        k = KEYS[2]
        self.cli("add", f"CLI card {k}", "-d", f"d {k}", "--status", "todo", "--id", "cli1")
        self.cli("claim", "cli1", "--name", "AGENT-3")
        self.cli("add", "sub", "--parent", "cli1", "--id", "cli1-s")
        self.cli("update", "cli1-s", "30", f"status {k}")
        self.cli("ask", "cli1", f"which {k}?")
        self.cli("review", "cli1", f"result {k}", "--body", f"## Changed\n- {k}")
        self.cli("edit", "cli1", "--title", f"new title {k}")
        self.assert_clean("cli")

    def test_older_cards_quoted_in_history_lines_are_masked_too(self):
        """A card stored before masking existed still holds a key in its title: the history line for a later edit must not copy it."""
        import json
        s = self.s
        s.add("Old card", status="todo", task_id="old")
        s.add("Blocker", status="todo", task_id="blk")
        data = json.loads(s.path.read_text())
        for t in data["tasks"]:
            t["title"] = f"old title {KEYS[0]}" if t["id"] == "old" else f"blocker {KEYS[1]}"
        s.path.write_text(json.dumps(data))
        s.edit("old", title="New title")
        s.edit("old", blocked_by=["blk"])
        log = [e["text"] for e in Store.get(s.load(), "old")["log"]]
        self.assertTrue(any("Title changed from" in t for t in log))
        self.assertFalse(any(KEYS[0] in t or KEYS[1] in t for t in log), log)

    def test_ordinary_text_goes_through_every_path_unchanged(self):
        s = self.s
        s.set_chat_agents(True)
        t, _ = s.start_card("Fix the header regression", "AGENT-1", description="commit 3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a, card ap-123")
        self.assertEqual((t["title"], t["agent"], t["description"]), ("Fix the header regression", "AGENT-1", "commit 3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a, card ap-123"))
        m = s.chat_send("AGENT-1", "heads up", propose="merge the branch", files=["src/ui/CallCard.tsx"], detail="see card ap-123")
        self.assertEqual((m["text"], (m.get("action") or {}).get("text"), m["files"]), ("heads up", "merge the branch", ["src/ui/CallCard.tsx"]))


if __name__ == "__main__":
    unittest.main()
