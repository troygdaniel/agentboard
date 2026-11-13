"""The Story page (/story): five scenes built from card data with templates (work-ready, ux-story-view).
Nothing here needs a model, a network or a program: the work profile serves the same page as a home machine."""
import re
import socket
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import server, story
from agentboard.store import Store

NOW = datetime(2026, 11, 9, 12, 0, 0)
F = "%Y-%m-%dT%H:%M:%S"


def card(id, title, status="todo", agent="", days_ago=0.0, parent=None, **kw):
    at = (NOW - timedelta(days=days_ago)).strftime(F)
    log = [{"at": at, "status": "doing", "progress": 5, "text": f"Started by {agent}"}] if agent else []
    if status == "done":
        log.append({"at": at, "status": "done", "progress": 100, "text": "Marked done"})
    t = {"id": id, "title": title, "description": "", "status": status, "progress": 100 if status == "done" else 0, "status_text": "", "agent": agent,
         "ctx": [], "prompt": "", "created": at, "updated": at, "log": log}
    if parent:
        t["parent_id"] = parent
    t.update(kw)
    return t


def sample():
    return [card("b1", "Billing: map the call sites", "done", "atlas", 3), card("b2", "Billing: extract the service", "done", "atlas", 2),
            card("b3", "Billing: reconcile month end", "doing", "atlas", 0.1), card("b3a", "Match the ledgers", "doing", "atlas", 0.1, parent="b3"),
            card("d1", "Docs: draft the reference", "done", "scribe", 1), card("d2", "Docs: pick a tone", "doing", "scribe", 0.1, needs_input=True, question="Friendly or formal?"),
            card("s1", "Search: highlight words", "doing", "bolt", 0.2, review=True, result="highlights titles"), card("s2", "Search: filter by agent", "todo"),
            card("old", "Search: spike the index", "done", "bolt", 12), card("later", "Parked idea", "backlog"), card("gone", "Abandoned", "doing", "x", 1, archived=True)]


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.d = story.collect(sample(), now=NOW)
        self.state = {c["id"]: c["state"] for c in self.d["cards"]}

    def test_every_card_lands_in_one_state(self):
        self.assertEqual(self.state, {"b1": "done", "b2": "done", "b3": "working", "d1": "done", "d2": "needs", "s1": "needs", "s2": "waiting"})

    def test_a_subtask_backlog_and_an_archived_open_card_are_not_cards(self):
        for gone in ("b3a", "later", "gone"):
            self.assertNotIn(gone, self.state)

    def test_a_card_finished_before_the_week_is_not_a_card_but_is_in_the_timeline(self):
        self.assertNotIn("old", self.state)
        self.assertEqual(self.d["counts"], {"waiting": 1, "working": 1, "needs": 2, "done": 3})
        self.assertEqual(sum(n for _d, n in self.d["timeline"]), 4)   # the 12-day-old one shows in the 14-day timeline

    def test_the_timeline_is_fourteen_days_ending_today(self):
        tl = self.d["timeline"]
        self.assertEqual(len(tl), 14)
        self.assertEqual(tl[-1][0], NOW.date())
        self.assertEqual(dict(tl)[NOW.date() - timedelta(days=1)], 1)

    def test_needs_lists_only_what_waits_on_the_owner(self):
        self.assertEqual(sorted(n["id"] for n in self.d["needs"]), ["d2", "s1"])
        self.assertEqual({n["kind"] for n in self.d["needs"]}, {"ask", "review"})

    def test_a_cleared_card_still_counts_as_finished(self):
        d = story.collect([card("x", "Cleared one", "done", "a", 1, archived=True)], now=NOW)
        self.assertEqual(d["counts"]["done"], 1)

    def test_the_same_tasks_give_the_same_story(self):
        again = story.collect(sample(), now=NOW)
        self.assertEqual([t["name"] for t in again["themes"]], [t["name"] for t in self.d["themes"]])
        self.assertEqual(again["counts"], self.d["counts"])


class ThemeTests(unittest.TestCase):
    def test_a_word_several_titles_share_names_a_theme_and_the_rest_is_other(self):
        d = story.collect([card("b1", "Billing: one", "todo"), card("b2", "Billing: two", "todo"), card("b3", "Billing: three", "todo"),
                           card("s1", "Search: one", "todo"), card("s2", "Search: two", "todo"), card("o", "Rotate keys", "todo")], now=NOW)
        names = [t["name"] for t in d["themes"]]
        self.assertEqual(names, ["Billing", "Search", "Other"])
        other = d["themes"][-1]
        self.assertEqual(other["slot"], "sg")   # grey, never a theme colour

    def test_n_of_m_counts_finished_cards_of_the_theme(self):
        th = {t["name"]: t for t in story.collect(sample(), now=NOW)["themes"]}
        self.assertEqual((th["Billing"]["n"], th["Billing"]["m"]), (2, 3))
        self.assertEqual((th["Search"]["n"], th["Search"]["m"]), (0, 2))

    def test_with_no_shared_word_cards_are_grouped_by_who_is_on_them(self):
        d = story.collect([card("a", "Alpha job", "doing", "ann", 0.1), card("b", "Beta chore", "doing", "bob", 0.1), card("c", "Gamma task", "todo")], now=NOW)
        self.assertEqual(sorted(t["name"] for t in d["themes"]), ["Queue", "ann", "bob"])

    def test_every_card_carries_its_themes_colour(self):
        d = story.collect(sample(), now=NOW)
        for th in d["themes"]:
            self.assertTrue(all(c["slot"] == th["slot"] for c in th["cards"]))

    def test_the_sentence_is_plain_words_from_a_template_and_drops_a_repeated_prefix(self):
        th = {t["name"]: t for t in story.collect(sample(), now=NOW)["themes"]}
        self.assertEqual(th["Billing"]["line"], "atlas is on reconcile month end")
        self.assertEqual(th["Search"]["line"], "Waiting on you: highlight words")
        done = story.collect([card("x", "Docs: a", "done", "s", 1), card("y", "Docs: b", "done", "s", 2)], now=NOW)["themes"][0]
        self.assertTrue(done["line"].startswith("All finished; the last was "), done["line"])
        todo = story.collect([card("x", "Docs: a", "todo"), card("y", "Docs: b", "todo")], now=NOW)["themes"][0]
        self.assertTrue(todo["line"].startswith("Next up: "), todo["line"])

    def test_the_owners_name_is_used(self):
        d = story.collect(sample(), now=NOW, owner="Troy")
        self.assertIn("Waiting on Troy: ", {t["name"]: t for t in d["themes"]}["Search"]["line"])


class HeadlineTests(unittest.TestCase):
    def test_an_empty_board_a_quiet_one_and_a_busy_one(self):
        self.assertEqual(story.headline(story.collect([], now=NOW)), "Nothing on the board yet.")
        quiet = story.collect([card("x", "Old", "done", "a", 10)], now=NOW)
        self.assertTrue(story.headline(quiet).startswith("Quiet right now"))
        busy = story.headline(story.collect(sample(), now=NOW))
        self.assertEqual(busy, "3 cards finished in the last 7 days, 3 in progress and 1 waiting to start. 2 of them need you.")

    def test_one_card_is_singular(self):
        h = story.headline(story.collect([card("x", "Only", "done", "a", 1)], now=NOW))
        self.assertTrue(h.startswith("1 card finished in the last 7 days"), h)


class PageTests(unittest.TestCase):
    def page(self, tasks=None, base="", owner="you"):
        return story.build_html(story.collect(sample() if tasks is None else tasks, now=NOW, owner=owner), base)

    def test_five_scenes_in_order_with_a_pager(self):
        h = self.page()
        ids = re.findall(r'<section class="scene[^"]*" id="(s\d)"', h)
        self.assertEqual(ids, ["s1", "s2", "s3", "s4", "s5"])
        self.assertEqual(re.findall(r'<a href="#(s\d)" aria-label="Scene \d', h), ids)

    def test_card_text_is_escaped(self):
        h = self.page([card("x", "<script>alert(1)</script> & more", "doing", "<b>bad</b>", 0.1)])
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertNotIn("<b>bad</b>", h)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", h)

    def test_the_page_reaches_nothing_outside_itself(self):
        h = self.page()
        for needle in ("http://", "https://", "fetch(", "XMLHttpRequest", "WebSocket", "<img", "<iframe", "<link", "src=", "import("):
            self.assertNotIn(needle, h)

    def test_reduced_motion_light_and_dark_and_narrow_are_handled(self):
        h = self.page()
        self.assertIn("prefers-reduced-motion", h)
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)')", h)   # no entrance animation at all: the scenes are simply there
        self.assertIn("prefers-color-scheme:dark", h)
        self.assertIn('data-theme="dark"', h)
        self.assertIn("max-width:760px", h)
        self.assertIn("scroll-snap-align:start", h)

    def test_without_script_everything_is_visible(self):
        # the hidden start state only exists under .js, which the inline script adds after it has set up the observers
        self.assertIsNone(re.search(r"(^|\})\s*\.scene:not\(\.in\) \.rise", story.CSS))
        self.assertIn("classList.add('js')", story.JS)

    def test_the_bar_links_under_the_base_and_lights_no_tab(self):
        # Nov 11: Story is a link in the board's Done column, like Summary and Reports, so its page lights none of the three tabs
        h = self.page(base="/b/x")
        self.assertNotIn("tab on", h)
        for href in ('href="/b/x/"', 'href="/b/x/watch"', 'href="/b/x/need"'):
            self.assertIn(href, h)

    def test_an_empty_board_says_so_with_one_scene(self):
        h = self.page([])
        self.assertIn("Nothing on the board yet.", h)
        self.assertNotIn('id="s2"', h)

    def test_a_nothing_to_do_board_is_calm_in_scene_four(self):
        h = self.page([card("x", "Billing: a", "done", "a", 1), card("y", "Billing: b", "doing", "a", 0.1)])
        self.assertIn("Nothing is waiting on you.", h)
        self.assertNotIn('class="need"', h)

    def test_scene_four_names_the_owner_and_each_thing_waiting(self):
        h = self.page(owner="Troy")
        self.assertIn("2 things waiting on Troy.", h)
        self.assertEqual(h.count('<a class="need" href='), 2)
        self.assertIn("Friendly or formal?", h)

    def test_many_cards_are_capped_to_dots_and_a_count(self):
        many = [card(f"c{i}", f"Thing{i} work", "todo") for i in range(story.MAX_DOTS + 15)]
        h = self.page(many)
        self.assertEqual(h.count('<a class="dot '), story.MAX_DOTS)
        self.assertIn("+15 more", h)

    def test_more_themes_than_fit_end_in_a_line(self):
        tasks = []
        for i in range(12):
            tasks += [card(f"a{i}", f"Zq{i}x: one", "todo"), card(f"b{i}", f"Zq{i}x: two", "todo")]
        d = story.collect(tasks, now=NOW)
        if len(d["themes"]) > story.MAX_THEMES:
            self.assertIn("more theme", story.build_html(d))


class LinkTests(unittest.TestCase):
    """Every card the page shows opens that card on the board (/#<id>, the hash the board opens a panel from); the days are counts, so they link nowhere."""
    def page(self, tasks=None, base="", owner="you"):
        return story.build_html(story.collect(sample() if tasks is None else tasks, now=NOW, owner=owner), base)

    def hrefs(self, h, cls):
        return re.findall(r'<a class="%s[^"]*" href="([^"]+)"' % cls, h)

    def test_every_dot_opens_its_card(self):
        h = self.page()
        self.assertEqual(sorted(self.hrefs(h, "dot")), sorted(f"/#{i}" for i in ("b1", "b2", "b3", "d1", "d2", "s1", "s2")))
        self.assertNotIn('<i class="dot', h)   # a dot is a link, not a bare mark

    def test_a_dot_keeps_its_title_and_has_a_name_for_a_screen_reader(self):
        h = self.page()
        self.assertIn('title="Billing: reconcile month end" aria-label="Billing: reconcile month end (Working)"', h)

    def test_each_row_in_needs_you_opens_its_card(self):
        self.assertEqual(sorted(self.hrefs(self.page(), "need")), ["/#d2", "/#s1"])

    def test_a_theme_sentence_opens_the_card_it_is_about(self):
        d = story.collect(sample(), now=NOW)
        by = {t["name"]: t for t in d["themes"]}
        self.assertEqual(by["Billing"]["focus"], "b3")   # the one in progress, not a finished one
        self.assertEqual(by["Search"]["focus"], "s1")    # waiting on the owner beats a card that merely waits
        self.assertRegex(story.build_html(d), r'<p><a href="/#b3">[^<]*reconcile month end</a></p>')

    def test_the_link_follows_the_base_and_an_odd_id_is_escaped(self):
        h = self.page([card("a b&c/d", "Odd: one", "todo"), card("a b&c/e", "Odd: two", "todo")], base="/b/x")
        self.assertIn('href="/b/x/#a%20b%26c%2Fd"', h)
        self.assertNotIn('href="/#', h)

    def test_the_days_are_not_links(self):
        h = self.page()
        day_list = h[h.index('class="days'):]
        self.assertNotIn("<a ", day_list.split("</ol>")[0])

    def test_a_card_in_the_flow_is_reachable_by_keyboard_and_touch(self):
        css = story.CSS
        self.assertIn("a.dot:focus-visible", css)
        self.assertIn("a.need:focus-visible", css)
        self.assertRegex(css, r"a\.dot::after\{content:\"\";position:absolute;inset:-4px\}")   # a 16px dot with a 24px tap area

    def test_the_page_still_loads_nothing_from_outside(self):
        h = self.page()
        self.assertNotRegex(h, r"""(?:src|href)=["']https?://""")


class WorkProfileTests(unittest.TestCase):
    """The page is built from the board's own file: with every program and every socket made to fail, it still builds."""
    def test_it_builds_with_nothing_allowed_to_start_or_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / ".agentboard")
            s.add("Billing: one", status="todo", task_id="one")
            s.add("Billing: two", status="doing", task_id="two")

            def boom(*a, **k):
                raise AssertionError("a program was started or a socket opened")
            with mock.patch("subprocess.run", side_effect=boom), mock.patch("subprocess.Popen", side_effect=boom), mock.patch("urllib.request.urlopen", side_effect=boom), \
                    mock.patch("socket.create_connection", side_effect=boom):
                h = story.build_html(story.build(s))
            self.assertIn("Billing", h)


class HttpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")
        self.s.add("Billing: one", status="todo", task_id="one")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read().decode(), dict(r.headers)

    def test_story_is_served_as_a_tight_page(self):
        for path in ("/story", "/story/"):
            status, body, headers = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn("text/html", headers["Content-Type"])
            self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
            self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertIn("Billing", body)

    def test_the_board_links_to_story_from_the_done_column(self):
        page = self.get("/")[1]
        self.assertIn("/story\" title=\"The work in plain words\">Story</a>", page)
        self.assertNotIn('id="tab-story"', page)   # no longer a tab: the row is Board, By agent, Needs you


if __name__ == "__main__":
    unittest.main()
