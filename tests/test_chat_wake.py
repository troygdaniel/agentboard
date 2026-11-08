"""chat-f7: ORCH listens like every agent and a wait wakes within two seconds of a line. Every chat_send moves .agentboard/chat-wake.json;
`chat inbox --wait` sleeps on that file (a stat a second, a full read every ten seconds as a net) so a fake ORCH session wakes within 2 s;
a schedule can stat the file instead of holding a wait; the panel says "nobody is listening as X" for ORCH and any agent."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from agentboard import chatwake, listeners, prompt

from test_mirror import Base

SRC = str(Path(__file__).resolve().parents[1] / "src")


class TheWakeFile(Base):
    def test_every_posted_line_moves_it_and_it_holds_no_words(self):
        n0 = chatwake.count(self.s.dir)   # (the test base's "agent chat is on" line already moved it once)
        self.s.chat_send(self.s.owner, "a private question", kind="user", to="ORCH")
        self.s.chat_send("AGENT-2", "status line")
        self.assertEqual(chatwake.count(self.s.dir), n0 + 2)
        raw = chatwake.path(self.s.dir).read_text()
        self.assertNotIn("private", raw)
        self.assertNotIn("status", raw)
        self.assertEqual(json.loads(raw)["to"], "all")
        chatwake.path(self.s.dir).write_text("{{{")
        self.assertEqual(chatwake.count(self.s.dir), 0)   # a broken file reads as zero and the next line replaces it
        self.s.chat_send("AGENT-2", "again")
        self.assertEqual(chatwake.count(self.s.dir), 1)

    def test_sleep_until_change_returns_the_moment_the_file_moves_or_after_the_net(self):
        clock = {"t": 0.0}
        slept, bumped = [], []

        def sleep(n):
            slept.append(n)
            clock["t"] += n
            if len(slept) == 3 and not bumped:
                bumped.append(True)
                chatwake.bump(self.s.dir, "ORCH")
        self.assertTrue(chatwake.sleep_until_change(self.s.dir, 1.0, 10.0, sleep=sleep, clock=lambda: clock["t"]))
        self.assertEqual(slept, [1.0, 1.0, 1.0])
        slept.clear()
        self.assertFalse(chatwake.sleep_until_change(self.s.dir, 1.0, 3.5, sleep=sleep, clock=lambda: clock["t"]))
        self.assertAlmostEqual(sum(slept), 3.5)


class AFakeOrchWakesWithinTwoSeconds(Base):
    def test_the_wait_registers_as_orch_and_returns_within_two_seconds_of_a_line(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        (self.root / "home").mkdir(exist_ok=True)
        env.update({"PYTHONPATH": SRC, "AGENTBOARD_DIR": str(self.s.dir), "HOME": str(self.root / "home"), "PYTHONDONTWRITEBYTECODE": "1"})
        self.run_cli("chat", "inbox", "--name", "ORCH")   # the test base's "agent chat is on" line is read first, so the wait has nothing until our line
        pr = subprocess.Popen([sys.executable, "-m", "agentboard", "chat", "inbox", "--name", "ORCH", "--wait", "30"], env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: pr.poll() is None and pr.kill())
        deadline = time.time() + 20
        while time.time() < deadline and not listeners.is_listening(self.s.dir, "ORCH"):
            time.sleep(0.05)
        self.assertTrue(listeners.is_listening(self.s.dir, "ORCH"), "the wait never registered as ORCH")
        time.sleep(0.3)
        t0 = time.monotonic()
        self.s.chat_send(self.s.owner, "ORCH, anyone free?", kind="user", to="ORCH")
        out, _ = pr.communicate(timeout=15)
        took = time.monotonic() - t0
        self.assertEqual(pr.returncode, 0, out)
        self.assertIn("anyone free?", out)
        self.assertLess(took, 2.0, f"woke after {took:.2f} s")
        self.assertFalse(listeners.is_listening(self.s.dir, "ORCH"))   # the wait has ended: the panel will say nobody is listening

    def test_a_line_to_a_stopped_wait_gets_the_nudge_that_moves_the_wake_file(self):
        m = self.s.chat_send(self.s.owner, "still there?", kind="user", to="ORCH")
        before = chatwake.count(self.s.dir)
        self.assertIsNone(self.s.chat_nudge(m["seq"]))
        self.assertEqual(chatwake.count(self.s.dir), before + 1)


class ThePromptAndThePage(unittest.TestCase):
    def test_the_orch_prompt_names_the_wake_file_and_the_nudge_to_itself(self):
        t = prompt.ORCH_TEMPLATE
        self.assertIn("chat inbox --name ORCH --wait 3600", t)
        self.assertIn(".agentboard/chat-wake.json", t)
        self.assertIn("stat that file each time you fire", t)
        self.assertIn("A line to you that nobody was listening for shows {owner} a Nudge too", t)

    def test_the_panel_says_nobody_is_listening_for_orch_and_any_agent(self):
        html = (Path(SRC) / "agentboard" / "static" / "index.html").read_text()
        self.assertIn("warn = orch ? `Nobody is listening for ORCH: it reads the board at its next check.` : `Nobody is listening for ${to}.`;", html)
        self.assertIn("${orch ? 'Nudge' : 'Nudge via ORCH'}</button>", html)
        self.assertIn("${orch ? 'nudged' : 'ORCH asked'}", html)
        self.assertNotIn("Type in its terminal, or boot one with Copy prompt", html)
        self.assertIn("d.message && !d.orch_listening", html)


if __name__ == "__main__":
    unittest.main()
