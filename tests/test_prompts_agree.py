"""Every agent-facing text is built from one source (rules.py), and no text contradicts another (overnight-agent-prompts, Nov 7).

The texts: `agentboard instructions`, the card prompt (plain, subtask, parent, made from a text), the unattended run prompt, the ORCH boot prompt, the
agent-chat protocol, the board's own announcement when agent chat is switched on, the Stop hook's messages, the line `answer --wait` prints, the idle
drafter's prompts, and this repo's own CLAUDE.md. The tests generate all of them (with the board's owner called "you", the default, and with a
two-word name) and check that the shared rules are there word for word, that the numbers agree, that the rules that differ do so on purpose, and that
none of them says what another forbids."""
import contextlib
import io
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from agentboard import agentchat, cli, hooks, prompt, rules, runs
from agentboard.store import Store

ROOT = Path(__file__).resolve().parent.parent
STOP = {"session_id": "sid-agree"}


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


class Texts:
    """Every text, for one board."""

    def __init__(self, owner=None, chat_on=True):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / ".agentboard"
        self.dir.mkdir()
        if owner:
            (self.dir / "config.toml").write_text(f'[board]\nowner = "{owner}"\n')
        self.s = Store(self.dir)
        s = self.s
        s.add("Plain card", "Do the plain thing.", "todo", task_id="plain")
        s.add("Big card", "Do the big thing.", "todo", task_id="big")
        s.add("Part one", "", "todo", task_id="part", parent_id="big")
        s.add("Part two", "", "todo", task_id="part2", parent_id="big")
        s.add("From a text", "words", "todo", task_id="texted", source={"kind": "text", "key": "k1", "sid": "k1", "at": "2026-11-07T10:00:00+00:00"})
        if chat_on:
            s.set_chat_agents(True)
        tasks = s.load()
        self.ab = prompt.agentboard_cmd(self.dir)
        self.me = '"<your session name>"'
        card = lambda tid, **kw: prompt.build_prompt(s.get(tasks, tid), self.dir, tasks=tasks, **kw)[0]   # noqa: E731
        self.texts = {
            "instructions": prompt.say(cli.INSTRUCTIONS, self.dir),
            "card-plain": card("plain"), "card-subtask": card("part"), "card-parent": card("big"), "card-text": card("texted"),
            "run-plain": runs.build_run_prompt(s.get(tasks, "plain"), self.dir, tasks, "oneshot", 5, 30),
            "run-parent": runs.build_run_prompt(s.get(tasks, "big"), self.dir, tasks, "oneshot", 5, 30),
            "orch": prompt.build_orch_prompt(tasks, self.dir),
            "chat-protocol": agentchat.protocol(self.dir, "AGENT-1"),
            "chat-orch": prompt.say(agentchat.ORCH_PROTOCOL.format(ab=self.ab, owner="{owner}"), self.dir),
            "announcement": " ".join(m["text"] for m in s.chat_list() if m.get("via") == "board"),
            "idle-draft": agentchat.DRAFT_PROMPT.format(name="AGENT-1", owner=prompt.owner_ref(self.dir), voice=agentchat.VOICE.format(owner=prompt.owner_ref(self.dir)),
                                                        today="today", inbox="-", memory="-"),
            "idle-share": agentchat.SHARE_PROMPT.format(name="AGENT-1", owner=prompt.owner_ref(self.dir), voice=agentchat.VOICE.format(owner=prompt.owner_ref(self.dir)),
                                                        today="today", memory="-", doing="-", chat="-"),
        }
        self.texts.update(self.hook_messages())
        self.name_of = {k: k for k in self.texts}

    def hook_messages(self):
        """The Stop hook's three messages: an unread line, a line the wait printed but the session did not act on, and no wait running."""
        out = {}
        env = dict(os.environ)
        os.environ["AGENTBOARD_NAME"] = "AGENT-4"
        try:
            from agentboard import cursors, listeners
            out["hook-silent"] = hooks.stop_decision(self.s, STOP)["reason"]                # nothing unread, no wait running
            m = self.s.chat_send(self.s.owner, "hello?", kind="user", to="AGENT-4")
            out["hook-unread"] = hooks.stop_decision(self.s, STOP)["reason"]
            cursors.deliver(self.s.dir, "AGENT-4", m["seq"])
            listeners.register(self.s.dir, "AGENT-4", "inbox")
            out["hook-delivered"] = hooks.stop_decision(self.s, STOP)["reason"]
        finally:
            os.environ.clear()
            os.environ.update(env)
        return out

    def close(self):
        self.tmp.cleanup()


class Base(unittest.TestCase):
    OWNER = None

    @classmethod
    def setUpClass(cls):
        cls._env = dict(os.environ)
        for k in [k for k in os.environ if k.startswith("AGENTBOARD_")]:
            del os.environ[k]
        cls.t = Texts(cls.OWNER)

    @classmethod
    def tearDownClass(cls):
        cls.t.close()
        os.environ.clear()
        os.environ.update(cls._env)

    def say(self, text):
        return prompt.say(text, self.t.dir)

    def agent_texts(self):
        """The texts an attended agent reads as rules."""
        return {k: v for k, v in self.t.texts.items() if k in ("instructions", "card-plain", "card-subtask", "card-parent", "card-text")}


class OneSource(Base):
    def test_the_reporting_rule_is_the_same_words_in_every_prompt_that_carries_it(self):
        want = squash(self.say(rules.REPORT_TEXT))
        for name in ("instructions", "card-plain", "card-subtask", "card-parent", "card-text", "run-plain", "run-parent", "orch"):
            self.assertIn(want, squash(self.t.texts[name]), name)

    def test_finishing_and_waiting_is_the_same_words_in_every_attended_prompt(self):
        for name, card, ab in (("card-plain", "plain", self.t.ab), ("card-subtask", "big", self.t.ab), ("card-parent", "big", self.t.ab),
                               ("instructions", '"$ID"', "agentboard")):
            text = squash(self.t.texts[name])
            self.assertIn(squash(self.say(rules.wake(ab, card, self.t.me, "review"))), text, name)
            self.assertIn(squash(self.say(rules.reachable(ab, self.t.me))), text, name)
            self.assertIn(squash(self.say(rules.never_done(ab, card))), text, name)

    def test_after_an_ask_the_same_wait_is_said_short(self):
        for name, card, ab in (("card-plain", "plain", self.t.ab), ("instructions", '"$ID"', "agentboard")):
            self.assertIn(squash(self.say(rules.wake(ab, card, self.t.me, "ask"))), squash(self.t.texts[name]), name)

    def test_the_working_rules_are_in_every_attended_prompt_and_the_run_prompt_has_its_own_version(self):
        for name in self.agent_texts():
            self.assertIn(squash(self.say(rules.working_rules())), squash(self.t.texts[name]), name)
        for name in ("run-plain", "run-parent"):
            self.assertIn(squash(self.say(rules.working_rules(unattended=True))), squash(self.t.texts[name]), name)
            self.assertNotIn("git worktree add", self.t.texts[name], "a one-shot run is already in a worktree the board made")

    def test_the_four_lessons_are_all_there(self):
        for name, text in self.agent_texts().items():
            for lesson in ("do not claim a card because it sits in Todo", "never edit the main checkout", "never use `git stash`", "Do not use `--force`", "Never put a backtick"):
                self.assertIn(lesson, text, f"{name}: {lesson}")
        orch = squash(self.t.texts["orch"])
        self.assertIn(squash(rules.ORCH_ONE_ID), orch)                       # ORCH marks done: one id each time

    def test_orch_waits_and_answers_with_the_shared_commands(self):
        orch = self.t.texts["orch"]
        self.assertIn(rules.inbox_wait_cmd(self.t.ab, "ORCH"), orch)
        self.assertIn(rules.reply_cmd(self.t.ab, "ORCH", self.t.s.owner), orch)

    def test_the_hook_and_the_answer_command_use_the_shared_commands(self):
        src = (ROOT / "src" / "agentboard" / "hooks.py").read_text()
        for literal in ("--wait 3600", 'chat send \\"<one line>\\"', "chat send \"<one line>\""):
            self.assertNotIn(literal, src, "the Stop hook builds its commands from rules.py")
        self.assertIn(rules.inbox_wait_cmd("agentboard", "AGENT-4"), self.t.texts["hook-unread"])
        self.assertIn(rules.inbox_wait_cmd("agentboard", "AGENT-4"), self.t.texts["hook-delivered"])
        cli_src = (ROOT / "src" / "agentboard" / "cli.py").read_text()
        self.assertIn("rules.reply_cmd('agentboard', name, s.owner, reply_to=msgs[-1]['seq'])", cli_src)

    def test_no_other_module_hard_codes_a_wait_length(self):
        for path in (ROOT / "src" / "agentboard").glob("*.py"):
            if path.name == "rules.py":
                continue
            text = path.read_text()
            self.assertEqual(re.findall(r"--wait \d{2,}|--timeout 3600", text), [], path.name)


class NumbersAgree(Base):
    def test_every_wait_in_every_text_is_one_length(self):
        waits = {}
        for name, text in self.t.texts.items():
            for n in re.findall(r"chat inbox --name \S+ --wait (\d+)", text) + re.findall(r"answer \S+ --wait --timeout (\d+)", text):
                waits.setdefault(int(n), []).append(name)
        self.assertEqual(list(waits), [rules.WAIT_S], waits)
        self.assertTrue(len(waits[rules.WAIT_S]) > 8)                         # and it is in plenty of them

    def test_the_old_lengths_are_gone_everywhere(self):
        for name, text in self.t.texts.items():
            self.assertNotRegex(text, r"--wait (120|300)\b", name)


class NoContradiction(Base):
    def test_an_unattended_run_is_never_told_to_wait_and_an_attended_agent_never_to_just_stop(self):
        for name in ("run-plain", "run-parent"):
            text = self.t.texts[name]
            self.assertNotIn("run_in_background", text, name)
            self.assertNotRegex(text, r"answer \S+ --wait", name)
            self.assertNotIn("chat inbox", text, name)
            self.assertIn("after `review`, stop", text, name)
            self.assertIn("this run does not wait", text, name)                # the repo's CLAUDE.md says wait: the run prompt says so out loud
        for name, text in self.agent_texts().items():
            self.assertNotRegex(text, r"review[^\n.]{0,60}\band stop\b", name)
            self.assertNotIn("unattended", text, name)
            self.assertIn("run_in_background", text, name)

    def test_force_is_only_ever_mentioned_to_be_refused(self):
        for name, text in self.t.texts.items():
            for line in text.splitlines():
                if "--force" in line:
                    self.assertRegex(line, r"(?i)do not use .?--force|not use --force|never", f"{name}: {line.strip()[:90]}")

    def test_marking_done_is_only_ever_for_the_owners_say_so(self):
        for name, text in self.t.texts.items():
            for line in text.splitlines():
                if re.search(r"agentboard done\b", line) and name != "orch":
                    self.assertRegex(line, r"ONLY|never|Never|NEVER|only", f"{name}: {line.strip()[:90]}")
        for name, text in self.agent_texts().items():
            self.assertNotRegex(text, r"(?i)you (may|can) (mark|run)[^.\n]*done", name)

    def test_no_text_calls_the_human_two_words_in_a_command(self):
        """`--to the user` is two words and the command refuses it: the command word is the board's name for the human (`you`, or the owner, quoted)."""
        for name, text in self.t.texts.items():
            self.assertNotIn("--to the user", text, name)
        for name in ("instructions", "card-plain", "card-parent", "orch", "hook-unread", "hook-delivered"):
            for to in re.findall(r"--to ('[^']+'|[\w-]+)", self.t.texts[name]):
                self.assertNotEqual(to, "the", name)
                self.assertRegex(to, r"^('[^']+'|[A-Za-z0-9_-]+)$", name)

    def test_the_idle_drafters_carry_no_protocol_of_their_own(self):
        for name in ("idle-draft", "idle-share"):
            text = self.t.texts[name]
            for banned in ("agentboard done", "--force", "run_in_background", "chat inbox"):
                self.assertNotIn(banned, text, name)
            self.assertIn("approve", text, name)                                # "never propose spending ... the owner must approve it first"

    def test_the_board_announcement_names_the_same_wait(self):
        self.assertIn(rules.inbox_wait_cmd("agentboard", "<you>"), self.t.texts["announcement"])


class TheRepoClaudeMd(unittest.TestCase):
    def test_this_repos_claude_md_carries_the_current_instructions_word_for_word(self):
        md = squash((ROOT / "CLAUDE.md").read_text())
        wanted = squash(prompt.say(cli.INSTRUCTIONS, None))
        self.assertIn(wanted, md, "CLAUDE.md drifted from `agentboard instructions`: regenerate its shared sections (everything before 'This repo is public')")

    def test_it_keeps_the_repo_only_sections_after_them(self):
        text = (ROOT / "CLAUDE.md").read_text()
        self.assertLess(text.index("## Looking things up"), text.index("## This repo is public"))
        self.assertIn("## Verifying UI changes", text)


class WithATwoWordOwner(NoContradiction, NumbersAgree, OneSource):
    OWNER = "Sam Jones"

    def test_the_command_word_is_quoted_and_the_prose_is_the_name(self):
        self.assertIn("--to 'Sam Jones'", self.t.texts["instructions"])
        self.assertIn("--to 'Sam Jones'", self.t.texts["card-plain"])
        self.assertIn("Sam Jones wrote to you", self.t.texts["hook-unread"])
        self.assertIn("--to 'Sam Jones'", self.t.texts["hook-unread"])


class WithTheDefaultOwner(Base):
    def test_the_command_word_is_you_and_the_prose_is_the_user(self):
        self.assertIn("--to you --reply-to <the line's number>`", self.t.texts["card-plain"])
        self.assertIn("The board's owner wrote to you", self.t.texts["hook-unread"])
        self.assertRegex(self.t.texts["hook-unread"], r"--to you --reply-to \d+")
        self.assertNotIn("you wrote to you", self.t.texts["hook-unread"])


class EachRuleOnce(Base):
    def test_no_shared_paragraph_appears_twice_in_one_prompt(self):
        """The old card prompt said the wake-and-wait rule three times in three wordings; now each shared paragraph is in a prompt once."""
        for name in ("card-plain", "card-subtask", "card-parent", "run-plain", "instructions"):
            text = squash(self.t.texts[name])
            for what, para in (("report", rules.REPORT_TEXT), ("working rules", rules.working_rules()), ("reachable", rules.reachable(self.t.ab, self.t.me))):
                self.assertLessEqual(text.count(squash(self.say(para))), 1, f"{name}: {what}")
            self.assertLessEqual(text.count("do not sit idle"), 1, name)
            self.assertLessEqual(text.count("Between cards, and any other time"), 1, name)


if __name__ == "__main__":
    unittest.main()
