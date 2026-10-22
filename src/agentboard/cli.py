"""agentboard command line."""
import argparse
import os
import shlex
import subprocess
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
    t = _store().add(a.title, a.description or "", a.status, a.ctx, a.id, a.project, blocked_by=a.blocked_by)
    print(f"added {t['id']} ({t['status']})")


def cmd_list(a):
    for t in _store().load():
        if t.get("archived") and not a.all:
            continue
        if a.status and t["status"] != a.status:
            continue
        who = f"  [{t['agent']}]" if t.get("agent") else ""
        print(f"{t['id']:30} {t['status']:8} {t.get('progress', 0):3}%{who}  {t['title']}")


def cmd_project_add(a):
    p = _store().add_project(a.name, a.color, a.description or "", a.id)
    print(f"added project {p['id']}")


def cmd_project_list(a):
    for p in _store().load_projects():
        print(f"{p['id']:30} {p['name']}")


def cmd_project_edit(a):
    p = _store().update_project(a.id, a.name, a.color, a.description)
    print(f"updated project {p['id']}")


def cmd_project_rm(a):
    _store().delete_project(a.id)
    print(f"removed project {a.id}")


def cmd_project_assign(a):
    t = _store().set_project(a.task_id, a.project_id)
    print(f"{t['id']}: tied to project {a.project_id}")


def cmd_project_unassign(a):
    t = _store().set_project(a.task_id, None)
    print(f"{t['id']}: untied from its project")


WAIT_FLAGS = ("review", "needs_input")  # pseudo-targets: a flag on the task, not a column


def _wait_result(t, target):
    """A result line once `wait --status target` should stop on t, else None.

    'review' and 'needs_input' always end the wait early even when they aren't the target:
    a task stuck on 'review' may never reach 'done' until a human clicks Mark done, and
    'needs_input' means progress is stalled on the user, not on more polling.
    """
    if target == "review" and t.get("review"):
        return f"ready for review — {t.get('result', '')}"
    if target == "needs_input" and t.get("needs_input"):
        return f"needs input — {t.get('question', '')}"
    if target not in WAIT_FLAGS and t["status"] == target:
        return f"reached {target}"
    if target not in WAIT_FLAGS and t.get("review"):
        return f"ready for review (target was {target}) — {t.get('result', '')}"
    if target != "needs_input" and t.get("needs_input"):
        return f"needs input (target was {target}) — {t.get('question', '')}"
    return None


def cmd_wait(a):
    """Block (polling tasks.json) until a task reaches --status, or flags review/needs input."""
    s = _store()
    start = time.time()
    try:
        while True:
            t = Store.get(s.load(), a.id)
            msg = _wait_result(t, a.status)
            if msg:
                print(f"{a.id}: {msg}")
                return
            if a.timeout and time.time() - start >= a.timeout:
                sys.exit(f"agentboard: wait timed out after {a.timeout}s ({a.id} still {t['status']})")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass


def _agent_name(a):
    name = a.name or os.environ.get("AGENTBOARD_NAME")
    if not name:
        raise BoardError("give --name (or set AGENTBOARD_NAME) so the board can show who is working")
    return name


SPAWN_PALETTE = ["#22d3ee", "#3b82f6", "#f97316", "#f472b6", "#8b5cf6", "#10b981"]


def _as_escape(s):
    """Escape a string for embedding inside a double-quoted AppleScript literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _hex_rgb(color):
    """'#rrggbb' -> (r, g, b) scaled to AppleScript's 0-65535 range, or None if not hex."""
    c = color.lstrip("#")
    if len(c) != 6:
        return None
    try:
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return (r * 257, g * 257, b * 257)


def cmd_spawn(a):
    if sys.platform != "darwin":
        raise BoardError("spawn only supports macOS Terminal.app right now")
    names = [n.strip() for n in a.names.split(",") if n.strip()]
    if not names:
        raise BoardError('give at least one name, e.g. agentboard spawn atlas,scribe,bolt')
    colors = [c.strip() for c in a.colors.split(",")] if a.colors else []
    cwd = os.getcwd()
    for i, name in enumerate(names):
        color = colors[i] if i < len(colors) else SPAWN_PALETTE[i % len(SPAWN_PALETTE)]
        cmdline = f"cd {shlex.quote(cwd)} && {a.cmd}"
        lines = ['tell application "Terminal"', "activate",
                 f'set newTab to do script "{_as_escape(cmdline)}"']
        rgb = _hex_rgb(color)
        if rgb:
            lines.append(f"set background color of newTab to {{{rgb[0]}, {rgb[1]}, {rgb[2]}}}")
            lines.append("set normal text color of newTab to {65535, 65535, 65535}")
        lines.append(f'set custom title of newTab to "{_as_escape(name)}"')
        if not a.no_rename:
            lines.append(f"delay {a.delay}")
            lines.append(f'do script "/rename {_as_escape(name)}" in newTab')
            lines.append("delay 0.4")
            lines.append(f'do script "/color {_as_escape(color)}" in newTab')
        lines.append("end tell")
        subprocess.run(["osascript", "-e", "\n".join(lines)], check=True)
    print(f"spawned {len(names)} session(s): {', '.join(names)}")


def cmd_start(a):
    t = _store().start(a.title, _agent_name(a), a.color or os.environ.get("AGENTBOARD_COLOR"),
                       a.description or "", a.id, a.project, blocked_by=a.blocked_by, force=a.force)
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

## Projects

Group related tasks under a project so they show up together on the board:

    agentboard project add "<name>" [--color <color>] [--description "..."]   # prints its id
    agentboard project list
    agentboard project assign <task_id> <project_id>     # tie any existing card to a project
    agentboard project unassign <task_id>                 # untie it
    agentboard add "<title>" --project <project_id>       # or tie it at creation time
    agentboard start "<title>" --name "<you>" --project <project_id>

## Dependencies

Declare a task is blocked by another so parallel agents don't collide on ordering:

    agentboard add "<title>" --blocked-by <task_id>            # repeat --blocked-by for more than one
    agentboard start "<title>" --name "<you>" --blocked-by <task_id>
    agentboard claim <id> --name "<you>"                        # refuses while a blocker isn't done (--force to override)

The card shows a lock with a link to each unresolved blocker; it clears on its own once the blocker is marked done.

## Sync

Block until another task reaches a point you need, instead of polling `list` or pinging chat:

    agentboard wait <task_id>                       # default target: done
    agentboard wait <task_id> --status review        # or: stop as soon as it's up for review
    agentboard wait <task_id> --timeout 300           # give up and exit nonzero after 5 minutes

`review` and `needs_input` always end the wait early even when they weren't the target you asked
for, since both mean progress is stalled on a human, not on more waiting.
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
    sp.add_argument("--project", help="project id to tie this task to")
    sp.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID",
                     help="task id this depends on; repeat for multiple")
    sp = add("list", cmd_list, "list tasks")
    sp.add_argument("--status")
    sp.add_argument("--all", action="store_true", help="include archived tasks")
    add("clear", cmd_clear, "archive all Done tasks (kept for history and the HUD)")
    sp = add("spawn", cmd_spawn, "open a new Terminal window per name, cd here, launch an agent in each (macOS)")
    sp.add_argument("names", help="comma-separated session names, e.g. atlas,scribe,bolt")
    sp.add_argument("--colors", help="comma-separated hex colors, one per name (default: built-in palette)")
    sp.add_argument("--cmd", default="claude", help="command to run in each window (default: claude)")
    sp.add_argument("--delay", type=float, default=3.0,
                     help="seconds to wait for the agent to start before sending /rename and /color (default: 3)")
    sp.add_argument("--no-rename", action="store_true", help="skip sending /rename and /color after launch")
    sp = add("start", cmd_start, "agent: announce new work (creates a task in doing, prints its id)")
    sp.add_argument("title")
    sp.add_argument("-d", "--description")
    sp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    sp.add_argument("--color", help="(or $AGENTBOARD_COLOR)")
    sp.add_argument("--id")
    sp.add_argument("--project", help="project id to tie this task to")
    sp.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID",
                     help="task id this depends on; repeat for multiple")
    sp.add_argument("--force", action="store_true", help="start even if a blocker is not done")
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
    sp = add("wait", cmd_wait, "block (polling) until a task reaches a status — sync on another agent's work")
    sp.add_argument("id")
    sp.add_argument("--status", default="done", choices=["backlog", "todo", "doing", "done", "review", "needs_input"],
                     help="target to wait for (default: done); 'review'/'needs_input' also always end the wait early "
                          "when they aren't the target, since those are blocked-on-a-human moments too")
    sp.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds (default 2)")
    sp.add_argument("--timeout", type=float, help="give up and exit nonzero after this many seconds (default: wait forever)")
    sp = add("prompt", cmd_prompt, "print a task's assembled prompt")
    sp.add_argument("id")
    sp.add_argument("--public", action="store_true", help="skip private providers")
    sp = add("rebuild", cmd_rebuild, "re-run providers and store prompt(s)")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--all", action="store_true")
    sp = add("serve", cmd_serve, "run the board at http://localhost:8765")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-open", action="store_true")

    sp = sub.add_parser("project", help="manage projects (groups of tasks)")
    psub = sp.add_subparsers(dest="project_cmd", required=True)

    def padd(name, fn, help):
        psp = psub.add_parser(name, help=help)
        psp.set_defaults(fn=fn)
        return psp

    psp = padd("add", cmd_project_add, "create a project")
    psp.add_argument("name")
    psp.add_argument("-d", "--description")
    psp.add_argument("--color")
    psp.add_argument("--id")
    padd("list", cmd_project_list, "list projects")
    psp = padd("edit", cmd_project_edit, "rename/recolor/describe a project")
    psp.add_argument("id")
    psp.add_argument("--name")
    psp.add_argument("--color")
    psp.add_argument("--description")
    psp = padd("rm", cmd_project_rm, "delete a project (untying any tasks from it)")
    psp.add_argument("id")
    psp = padd("assign", cmd_project_assign, "tie an existing task to a project")
    psp.add_argument("task_id")
    psp.add_argument("project_id")
    psp = padd("unassign", cmd_project_unassign, "untie a task from its project")
    psp.add_argument("task_id")

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
