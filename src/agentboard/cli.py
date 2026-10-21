"""agentboard command line."""
import argparse
import os
import sys
from pathlib import Path

from . import __version__
from . import prompt as promptlib
from .server import serve
from .store import DIR_NAME, BoardError, Store, find_dir

SAMPLE_CONFIG = '''\
# agentboard config. Providers add context to task prompts.
# Attach them to a task with:  agentboard add "Title" --ctx name[:arg]

# [providers.docs]            # sections of a markdown file; arg = section names
# type = "markdown"
# path = "CLAUDE.md"          # relative to the project root, or absolute
# max_chars = 4000
#
# [providers.notes]           # last N entries of a file
# type = "file-tail"
# path = "~/notes.md"
# entry_pattern = '^# \\['     # lines that start an entry (omit for last N lines)
# entries = 3
#
# [providers.mail]            # any HTTP search endpoint; {query} <- arg or task title
# type = "http"
# url = "http://localhost:5001/api/search?q={query}&limit=5"
# json_path = "results"
# fields = ["from", "subject", "date", "body"]
# private = true              # skipped by `agentboard prompt --public`
# redact = ["\\\\b\\\\d{3}-\\\\d{3}-\\\\d{4}\\\\b"]
#
# [providers.git]             # any shell command; {arg} and {title} are substituted
# type = "command"
# run = "git log --oneline -10"

# [ui]
# dispatch = false            # hide Copy prompt and the prompt preview (shown by default)

# [prompt]
# template_file = "prompt.md"  # replaces the built-in template
'''


def _store():
    return Store(find_dir())


def cmd_init(a):
    d = Path.cwd() / DIR_NAME
    d.mkdir(exist_ok=True)
    cfg = d / "config.toml"
    if not cfg.exists():
        cfg.write_text(SAMPLE_CONFIG)
    (d / "tasks.json").touch()
    if not (d / "tasks.json").read_text().strip():
        (d / "tasks.json").write_text('{"tasks": []}')
    print(f"initialized {d}\nnext: agentboard add \"My first task\" --status todo && agentboard serve")


def cmd_add(a):
    t = _store().add(a.title, a.description or "", a.status, a.ctx, a.id)
    print(f"added {t['id']} ({t['status']})")


def cmd_list(a):
    for t in _store().load():
        if t.get("archived") and not a.all:
            continue
        if a.status and t["status"] != a.status:
            continue
        who = f"  [{t['agent']}]" if t.get("agent") else ""
        print(f"{t['id']:30} {t['status']:8} {t.get('progress', 0):3}%{who}  {t['title']}")


def _agent_name(a):
    name = a.name or os.environ.get("AGENTBOARD_NAME")
    if not name:
        raise BoardError("give --name (or set AGENTBOARD_NAME) so the board can show who is working")
    return name


def cmd_start(a):
    t = _store().start(a.title, _agent_name(a), a.color or os.environ.get("AGENTBOARD_COLOR"),
                       a.description or "", a.id)
    print(t["id"])  # agents use this id for update/done


INSTRUCTIONS = """\
## Agent board

This project tracks agent work on a shared board (`agentboard`). When you begin a distinct piece of work:

    ID=$(agentboard start "<short title>" --name "<your session name>" [--color <color>])
    agentboard update "$ID" <0-100> "<one-line status>"     # at meaningful steps
    agentboard review "$ID" "<one-line result>"                # work complete -> the USER signs off and marks it done
    agentboard ask "$ID" "<one-line question>"                 # ONLY if blocked on the user; keep working after they answer

NEVER mark your own task done. Finish with `review` and stop. Run
`agentboard done "$ID"` only if the user explicitly tells you to.

If you are handed a task id instead, run `agentboard claim <id> --name "<your session name>"`.
Use your own session name (and color, if you have one) so people can tell agents apart.
Create one task per deliverable, not per command. Keep titles short and status lines to one line.
"""


def cmd_instructions(a):
    print(INSTRUCTIONS.replace("agentboard ", f"{promptlib.agentboard_cmd(find_dir())} ") if a.absolute else INSTRUCTIONS)


def cmd_demo(a):
    """Fill the board with sample work so the UI has something to show. Idempotent."""
    s = _store()

    def seed(fn, *args, **kw):
        try:
            fn(*args, **kw)
        except BoardError:
            pass  # already seeded on an earlier run

    seed(s.add,"Write release notes", "v2.4 changelog from merged PRs.", "todo", task_id="demo-release-notes")
    seed(s.add, "Audit npm dependencies", "Flag anything unmaintained or with open CVEs.", "backlog", task_id="demo-audit")
    seed(s.start, "Refactor billing module", "atlas", "#3b82f6", task_id="demo-billing")
    for pct, text in ((20, "Mapped call sites (41 files)"), (45, "Extracted BillingService, tests green"),
                      (70, "Updating call sites in invoices/")):
        seed(s.update, "demo-billing", pct, text)
    seed(s.start, "Draft API docs", "scribe", "#f97316", task_id="demo-docs")
    seed(s.update, "demo-docs", 30, "Reading route handlers")
    seed(s.start, "Set up CI", "bolt", "#8b5cf6", task_id="demo-ci")
    seed(s.update, "demo-ci", text="GitHub Actions: lint, test, deploy in 3 jobs", status="done")
    print("added sample tasks (ids start with demo-); remove with: agentboard rm --demo")
    if a.live:
        _demo_live(s, a.minutes)


def _demo_live(s, minutes):
    """Simulate agents working so the board and HUD have live activity."""
    import random
    import time
    agents = [("nova", "#22d3ee"), ("atlas", "#3b82f6"), ("scribe", "#f97316"), ("echo", "#f472b6")]
    titles = ["Tune cache eviction", "Backfill audit log", "Split payments worker", "Harden webhook retries",
              "Trim bundle size", "Index search facets", "Rotate API keys", "Profile slow queries"]
    steps = ["Reading code", "Mapping call sites", "Writing tests", "Refactoring", "Running test suite",
             "Fixing edge cases", "Updating docs", "Benchmarking"]
    end = time.time() + minutes * 60
    n = max([int(t["id"].rsplit("-", 1)[-1]) for t in s.load()
             if t["id"].startswith("demo-live-") and t["id"].rsplit("-", 1)[-1].isdigit()] or [0])
    print(f"live demo for {minutes:g} min — open the board, press h for the HUD, sound on. Ctrl+C stops.")
    try:
        while time.time() < end:
            doing = [t for t in s.load() if t["status"] == "doing" and t["id"].startswith("demo-")]
            if len(doing) < 2:
                name, color = random.choice(agents)
                n += 1
                s.start(random.choice(titles), name, color, task_id=f"demo-live-{n}")
            elif doing:
                t = random.choice(doing)
                if t.get("needs_input"):
                    if random.random() < .25:
                        s.update(t["id"], t.get("progress", 0), "User answered — resuming")
                    time.sleep(random.uniform(3, 7))
                    continue
                if t.get("review"):
                    if random.random() < .3:   # the "user" signs off
                        s.update(t["id"], 100, t.get("result") or "Approved", status="done")
                    time.sleep(random.uniform(3, 7))
                    continue
                if random.random() < .07 and not any(x.get("needs_input") for x in doing):
                    s.ask(t["id"], random.choice(["Deploy to staging or prod?", "OK to drop the legacy column?",
                                                  "Retry limit: 3 or 5?", "Use the new API key or rotate?"]))
                    time.sleep(random.uniform(3, 7))
                    continue
                p = min(100, t.get("progress", 0) + random.randint(3, 9))
                if p >= 100:
                    s.review(t["id"], random.choice(["Shipped", "Merged", "All tests green"]))
                else:
                    s.update(t["id"], p, random.choice(steps))
            time.sleep(random.uniform(3, 7))
    except KeyboardInterrupt:
        pass


def cmd_clear(a):
    print(f"archived {len(_store().clear_done())} done task(s)")


def cmd_rm(a):
    s = _store()
    ids = [t["id"] for t in s.load() if t["id"].startswith("demo-")] if a.demo else [a.id]
    for i in ids:
        s.delete(i)
    print(f"removed {len(ids)} task(s)")


def cmd_claim(a):
    name = _agent_name(a)
    t = _store().claim(a.id, name, a.color or os.environ.get("AGENTBOARD_COLOR"), a.force)
    print(f"claimed {t['id']} as {name}")


def cmd_update(a):
    t = _store().update(a.id, a.progress, a.text)
    print(f"{t['id']}: {t['progress']}%")


def cmd_ask(a):
    t = _store().ask(a.id, a.question)
    print(f"{t['id']}: waiting on user — {a.question}")


def cmd_review(a):
    t = _store().review(a.id, a.text)
    print(f"{t['id']}: ready for review — waiting on the user to mark it done")


def cmd_done(a):
    _store().update(a.id, text=a.text or "", status="done")
    print(f"{a.id}: done")


def cmd_prompt(a):
    s = _store()
    text, warnings = promptlib.build_prompt(Store.get(s.load(), a.id), s.dir, public=a.public)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(text)


def cmd_rebuild(a):
    s = _store()
    ids = [t["id"] for t in s.load()] if a.all else [a.id]
    with s.transaction() as tasks:
        for tid in ids:
            t = Store.get(tasks, tid)
            t["prompt"], warnings = promptlib.build_prompt(t, s.dir)
            for w in warnings:
                print(f"{tid}: warning: {w}", file=sys.stderr)
    print(f"rebuilt {len(ids)} prompt(s)")


def cmd_serve(a):
    serve(_store(), a.port, not a.no_open)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentboard", description="Kanban board for parallel CLI agents")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "create .agentboard/ in the current directory")
    sp = add("add", cmd_add, "add a task")
    sp.add_argument("title")
    sp.add_argument("-d", "--description")
    sp.add_argument("--status", default="backlog", choices=["backlog", "todo", "doing", "done"])
    sp.add_argument("--ctx", action="append", default=[], metavar="PROVIDER[:ARG]")
    sp.add_argument("--id")
    sp = add("list", cmd_list, "list tasks")
    sp.add_argument("--status")
    sp.add_argument("--all", action="store_true", help="include archived tasks")
    add("clear", cmd_clear, "archive all Done tasks (kept for history and the HUD)")
    sp = add("start", cmd_start, "agent: announce new work (creates a task in doing, prints its id)")
    sp.add_argument("title")
    sp.add_argument("-d", "--description")
    sp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    sp.add_argument("--color", help="(or $AGENTBOARD_COLOR)")
    sp.add_argument("--id")
    sp = add("instructions", cmd_instructions, "print a snippet to paste into CLAUDE.md / AGENTS.md")
    sp.add_argument("--absolute", action="store_true", help="embed absolute command + board path (works from any directory)")
    sp = add("demo", cmd_demo, "add sample tasks to see the board")
    sp.add_argument("--live", action="store_true", help="then simulate agents working (great with the HUD)")
    sp.add_argument("--minutes", type=float, default=5)
    sp = add("rm", cmd_rm, "remove a task")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--demo", action="store_true", help="remove all demo tasks")
    sp = add("claim", cmd_claim, "agent: take a task (moves it to doing)")
    sp.add_argument("id")
    sp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    sp.add_argument("--color")
    sp.add_argument("--force", action="store_true")
    sp = add("update", cmd_update, "agent: report progress")
    sp.add_argument("id")
    sp.add_argument("progress", type=int)
    sp.add_argument("text", nargs="?")
    sp = add("ask", cmd_ask, "agent: flag that you are blocked on the user")
    sp.add_argument("id")
    sp.add_argument("question")
    sp = add("review", cmd_review, "agent: work complete — hand to the user for sign-off")
    sp.add_argument("id")
    sp.add_argument("text", help="one-line result")
    sp = add("done", cmd_done, "USER-APPROVED completion (agents: use review instead)")
    sp.add_argument("id")
    sp.add_argument("text", nargs="?")
    sp = add("prompt", cmd_prompt, "print a task's assembled prompt")
    sp.add_argument("id")
    sp.add_argument("--public", action="store_true", help="skip private providers")
    sp = add("rebuild", cmd_rebuild, "re-run providers and store prompt(s)")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--all", action="store_true")
    sp = add("serve", cmd_serve, "run the board at http://localhost:8765")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-open", action="store_true")

    a = p.parse_args(argv)
    if a.cmd == "rebuild" and not (a.all or a.id):
        p.error("give a task id or --all")
    if a.cmd == "rm" and not (a.demo or a.id):
        p.error("give a task id or --demo")
    try:
        a.fn(a)
    except BoardError as e:
        sys.exit(f"agentboard: {e}")


if __name__ == "__main__":
    main()
