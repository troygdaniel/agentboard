"""First run (overnight-ux-firstrun, Nov 7): a developer who has never seen the board should be productive in five minutes.
The CLI says what to do next (a welcome for a bare `agentboard`, a guided `init`, a nearest-command hint, plain errors) and the empty board
offers three ways in (a visible New task button, sample cards, a 60-second tour) in words with no jargon. Everything here runs on throwaway
folders and boards; nothing reads a real one."""
import contextlib
import http.client
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, demo, server
from agentboard.store import Store

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class Tty(io.StringIO):
    def isatty(self):
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.here = self.root / "proj"
        self.here.mkdir()
        old = os.getcwd()
        os.chdir(self.here)
        self.addCleanup(os.chdir, old)

    def run_cli(self, *argv, tty=False, stdin_tty=False, answers=None):
        out, err = (Tty(), Tty()) if tty else (io.StringIO(), io.StringIO())
        asked = []

        def fake_input(prompt=""):
            asked.append(prompt)
            if not answers:
                raise EOFError
            return answers.pop(0)
        stdin = mock.Mock(isatty=lambda: stdin_tty)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch("sys.stdin", stdin), mock.patch("builtins.input", fake_input):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        self.asked = asked
        return code, out.getvalue(), err.getvalue()

    def board(self):
        return Store(self.here / ".agentboard")


class Welcome(Base):
    def test_a_bare_command_is_a_welcome_not_an_error(self):
        code, out, err = self.run_cli()
        self.assertEqual((code, err), (0, ""))
        for need in ("agentboard init", "agentboard serve", "agentboard instructions", "New here?", "agentboard <command> -h", "http://localhost:8765"):
            self.assertIn(need, out)
        self.assertNotIn("This folder's board", out)               # no board in reach: nothing to say about one
        self.assertLess(len(out.splitlines()), 16)                 # a glance, not a manual

    def test_it_names_the_board_in_reach(self):
        self.run_cli("init", "--no-demo")
        self.board().add("One", status="todo")
        _code, out, _err = self.run_cli()
        self.assertIn("This folder's board:", out)
        self.assertIn("(1 task)", out)

    def test_the_help_page_points_new_users_at_it(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["-h"])
        self.assertIn("New here? Run `agentboard` with no arguments", out.getvalue())


class UnknownCommand(Base):
    def test_a_typo_names_the_closest_command_and_does_not_list_all_of_them(self):
        code, _out, err = self.run_cli("strat", "x")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice: 'strat'", err)
        self.assertIn("Did you mean: start", err)
        self.assertNotIn("choose from", err)
        self.assertLess(len(err.splitlines()), 4)

    def test_nothing_close_gives_no_guess(self):
        code, _out, err = self.run_cli("zzzzzz")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice: 'zzzzzz'", err)
        self.assertNotIn("Did you mean", err)
        self.assertIn("`agentboard` with no arguments", err)

    def test_the_plugin_hint_is_for_people_who_have_a_plugin(self):
        os.environ.pop("AGENTBOARD_PLUGINS", None)
        with mock.patch.object(cli, "_plugin_installed", return_value=False):
            _c, _o, err = self.run_cli("zzzzzz")
        self.assertNotIn("plugins are", err)                       # a stranger's typo is not about plugins
        with mock.patch.object(cli, "_plugin_installed", return_value=True):
            _c, _o, err = self.run_cli("zzzzzz")
        self.assertIn("plugins are off", err)

    def test_a_known_command_with_a_bad_argument_keeps_argparses_own_words(self):
        code, _o, err = self.run_cli("move", "x", "banana")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice: 'banana'", err)


class Init(Base):
    def test_init_says_what_to_do_next_and_asks_nothing_when_not_at_a_terminal(self):
        code, out, err = self.run_cli("init")
        self.assertEqual((code, self.asked), (0, []))
        self.assertIn("set up a board:", out)
        for step in ("agentboard serve", "agentboard demo", "agentboard instructions", "CLAUDE.md or AGENTS.md"):
            self.assertIn(step, out)
        self.assertEqual(self.board().load(), [])
        self.assertTrue((self.here / ".gitignore").read_text().count(".agentboard/"))

    def test_at_a_terminal_it_asks_once_about_sample_cards(self):
        _c, out, _e = self.run_cli("init", tty=True, stdin_tty=True, answers=["y"])
        self.assertEqual(len(self.asked), 1)
        self.assertIn("sample cards", self.asked[0])
        self.assertTrue(self.board().load())
        self.assertTrue(all(t["id"].startswith("demo-") for t in self.board().load()))
        self.assertNotIn("agentboard demo ", out.split("next:")[1])   # it is done, so the next steps do not offer it

    def test_no_means_an_empty_board_and_so_does_a_closed_stdin(self):
        for answers in (["n"], [""], ["maybe"], None):
            with self.subTest(answers=answers):
                d = self.root / f"p{len(str(answers))}{answers[0] if answers else 'x'}"
                d.mkdir()
                os.chdir(d)
                self.run_cli("init", tty=True, stdin_tty=True, answers=answers)
                self.assertEqual(Store(d / ".agentboard").load(), [])
                self.assertEqual(len(self.asked), 1)

    def test_the_flags_skip_the_question(self):
        self.run_cli("init", "--no-demo", tty=True, stdin_tty=True, answers=["y"])
        self.assertEqual((self.asked, self.board().load()), ([], []))
        os.chdir(self.root)
        d = self.root / "other"
        d.mkdir()
        os.chdir(d)
        self.run_cli("init", "--demo", tty=True, stdin_tty=True, answers=["n"])
        self.assertEqual(self.asked, [])
        self.assertTrue(Store(d / ".agentboard").load())

    def test_nothing_is_asked_when_only_stdin_or_only_stdout_is_a_terminal(self):
        self.run_cli("init", tty=False, stdin_tty=True, answers=["y"])
        self.assertEqual(self.asked, [])

    def test_running_it_again_changes_nothing_and_says_so(self):
        self.run_cli("init", "--no-demo")
        self.board().add("Keep me", status="todo")
        _c, out, _e = self.run_cli("init", tty=True, stdin_tty=True, answers=["y"])
        self.assertIn("already set up here, nothing was changed", out)
        self.assertEqual(self.asked, [])                           # no question on a board that has work in it
        self.assertEqual([t["title"] for t in self.board().load()], ["Keep me"])

    def test_a_board_in_a_folder_above_is_mentioned(self):
        self.run_cli("init", "--no-demo")
        sub = self.here / "pkg"
        sub.mkdir()
        os.chdir(sub)
        _c, out, _e = self.run_cli("init", "--no-demo")
        self.assertIn("a board in a folder above this one", out)
        self.assertIn(str(self.here / ".agentboard"), out)


class InitNeverTouchesAnotherBoard(Base):
    """Cross-review xr-firstrun-demo-wrong-board: `init --demo` seeded the sample cards into the board AGENTBOARD_DIR names, not the one init made."""

    def setUp(self):
        super().setUp()
        self.other = self.root / "live" / ".agentboard"
        self.other.mkdir(parents=True)
        self.live = Store(self.other)
        self.live.add("Real work", status="todo")
        self.before = (self.other / "tasks.json").read_bytes()
        os.environ["AGENTBOARD_DIR"] = str(self.other)
        self.new = self.root / "fresh"
        self.new.mkdir()
        os.chdir(self.new)

    def assertLiveBoardUntouched(self):
        self.assertEqual((self.other / "tasks.json").read_bytes(), self.before)
        self.assertEqual([t["title"] for t in self.live.load()], ["Real work"])

    def test_the_flag_seeds_the_new_board_and_leaves_the_named_one_alone(self):
        code, out, _e = self.run_cli("init", "--demo")
        self.assertEqual(code, 0)
        self.assertTrue(all(t["id"].startswith("demo-") for t in Store(self.new / ".agentboard").load()))
        self.assertTrue(Store(self.new / ".agentboard").load())
        self.assertLiveBoardUntouched()
        self.assertIn("added sample cards", out)

    def test_the_answer_yes_at_a_terminal_does_the_same(self):
        self.run_cli("init", tty=True, stdin_tty=True, answers=["y"])
        self.assertTrue(Store(self.new / ".agentboard").load())
        self.assertLiveBoardUntouched()

    def test_init_says_that_the_shell_still_points_at_the_other_board(self):
        _c, out, _e = self.run_cli("init", "--no-demo")
        self.assertIn(f"AGENTBOARD_DIR is set to {self.other}", out)
        self.assertIn("not this new one", out)
        self.assertLiveBoardUntouched()

    def test_no_note_when_the_variable_names_the_new_board_itself(self):
        os.environ["AGENTBOARD_DIR"] = str(self.new / ".agentboard")
        _c, out, _e = self.run_cli("init", "--demo")
        self.assertNotIn("is set to", out)
        self.assertTrue(Store(self.new / ".agentboard").load())
        self.assertLiveBoardUntouched()

    def test_with_no_variable_nothing_changed(self):
        del os.environ["AGENTBOARD_DIR"]
        _c, out, _e = self.run_cli("init", "--demo")
        self.assertNotIn("is set to", out)
        self.assertTrue(Store(self.new / ".agentboard").load())

    def test_a_named_board_is_protected_the_same_way(self):
        """`--board NAME` and AGENTBOARD_BOARD name a registered board and win over the folder, like AGENTBOARD_DIR does."""
        from agentboard import boards
        os.environ["AGENTBOARD_HOME"] = str(self.root / "boards-home")
        boards.register("live", self.other)
        del os.environ["AGENTBOARD_DIR"]
        os.environ["AGENTBOARD_BOARD"] = "live"
        _c, out, _e = self.run_cli("init", "--demo")
        self.assertIn("AGENTBOARD_BOARD is set to live", out)
        self.assertTrue(Store(self.new / ".agentboard").load())
        self.assertLiveBoardUntouched()
        del os.environ["AGENTBOARD_BOARD"]
        os.rename(self.new / ".agentboard", self.new / "gone")
        _c, out, _e = self.run_cli("--board", "live", "init", "--demo")                    # the flag is the same thing
        self.assertLiveBoardUntouched()
        self.assertTrue(Store(self.new / ".agentboard").load())

    def test_the_demo_command_itself_still_follows_the_variable(self):
        """`agentboard demo` is about the board in use, which is what it should stay."""
        self.run_cli("demo")
        self.assertTrue(any(t["id"].startswith("demo-") for t in self.live.load()))

    def test_the_bare_command_names_the_variable_not_the_folder(self):
        _c, out, _e = self.run_cli()
        self.assertIn("The board in use (AGENTBOARD_DIR is set):", out)
        self.assertNotIn("This folder's board", out)
        del os.environ["AGENTBOARD_DIR"]
        os.chdir(self.here)
        self.run_cli("init", "--no-demo")
        self.assertIn("This folder's board:", self.run_cli()[1])


class Hints(Base):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--no-demo")

    def test_an_empty_list_says_how_to_add_a_task_at_a_terminal_and_stays_silent_in_a_script(self):
        code, out, err = self.run_cli("list", tty=True)
        self.assertEqual((code, out), (0, ""))
        self.assertIn('agentboard add "My first task"', err)
        self.assertIn("agentboard demo", err)
        self.assertEqual(self.run_cli("list"), (0, "", ""))        # piped: exactly what it was

    def test_a_percent_out_of_range_is_said_not_swallowed(self):
        self.run_cli("start", "Try it", "--name", "me")
        code, out, err = self.run_cli("update", "try-it", "150", "too far")
        self.assertEqual(code, 0)
        self.assertIn("try-it: 100%", out)
        self.assertIn("note: progress is 0 to 100; 150 was taken as 100", err)
        _c, _o, err = self.run_cli("update", "try-it", "50", "fine")
        self.assertNotIn("note:", err)

    def test_an_unknown_id_points_at_list(self):
        code, _o, err = self.run_cli("update", "nope", "5", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("no such task: nope (`agentboard list` shows the ids)", str(code) + err)

    def test_list_filters_by_agent_in_any_case_and_by_a_real_column(self):
        for who in ("atlas", "bolt"):
            self.run_cli("start", f"Task of {who}", "--name", who)
        _c, out, _e = self.run_cli("list", "--agent", "ATLAS")
        self.assertIn("task-of-atlas", out)
        self.assertNotIn("bolt", out)
        self.assertEqual(self.run_cli("list", "--agent", "nobody")[1], "")
        self.assertEqual(self.run_cli("list", "--status", "banana")[0], 2)
        self.assertIn("task-of-atlas", self.run_cli("list", "--status", "doing")[1])

    def test_the_subtask_reminder_is_for_agents_not_for_a_person_at_a_terminal(self):
        _c, _o, piped = self.run_cli("add", "One")
        self.assertIn("every card gets subtasks", piped)
        _c, _o, typed = self.run_cli("add", "Two", tty=True)
        self.assertNotIn("reminder", typed)

    def test_serve_refuses_a_port_that_cannot_be_one_in_plain_words(self):
        for port in ("99999", "0", "-5"):
            code, _o, err = self.run_cli("serve", "--no-open", "--port", port)
            self.assertNotEqual(code, 0, port)
            self.assertIn("--port must be a number from 1 to 65535", str(code) + err)
            self.assertNotIn("Traceback", err)

    def test_serve_help_says_what_its_options_do(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["serve", "-h"])
        text = out.getvalue()
        self.assertIn("default 8765", text)
        self.assertIn("do not open a browser", text)


class SampleCards(Base):
    def setUp(self):
        super().setUp()
        self.s = Store(self.here / ".agentboard")
        self.s.dir.mkdir()

    def test_seeding_twice_changes_nothing(self):
        n = demo.seed(self.s)
        before = json.dumps(self.s.load(), sort_keys=True)
        self.assertEqual(demo.seed(self.s), n)
        self.assertEqual(json.dumps(self.s.load(), sort_keys=True), before)
        self.assertTrue(all(t["id"].startswith("demo-") for t in self.s.load()))

    def test_a_sample_card_in_progress_has_its_steps_so_the_board_does_not_flag_it(self):
        demo.seed(self.s)
        tasks = self.s.load()
        for t in tasks:
            if t["status"] == "doing" and not t.get("parent_id"):
                self.assertGreaterEqual(sum(1 for k in tasks if k.get("parent_id") == t["id"]), 2, t["id"])
        self.assertEqual({t["agent"] for t in tasks if t.get("agent")}, {"atlas", "scribe", "bolt"})

    def test_rm_demo_takes_them_all_away_steps_included(self):
        demo.seed(self.s)
        self.s.add("Mine", status="todo")
        code, out, _e = self.run_cli("rm", "--demo")
        self.assertEqual(code, 0)
        self.assertEqual([t["title"] for t in self.s.load()], ["Mine"])

    def test_the_demo_command_is_the_same_thing(self):
        code, out, _e = self.run_cli("demo")
        self.assertEqual(code, 0)
        self.assertIn("remove with: agentboard rm --demo", out)
        self.assertEqual(len(self.s.load()), demo.seed(self.s))


class SampleRoute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store, 0))
        self.port = probe.server_address[1]
        probe.server_close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, extra=None, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request("POST", "/api/demo", body="{}", headers={"Host": f"localhost:{self.port}", "Content-Type": ctype, **(extra or {})})
        r = c.getresponse()
        return r.status, r.read()

    def test_the_button_adds_the_sample_cards_once(self):
        code, raw = self.post()
        self.assertEqual(code, 200)
        n = json.loads(raw)["cards"]
        self.assertEqual(len(self.store.load()), n)
        self.assertEqual(json.loads(self.post()[1])["cards"], n)

    def test_it_is_guarded_like_every_other_post(self):
        self.assertEqual(self.post({"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.post(ctype="text/plain")[0], 415)
        self.assertEqual(self.store.load(), [])


class ThePage(unittest.TestCase):
    def header(self):
        return re.search(r"<header>.*?</header>", PAGE, re.S).group(0)

    def test_new_task_is_a_button_you_can_see_and_the_key_is_in_its_name(self):
        h = self.header()
        self.assertRegex(h, r'<button class="btn" id="new-btn"[^>]*aria-label="New task \(n\)"')
        self.assertIn('<span class="lbl">New task</span>', h)
        self.assertIn("$('new-btn').onclick = () => { if (hudIsOpen()) closeHud(); toggleAdd(true); };", PAGE)   # what n does
        self.assertIn("@media (max-width: 700px) { #new-btn {", PAGE)                                          # a phone keeps the plus

    def test_help_is_a_button_too(self):
        h = self.header()
        self.assertRegex(h, r'id="help-btn"[^>]*aria-controls="keys"')
        self.assertIn("$('help-btn').onclick = () => toggleKeys();", PAGE)

    def test_the_first_screen_has_no_jargon_and_three_ways_in(self):
        w = re.search(r'<div id="welcome">.*?\n  </div>', PAGE, re.S).group(0)
        top = w.split('<details class="orch-how">')[0]
        for word in ("ORCH", "orchestrat", "HUD", "telemetry"):
            self.assertNotIn(word, top, word)
        for ident in ("welcome-add", "welcome-demo", "welcome-tour"):
            self.assertIn(f'id="{ident}"', top)
        self.assertIn("$('welcome-demo').onclick", PAGE)
        self.assertIn("api('/api/demo', {})", PAGE)
        self.assertIn("agentboard rm --demo", PAGE)                                 # the toast says how to undo it

    def test_the_empty_columns_say_how_a_card_gets_there(self):
        m = re.search(r"const EMPTY = \{(.*?)\};", PAGE, re.S).group(1)
        self.assertIn("Add a task (n)", m)
        self.assertIn("when an agent starts it", m)
        self.assertIn("once you have reviewed it", m)
        self.assertNotIn("claim", m)                                                # "claim" is the agents' word

    def test_the_tour_is_four_short_steps_with_fixed_text(self):
        tour = re.search(r"const TOUR = \[(.*?)\n\];", PAGE, re.S).group(1)
        self.assertEqual(tour.count("{ h: '"), 4)
        for h in ("Agents report, you decide", "Three columns", "When an agent needs you", "More ways to look"):
            self.assertIn(h, tour)
        self.assertIn("$('tour-viz').innerHTML = t.viz;   // fixed strings above, never board data", PAGE)
        self.assertEqual(PAGE.count("$('tour-viz').innerHTML"), 1)

    def test_the_tour_is_a_proper_dialog_that_the_keys_respect(self):
        self.assertIn('id="tour" role="dialog" aria-modal="true" aria-labelledby="tour-h"', PAGE)
        self.assertIn("if (tourIsOpen()) { tourKey(e); return; }", PAGE)           # while it is open it has the keys
        self.assertIn("if (e.key === 'Escape') { e.preventDefault(); closeTour(); return; }", PAGE)
        self.assertIn("e.key === 'Tab'", PAGE)                                      # focus stays inside it
        self.assertIn("tourOpener?.focus()", PAGE)                                  # and goes back where it was
        self.assertIn('id="keys-tour"', PAGE)                                       # reachable from the shortcuts sheet too

    def test_the_tour_never_opens_by_itself(self):
        self.assertEqual(len(re.findall(r"openTour\(", PAGE)), 3)                   # the function, the welcome button, the sheet's link
        self.assertNotIn("localStorage.setItem('agentboard-tour", PAGE)


if __name__ == "__main__":
    unittest.main()
