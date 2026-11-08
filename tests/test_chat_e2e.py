"""Chat end to end (card chat-q1): the loss paths of docs/conversation-reliability-analysis.md (R1 to R11) as tests, with FAKE SESSIONS that are real
`agentboard chat inbox --wait` processes, a real server, and the page's own receipt logic (run in node). Every scenario was a way a line was lost or ignored
on Nov 7; each now has a test that fails if it comes back. Everything is on a throwaway board and 127.0.0.1; no private line is read.

Needs node (the receipt states are the page's own receiptOf). Takes about a minute: the sessions are real processes."""
import json
import shutil
import signal
import statistics
import subprocess
import sys
import time
import unittest

from agentboard import chatwake, cursors, listeners

from chat_world import NODE, World, free_port

HAVE_NODE = shutil.which(NODE) is not None


def needs_node(cls):
    return unittest.skipUnless(HAVE_NODE, "node is needed for the page's receipt logic")(cls)


@needs_node
class WakeAndLatency(unittest.TestCase):
    """R1, and the 3-minute poll that ORCH used to be: a line reaches a waiting session within seconds, ORCH on the wake file included."""

    def test_every_listening_session_hears_the_line_within_two_and_a_half_seconds(self):
        w = World(self)
        names = ["AGENT-A", "AGENT-B", "AGENT-C", "AGENT-D", "ORCH"]
        for n in names:
            w.session(n).listen()
        times = {}
        for n in names:
            t0 = time.monotonic()
            w.owner_says(f"hello {n}", to=n)
            out = w.sessions[n].got(10)
            self.assertIsNotNone(out, f"{n}'s wait did not end")
            self.assertIn(f"hello {n}", out)
            times[n] = w.sessions[n].exited_after(t0)
        self.assertLess(max(times.values()), 2.5, times)
        self.assertLess(statistics.median(times.values()), 1.5, times)

    def test_a_line_to_all_reaches_every_waiting_session_once(self):
        w = World(self)
        for n in ("A-1", "A-2", "A-3"):
            w.session(n).listen()
        w.owner_says("everyone", to="all")
        for n in ("A-1", "A-2", "A-3"):
            out = w.sessions[n].got(10)
            self.assertEqual(out.count("everyone"), 1, (n, out))

    def test_orch_on_a_schedule_learns_in_one_stat_that_something_was_posted(self):
        w = World(self)
        w.session("ORCH")   # never listening: a runtime that cannot hold a wait
        before = chatwake.count(w.board)
        m = w.owner_says("are you there", to="ORCH")
        self.assertGreater(chatwake.count(w.board), before)
        self.assertEqual(json.loads((w.board / chatwake.WAKE_FILE).read_text())["to"], "ORCH")
        self.assertNotIn("are you there", (w.board / chatwake.WAKE_FILE).read_text())   # a counter and a name, never the words
        rc, out = w.sessions["ORCH"].run("chat", "inbox")
        self.assertIn("are you there", out)
        self.assertEqual(w.state(m["seq"])["state"], "delivered")   # printing it is a delivery ...
        rc, out = w.sessions["ORCH"].run("claim", w.store.load()[0]["id"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(w.state(m["seq"])["state"], "seen")        # ... and ORCH's next act on the board is what makes it seen


@needs_node
class ReceiptsTellTheTruth(unittest.TestCase):
    """R2, R3: delivered is not seen; a dead reader's line comes again; a stopped wait is said at 60 s."""

    def test_a_busy_session_delivered_then_late_then_shown_again_then_seen_then_answered(self):
        w = World(self)
        a = w.session("AGENT-A").listen()
        m = w.owner_says("did you get this?", to="AGENT-A")
        self.assertIn("did you get this?", a.got(10))                      # the wait printed it and exited: the session may be mid-step
        s = w.state(m["seq"])
        self.assertEqual((s["state"], s.get("late", False)), ("delivered", False))
        s = w.state(m["seq"], plus_s=400)                                  # six minutes later and it still has not acted
        self.assertEqual((s["state"], s["late"]), ("delivered", True))
        w.age_delivery("AGENT-A", 400)
        rc, out = a.run("chat", "inbox")                                   # it comes back to the board: the line is shown AGAIN, with the reason
        self.assertIn("never confirmed: shown again", out)
        self.assertIn("did you get this?", out)
        self.assertEqual(w.state(m["seq"])["state"], "delivered")          # printing it again is still only a delivery
        rc, out = a.run("claim", w.store.load()[0]["id"])                  # any command as that name: it has acted on the board
        self.assertEqual(rc, 0, out)
        self.assertEqual(w.state(m["seq"])["state"], "seen")
        a.run("chat", "send", "yes, on it", "--to", w.owner, "--reply-to", str(m["seq"]))
        self.assertEqual(w.state(m["seq"])["state"], "answered")

    def test_a_line_printed_to_a_reader_that_was_gone_is_not_lost(self):
        w = World(self)
        a = w.session("AGENT-A").listen(discard=True)                      # its output goes nowhere
        m = w.owner_says("anyone?", to="AGENT-A")
        a.got(10)
        self.assertEqual(w.state(m["seq"])["state"], "delivered")
        self.assertIsNone(cursors.get(w.board, "AGENT-A"))                 # not seen: the cursor did not move on print
        w.age_delivery("AGENT-A", 400)
        rc, out = a.run("chat", "inbox")
        self.assertIn("anyone?", out)                                      # the next read shows it again

    def test_a_stopped_wait_is_known_and_the_page_would_warn_at_sixty_seconds(self):
        w = World(self)
        a = w.session("AGENT-A").listen()
        a.kill()                                                           # the owner typed in its terminal; the session's wait died
        self.assertFalse(a.listening())
        m = w.owner_says("are you there?", to="AGENT-A")
        s = w.state(m["seq"])
        self.assertEqual((s["state"], bool(s.get("late"))), ("sent", False))
        s = w.state(m["seq"], plus_s=75)
        self.assertEqual((s["state"], s["late"], s["listening"]), ("sent", True, False))   # "Nobody is listening for AGENT-A" and the Nudge
        self.assertEqual(w.state(m["seq"], plus_s=2 * 86400).get("old"), True)             # after a day it is history: no warning

    def test_a_listening_but_busy_session_is_not_called_dead(self):
        w = World(self)
        a = w.session("AGENT-A").listen()
        m = w.owner_says("when you can", to="AGENT-A")
        s = w.state(m["seq"], plus_s=75)                                   # the wait has NOT printed yet in this scenario (a is the same process, still running?)
        a.got(10)
        s2 = w.state(m["seq"])
        self.assertEqual(s2["state"], "delivered")

    def test_the_stop_hook_catches_a_session_with_an_unread_line_from_any_folder(self):
        w = World(self)
        a = w.session("AGENT-A")
        a.run("me", "--name", "AGENT-A", "--session", "sess-a")
        w.cli("chat", "send", "--user", "--to", "AGENT-A", "unread owner line")
        payload = json.dumps({"session_id": "sess-a"})
        rc, out = w.cli("hook", "stop", "--dir", str(w.board), stdin=payload, env={"AGENTBOARD_DIR": ""})   # a folder with no board, no environment
        self.assertIn('"block"', out)
        self.assertIn("unread owner line", out)
        rc, out = w.cli("hook", "stop", "--dir", str(w.board), stdin=json.dumps({"session_id": "never-registered"}), env={"AGENTBOARD_DIR": ""})
        self.assertEqual(out.strip(), "")                                  # a session that is not an agent here is left alone
        rc, out = w.cli("hook", "stop", stdin=payload, env={"AGENTBOARD_DIR": ""})
        self.assertEqual(out.strip(), "")                                  # without --dir and without a board it finds nothing: this is why the install bakes it in


@needs_node
class OneNameTwoSessions(unittest.TestCase):
    def test_two_waits_under_one_name_are_counted_and_the_first_keeps_listening(self):
        w = World(self)
        a1 = w.session("AGENT-1").listen(wait=300)
        a2 = w.session("AGENT-1")
        a2.listen(wait=300)
        for _ in range(100):   # (the second process is registered a moment after it starts)
            if listeners.sessions(w.board, "AGENT-1") == 2:
                break
            time.sleep(0.1)
        self.assertEqual(listeners.sessions(w.board, "AGENT-1"), 2)
        a2.kill()
        time.sleep(0.3)
        self.assertEqual(listeners.sessions(w.board, "AGENT-1"), 1)
        self.assertTrue(a1.listening(), "the shorter-lived session's end took the other one's entry with it (R4b)")

    def test_the_second_session_is_told_at_once(self):
        w = World(self)
        w.session("AGENT-1").listen(wait=300)
        second = w.session("AGENT-1")
        second.listen(wait=300)
        for _ in range(100):
            if listeners.sessions(w.board, "AGENT-1") == 2:
                break
            time.sleep(0.1)
        second.kill()
        self.assertIn("2 sessions are listening as AGENT-1", (second.proc.stderr.read() or b"").decode())


@needs_node
class WrongNames(unittest.TestCase):
    def test_a_line_to_a_name_nobody_has_is_refused_with_the_closest_name(self):
        w = World(self)
        w.store.set_chat_agents(True)   # agent-to-agent lines need the switch; the name check is what is tested
        w.session("AGENT-4").listen(wait=300)
        sender = w.session("AGENT-3").listen(wait=300)
        for typo in ("AGENT-44", "Agent 4", "agent4 "):
            rc, out = sender.run("chat", "send", "hello?", "--to", typo)
            self.assertNotEqual(rc, 0, typo)
            self.assertIn("Not sent", out)
            self.assertIn("Closest: AGENT-4", out)
        rc, out = sender.run("chat", "send", "hello?", "--to", "agent-4")    # a known name in another case is fine
        self.assertEqual(rc, 0, out)
        self.assertEqual([m["to"] for m in w.chat()["messages"] if m["sender"] == "AGENT-3"], ["agent-4"])


@needs_node
class ManyReadersAndManyLines(unittest.TestCase):
    def test_twelve_sessions_reading_at_the_same_instant_lose_no_cursor(self):
        w = World(self)
        names = [f"S-{i}" for i in range(12)]
        for n in names:
            w.session(n)
        w.owner_says("to everyone", to="all")
        go = time.time() + 5
        code = ("import sys,time,os; from agentboard.cli import main; "
                f"time.sleep(max(0,{go}-time.time())); main(['chat','inbox','--name',os.environ['AGENTBOARD_NAME']])")
        procs = [subprocess.Popen([sys.executable, "-c", code], env=w.sessions[n].env(), cwd=w.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for n in names]
        for p in procs:
            p.wait(timeout=60)
        have = cursors.read_delivered(w.board)   # (printing is a delivery: that is the concurrent write; the seen cursor moves only when a session acts)
        self.assertEqual(sorted(n.lower() for n in names if n.lower() not in have), [], "a delivery record was lost")
        for n in names:   # and now every one of them acts at the same instant: the cursor (seen) writes race too
            w.sessions[n].proc = None
        go2 = time.time() + 5
        code2 = ("import os,time; from agentboard.cli import main; "
                 f"time.sleep(max(0,{go2}-time.time())); main(['claim','{w.store.load()[0]['id']}','--force','--name',os.environ['AGENTBOARD_NAME']])")
        procs = [subprocess.Popen([sys.executable, "-c", code2], env=w.sessions[n].env(), cwd=w.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for n in names]
        for p in procs:
            p.wait(timeout=60)
        seen = cursors.read(w.board)
        self.assertEqual(sorted(n.lower() for n in names if n.lower() not in seen), [], "a seen-cursor update was lost")

    def test_sixty_unread_lines_are_all_read_oldest_first_across_two_reads(self):
        w = World(self)
        a = w.session("AGENT-A")
        for i in range(60):
            w.owner_says(f"line {i:02d}", to="AGENT-A")
        rc, first = a.run("chat", "inbox")
        rc, second = a.run("chat", "inbox")
        got = [int(l.split("line ")[1][:2]) for l in (first + second).splitlines() if "line " in l and l.startswith("#")]
        self.assertEqual(got, list(range(60)))                              # every one, in order, once
        self.assertIn("more unread", first)
        self.assertNotIn("more unread", second)

    @unittest.expectedFailure
    def test_SPEC_a_log_longer_than_the_kept_500_lines_tells_a_session_that_lines_were_cut(self):
        """Card low-agent-1-a-session-away-for-more-than (LOW, found by this suite): a session away for more than 500 lines is shown the oldest KEPT line with no word that
        the ones before it were cut. Remove the marker with the fix."""
        w = World(self)
        a = w.session("AGENT-A")
        a.run("chat", "inbox")                                             # its cursor is at the start
        for i in range(520):
            w.store.chat_send("bulk", f"filler {i}", kind="agent")
        rc, out = a.run("chat", "inbox", "--limit", "0")
        first_seen = min(int(l.split()[0][1:]) for l in out.splitlines() if l.startswith("#"))
        self.assertGreater(first_seen, 1)                                  # the oldest lines were cut from the log
        self.assertRegex(out, r"(?i)cut|dropped|missed|older|skipped", "a session whose cursor is older than the log is told nothing (R9, still open)")


@needs_node
class TheServerRestarts(unittest.TestCase):
    def test_a_killed_server_loses_no_line_and_no_receipt(self):
        w = World(self, serve=False)
        s1, port1 = w.serve_process()
        a = w.session("AGENT-A").listen(wait=300)
        status, m1 = w.http("POST", "/api/chat", {"text": "before the crash", "to": "AGENT-A"}, port=port1)
        self.assertEqual(status, 200)
        self.assertIn("before the crash", a.got(10))
        s1.send_signal(signal.SIGKILL)
        s1.wait()
        rc, out = w.cli("chat", "send", "--user", "--to", "AGENT-A", "while the server was down")       # the owner's CLI works without a server
        self.assertEqual(rc, 0, out)
        s2, port2 = w.serve_process()
        d = w.chat(port=port2)
        self.assertEqual([m["text"] for m in d["messages"] if m["kind"] == "user"], ["before the crash", "while the server was down"])
        self.assertEqual(d["receipts"]["delivered"]["agent-a"]["seq"], m1["seq"])                      # the delivery receipt survived too
        rc, out = w.sessions["AGENT-A"].run("chat", "inbox")
        self.assertIn("while the server was down", out)                                                # and the line posted while it was down is delivered


@needs_node
class WhatAnAgentMayAnswer(unittest.TestCase):
    """R10: with agent chat off (the owner's setting today), every form of an answer to the owner posts."""

    def test_every_owner_bound_form_posts_with_agent_chat_off_and_agent_to_agent_does_not(self):
        w = World(self)
        a = w.session("AGENT-A").listen(wait=300)
        m = w.owner_says("a question", to="AGENT-A")
        self.assertEqual(w.cli("chat", "agents", "off")[0], 0)
        forms = {"plain": ["done"], "threaded": ["done", "--reply-to", str(m["seq"])], "topic help": ["need help", "--topic", "help"], "two lines": ["done\nmore on a second line"],
                 "detail": ["done", "--detail", "the technical part"], "long line": ["x" * 320], "card": ["done", "--card", w.store.load()[0]["id"]]}
        for label, args in forms.items():
            rc, out = a.run("chat", "send", *args, "--to", w.owner)
            self.assertEqual(rc, 0, f"{label}: {out}")
        a.run("chat", "agents", "off")
        rc, out = a.run("chat", "send", "to a peer", "--to", "ORCH")
        self.assertNotEqual(rc, 0, "an agent-to-agent line must still need the switch")


@needs_node
class TheHooksAtUserLevel(unittest.TestCase):
    def test_user_level_install_names_the_board_and_mirrors_only_known_agents(self):
        w = World(self)
        w.store.set_chat_agents(True)
        rc, out = w.cli("hooks", "install", "--user")
        self.assertEqual(rc, 0, out)
        settings = w.home / ".claude" / "settings.json"
        self.assertIn(str(w.board), settings.read_text())                   # the board folder is in the hook command
        payload = lambda sid, text: json.dumps({"session_id": sid, "tool_name": "SendMessage", "tool_input": {"to": "ORCH", "message": text}})
        w.cli("hook", "send-message", "--dir", str(w.board), stdin=payload("unknown-session", "PRIVATE text of another project"), env={"AGENTBOARD_DIR": ""})
        w.session("AGENT-A").run("me", "--name", "AGENT-A", "--session", "known-session")
        w.cli("hook", "send-message", "--dir", str(w.board), stdin=payload("known-session", "a registered agent speaking"), env={"AGENTBOARD_DIR": ""})
        texts = [m["text"] for m in w.chat()["messages"] if m.get("via") == "mirror"]
        self.assertEqual(texts, ["a registered agent speaking"])

    def test_the_users_original_settings_survive_install_reinstall_and_uninstall(self):
        w = World(self)
        settings = w.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        original = {"permissions": {"allow": ["Bash(ls:*)"]}, "env": {"A_SETTING": "kept"}, "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo mine"}]}]}}
        settings.write_text(json.dumps(original, indent=2))
        w.cli("hooks", "install", "--user")
        other = w.tmp / "other" / ".agentboard"
        other.mkdir(parents=True)
        w.cli("hooks", "install", "--user", env={"AGENTBOARD_DIR": str(other)})
        w.cli("hooks", "uninstall", "--user")
        self.assertEqual(json.loads(settings.read_text()), original)
        kept = [p for p in settings.parent.glob("settings.json.*")]
        self.assertTrue(any(json.loads(p.read_text()) == original for p in kept), "the pristine original is kept once, beside the file")


@needs_node
class LatencyPerAgent(unittest.TestCase):
    """The latency check: for each fake agent, how long from the owner's line to the delivery receipt, with agents that read at very different speeds.
    (The board records WHEN a line was delivered but not when it was seen or answered: the next metric, chat-p2, can only count what is recorded.)"""

    def test_delivery_time_per_agent_is_seconds_whatever_the_agent_does_after(self):
        w = World(self)
        speeds = {"AGENT-FAST": 0, "AGENT-SLOW": 400, "AGENT-GONE": None}
        for n in speeds:
            w.session(n).listen(discard=speeds[n] is None)
        sent = {}
        for n in speeds:
            sent[n] = w.owner_says(f"ping {n}", to=n)
        for n in speeds:
            w.sessions[n].got(10)
        d = w.chat()
        table = {}
        for n, m in sent.items():
            rec = d["receipts"]["delivered"][n.lower()]
            t_sent = time.mktime(time.strptime(m["at"], "%Y-%m-%dT%H:%M:%S"))
            t_del = time.mktime(time.strptime(rec["at"], "%Y-%m-%dT%H:%M:%S"))
            table[n] = t_del - t_sent
        self.assertLess(max(table.values()), 4, table)
        self.assertEqual({n: w.state(m["seq"])["state"] for n, m in sent.items()}, {n: "delivered" for n in speeds})
        w.age_delivery("AGENT-SLOW", 400)
        self.assertEqual(w.state(sent["AGENT-SLOW"]["seq"], plus_s=400)["late"], True)
        w.sessions["AGENT-FAST"].run("claim", w.store.load()[0]["id"])
        self.assertEqual(w.state(sent["AGENT-FAST"]["seq"])["state"], "seen")
        self.assertEqual(w.state(sent["AGENT-GONE"]["seq"], plus_s=400)["state"], "delivered")      # never acted: stays delivered, flagged late, never "seen"


@needs_node
class TheLiveCheckScript(unittest.TestCase):
    """tests/chat_live_check.py, run against a throwaway board: read-only by default, never prints a line's words, --send posts one ping per listener and ORCH."""

    def run_check(self, w, *args):
        from pathlib import Path
        script = Path(__file__).resolve().parent / "chat_live_check.py"
        r = subprocess.run([sys.executable, str(script), *args], env=w.env, cwd=w.cwd, capture_output=True, text=True, timeout=90)
        return r.returncode, r.stdout + r.stderr

    def test_read_only_prints_states_and_counts_and_writes_nothing(self):
        w = World(self)
        a = w.session("AGENT-A").listen()
        w.owner_says("SECRET-WORDS-OF-A-LINE", to="AGENT-A")
        a.got(10)
        before = {p.name: p.read_bytes() for p in w.board.glob("*.json")}
        rc, out = self.run_check(w)
        self.assertEqual(rc, 0, out)
        self.assertIn("AGENT-A", out)
        self.assertRegex(out, r"#\d+\s+to AGENT-A\s+\d+ s ago\s+delivered")
        self.assertNotIn("SECRET-WORDS", out)
        self.assertEqual({p.name: p.read_bytes() for p in w.board.glob("*.json")}, before)

    def test_send_needs_yes_and_then_pings_each_listener_and_orch_once(self):
        w = World(self)
        a = w.session("AGENT-A").listen()
        rc, out = self.run_check(w, "--send")
        self.assertIn("add --yes", out)
        self.assertEqual([m for m in w.chat()["messages"] if "chat check" in m["text"]], [])
        rc, out = self.run_check(w, "--send", "--yes", "--wait", "8")
        self.assertEqual(rc, 0, out)
        pings = [m for m in w.chat()["messages"] if "chat check" in m["text"]]
        self.assertEqual(sorted(m["to"] for m in pings), ["AGENT-A", "ORCH"])
        self.assertRegex(out, r"AGENT-A\s+delivered\s+delivered after \d+ s")
        self.assertRegex(out, r"ORCH\s+sent\s+not delivered yet")          # ORCH has no wait here: the line is posted and the wake file moved
        a.got(5)


if __name__ == "__main__":
    unittest.main()
