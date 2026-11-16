"""Chat archive (card retro-chat-archive, docs/insights-design.md capture 9). With [insights] on, every chat line the store posts is appended, as posted, to
.agentboard/chat-archive/chat-YYYY-MM-DD.jsonl, and counts.json keeps lines per day and sender; the live file still holds its last CHAT_MAX lines. Part 1: the
store on a throwaway board (the cap is patched small so the suite stays quick). Part 2: the archive module on made-up lines with the counts worked out by hand.
Part 3: nothing on the board reads the archive and the module reaches no process or network. Nothing here touches a real board."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import chatarchive, selfcheck, store
from agentboard.store import Store

SRC = Path(chatarchive.__file__).parent


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
        self.archive = self.s.dir / chatarchive.DIR

    def turn_on(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text("[insights]\nenabled = true\n")

    def clock(self, *stamps):
        """The store's clock answers these stamps in turn (and keeps the last one)."""
        it = iter(stamps)
        last = [stamps[-1]]

        def now():
            try:
                last[0] = next(it)
            except StopIteration:
                pass
            return last[0]
        p = mock.patch("agentboard.store._now", now)
        p.start()
        self.addCleanup(p.stop)

    def live(self):
        return self.s.chat_list(limit=100000)


class TheStoreArchives(Base):
    def test_off_by_default_nothing_is_written(self):
        self.s.chat_send("AGENT-1", "hello")
        self.assertFalse(self.archive.exists())

    def test_every_line_past_the_cap_is_kept_as_posted(self):
        self.turn_on()
        with mock.patch.object(store, "CHAT_MAX", 20):
            sent = [self.s.chat_send("AGENT-1", f"line {i}", detail="the rest" if i == 1 else None) for i in range(1, 26)]
        self.assertEqual(len(self.live()), 20)                      # the live file is capped
        self.assertEqual(self.live()[0]["seq"], 6)
        kept = chatarchive.read(self.s.dir)
        self.assertEqual([m["seq"] for m in kept], list(range(1, 26)))   # the archive has all 25
        self.assertEqual(kept[0], sent[0])                          # the first line, fallen off the live file, as it was posted
        self.assertEqual(kept[0]["detail"], "the rest")
        self.assertEqual(sorted(p.name for p in self.archive.iterdir()), ["chat-2026-11-15.jsonl", "counts.json"] if kept[0]["at"][:10] == "2026-11-15"
                         else [f"chat-{kept[0]['at'][:10]}.jsonl", "counts.json"])

    def test_counts_per_day_and_sender_match_a_hand_count(self):
        self.turn_on()
        self.clock("2026-11-14T09:00:00", "2026-11-14T09:05:00", "2026-11-14T23:59:59", "2026-11-15T00:00:01")
        self.s.chat_send("A", "one")
        self.s.chat_send("A", "two")
        self.s.chat_send("B", "three")
        self.s.chat_send("B", "four")
        self.assertEqual(chatarchive.counts(self.s.dir), {"2026-11-14": {"A": 2, "B": 1}, "2026-11-15": {"B": 1}})
        self.assertEqual(len((self.archive / "chat-2026-11-14.jsonl").read_text().splitlines()), 3)   # one file a day
        self.assertEqual(len((self.archive / "chat-2026-11-15.jsonl").read_text().splitlines()), 1)
        self.assertEqual([m["text"] for m in chatarchive.read(self.s.dir, "2026-11-15")], ["four"])
        self.assertEqual(json.loads((self.archive / chatarchive.COUNTS).read_text())["last_seq"], 4)

    def test_the_owner_line_is_counted_under_the_owner(self):
        self.turn_on()
        self.s.chat_send(self.s.owner, "hi all", "user")
        self.assertEqual(list(chatarchive.counts(self.s.dir).values()), [{self.s.owner: 1}])

    def test_the_first_archive_copies_what_the_live_file_still_holds(self):
        self.s.chat_send("A", "before the flag")
        self.s.chat_send("A", "also before")
        self.turn_on()
        self.s.chat_send("B", "first with the flag on")
        self.assertEqual([m["text"] for m in chatarchive.read(self.s.dir)], ["before the flag", "also before", "first with the flag on"])

    def test_a_failed_archive_write_never_fails_a_post(self):
        self.turn_on()
        self.s.dir.mkdir(parents=True, exist_ok=True)
        self.archive.write_text("a file where the folder should be")
        m = self.s.chat_send("A", "still posted")
        self.assertEqual(self.live()[-1]["seq"], m["seq"])
        self.assertEqual(self.live()[-1]["text"], "still posted")

    def test_a_later_change_to_the_live_line_stays_on_the_live_line(self):
        self.turn_on()
        m = self.s.chat_send("A", "do the thing", propose="do the thing")
        self.s.chat_decide(m["seq"], "approved")
        self.assertEqual(self.live()[-1]["action"]["status"], "approved")
        self.assertEqual(chatarchive.read(self.s.dir)[-1]["action"]["status"], "proposed")   # the archive is the line as sent


class TheModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def line(self, seq, sender="A", at="2026-11-14T10:00:00", **kw):
        return dict({"seq": seq, "at": at, "sender": sender, "text": f"line {seq}", "kind": "agent"}, **kw)

    def test_a_line_is_never_archived_twice(self):
        live = [self.line(1), self.line(2)]
        self.assertEqual(chatarchive.append(self.d, live), 2)
        self.assertEqual(chatarchive.append(self.d, live), 0)
        live.append(self.line(3, "B"))
        self.assertEqual(chatarchive.append(self.d, live), 1)
        self.assertEqual([m["seq"] for m in chatarchive.read(self.d)], [1, 2, 3])
        self.assertEqual(chatarchive.counts(self.d), {"2026-11-14": {"A": 2, "B": 1}})

    def test_numbers_that_went_back_start_again_from_the_line_just_posted(self):
        chatarchive.append(self.d, [self.line(50)])
        self.assertEqual(chatarchive.append(self.d, [self.line(2), self.line(3)]), 1)   # a restore to an older snapshot
        self.assertEqual([m["seq"] for m in chatarchive.read(self.d)], [50, 3])
        self.assertEqual(json.loads((self.d / chatarchive.DIR / chatarchive.COUNTS).read_text())["last_seq"], 3)

    def test_a_broken_counts_file_or_a_stray_line_does_not_stop_it(self):
        (self.d / chatarchive.DIR).mkdir()
        (self.d / chatarchive.DIR / chatarchive.COUNTS).write_text("not json")
        (self.d / chatarchive.DIR / "chat-2026-11-14.jsonl").write_text("not json either\n")
        self.assertEqual(chatarchive.append(self.d, [self.line(1), {"no": "seq"}, "not a dict"]), 1)
        self.assertEqual([m["seq"] for m in chatarchive.read(self.d)], [1])
        self.assertEqual(chatarchive.counts(self.d), {"2026-11-14": {"A": 1}})

    def test_an_empty_board_has_empty_counts(self):
        self.assertEqual(chatarchive.counts(self.d), {})
        self.assertEqual(chatarchive.read(self.d), [])
        self.assertEqual(chatarchive.append(self.d, []), 0)


class NothingOnTheBoardReadsIt(unittest.TestCase):
    def test_only_the_store_imports_the_module_and_only_to_write(self):
        users = {p.name for p in SRC.glob("*.py") if re.search(r"\bchatarchive\b", p.read_text()) and p.name != "chatarchive.py"}
        self.assertEqual(users, {"store.py"})
        text = (SRC / "store.py").read_text()
        self.assertIn("chatarchive.append(", text)
        self.assertNotIn("chatarchive.read(", text)
        self.assertNotIn("chatarchive.counts(", text)
        for name in ("lookup.py", "server.py", "cli.py", "agentchat.py"):
            self.assertNotIn(chatarchive.DIR, (SRC / name).read_text())

    def test_the_module_reaches_no_process_or_network(self):
        text = (SRC / "chatarchive.py").read_text()
        imported = set(re.findall(r"^(?:from|import)\s+(\S+)", text, re.M))
        self.assertEqual(imported & (selfcheck.NETWORK_MODULES | selfcheck.PROCESS_MODULES), set())
        self.assertEqual(imported, {"json", "pathlib", "."})   # "." is the package's own backup.write_atomic


if __name__ == "__main__":
    unittest.main()
