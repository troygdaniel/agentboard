"""agentboard command line."""
import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from . import __version__
from . import backup as backuplib
from . import hud as hudlib
from . import prompt as promptlib
from . import runs as runslib
from . import sms as smslib
from .server import serve
from . import boards as boardlib
from .store import DIR_NAME, BoardError, Store, find_dir, subtask_counts

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

# [run]                       # one-shot agents: `agentboard run <card>`
# claude = "claude"           # the claude binary (default: the one on PATH)
# budget_usd = 5              # hard spend cap per run, passed to claude as --max-budget-usd
# max_minutes = 45            # hard wall-clock limit per run

# [sms]                       # text the board (docs: README "Text the board"); off until enabled
# enabled = true
# allowed = ["+14165550123"]  # only these numbers are heard; everyone else is ignored silently
# public_url = "https://<your tunnel>/sms"   # exactly the URL set in Twilio: it is part of the signature
# token_env = "AGENTBOARD_TWILIO_AUTH_TOKEN" # the auth token is read from this environment variable, never from a file here
# rate_per_hour = 30

# [board]
# stale_minutes = 120         # flag a Doing task as stale/abandoned after this many idle minutes
#                              # (default 120; much longer than the board's 10-min "quiet" warning).
#                              # Surfaced by `agentboard list --stale`, a red card marker, and the HUD.

# [notify]                    # native macOS notification when a card needs input or is ready for review
# enabled = true               # off by default; osascript only, no new dependency
# sound = "Glass"               # optional: a macOS notification sound name (omit for silent)

# [backup]                    # snapshots are always kept in .agentboard/backups (hourly, 48 hours + 30 days); this adds a nightly copy elsewhere
# sync_dir = "~/Library/Mobile Documents/com~apple~CloudDocs/agentboard-backups"   # an iCloud Drive or Google Drive folder on this Mac

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
    ignored = _gitignore_board(Path.cwd())
    print(f"initialized {d}" + (f"\nadded {DIR_NAME}/ to .gitignore (task data can hold private context)" if ignored else "")
          + "\nnext: agentboard add \"My first task\" --status todo && agentboard serve")


def _gitignore_board(root):
    """Add `.agentboard/` to the project's .gitignore unless it is already ignored. Creates the file
    when the project has none. Returns True when a line was added."""
    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if any(l.strip().rstrip("/") in (DIR_NAME, "/" + DIR_NAME) for l in lines):
        return False
    body = "\n".join(lines).rstrip("\n")
    body = (body + "\n" if body else "") + f"# agentboard task data and local config (may contain private context)\n{DIR_NAME}/\n"
    gi.write_text(body)
    return True


def cmd_add(a):
    t = _store().add(a.title, a.description or "", a.status, a.ctx, a.id, a.project, blocked_by=a.blocked_by,
                     parent_id=a.parent)
    print(f"added {t['id']} ({t['status']})")


def cmd_list(a):
    s = _store()
    threshold = hudlib.stale_minutes(promptlib.load_config(s.dir))
    tasks = s.load()
    counts = subtask_counts(tasks)
    ids = {t["id"] for t in tasks}
    for t in _tree_order(tasks):
        if t.get("archived") and not a.all:
            continue
        if a.status and t["status"] != a.status:
            continue
        idle = hudlib.minutes_idle(t)
        stale = idle is not None and idle >= threshold
        if a.stale and not stale:
            continue
        who = f"  [{t['agent']}]" if t.get("agent") else ""
        flag = f"  ⚠ STALE ({int(idle)}m idle)" if stale else ""
        sub = t.get("parent_id") in ids
        n, d = counts.get(t["id"], (0, 0))
        kids = f"  [{d}/{n} subtasks]" if n else ""
        name = f"  ↳ {t['id']}" if sub else t["id"]   # subtasks hang under their parent
        print(f"{name:30} {t['status']:8} {'Σ' if n else ' '}{t.get('progress', 0):3}%{who}{kids}{flag}  {t['title']}")


def _tree_order(tasks):
    """Board order, but each subtask listed right under its parent."""
    ids = {t["id"] for t in tasks}
    for t in tasks:
        if t.get("parent_id") in ids:
            continue
        yield t
        yield from (k for k in tasks if k.get("parent_id") == t["id"])


TAIL_FEED_CAP = 500   # generous enough that a burst of activity between polls can't overrun a single snapshot


def _tail_fmt(e):
    at = e["at"].split("T", 1)[1] if "T" in e["at"] else e["at"]
    agent = e.get("agent") or "-"
    return f"{at}  {agent:<12.12}  {e.get('label') or e['task']:<30.30}  {e['text']}"


def _tail_fresh(events, last_at, seen):
    """events: newest-first, as from hud.build(). Returns (new events oldest-first, advanced last_at, advanced seen).

    Same-second collisions (two log entries sharing a timestamp) are disambiguated with a (task, at, text) set
    rather than just the watermark, since the log's timestamp resolution is whole seconds.
    """
    fresh = [e for e in events
             if e["at"] > last_at or (e["at"] == last_at and (e["task"], e["at"], e["text"]) not in seen)]
    if events:
        last_at = events[0]["at"]
        seen = {(e["task"], e["at"], e["text"]) for e in events if e["at"] == last_at}
    return list(reversed(fresh)), last_at, seen


def cmd_tail(a):
    """Watch board activity live in the terminal — the same event feed the HUD shows, polled from tasks.json."""
    s = _store()

    def snapshot():
        return hudlib.build(s.load(), feed_limit=TAIL_FEED_CAP)["events"]  # newest-first

    events = snapshot()
    # seed the watermark from the true newest event regardless of how much history --lines asks to print,
    # so a smaller --lines can never cause the first poll to replay what it skipped
    last_at = events[0]["at"] if events else time.strftime("%Y-%m-%dT%H:%M:%S")
    seen = {(e["task"], e["at"], e["text"]) for e in events if e["at"] == last_at}
    for e in reversed(events[:max(0, a.lines)]):
        print(_tail_fmt(e), flush=True)   # flush: stdout is block-buffered when piped/redirected, not a tty
    try:
        while True:
            time.sleep(a.interval)
            fresh, last_at, seen = _tail_fresh(snapshot(), last_at, seen)
            for e in fresh:
                print(_tail_fmt(e), flush=True)
    except KeyboardInterrupt:
        pass


def cmd_report(a):
    """Markdown recap of what was completed on a day (default: today), grouped by agent.

    Read-only; built on the same 'marked done' / activity-log aggregation the HUD uses
    (hud.done_on / hud.events_on), not a separate tracking mechanism. Paste it into a
    standup or a daily log.
    """
    if a.date:
        try:
            day = date.fromisoformat(a.date)
        except ValueError:
            raise BoardError(f"invalid --date '{a.date}'; use YYYY-MM-DD")
    else:
        day = date.today()
    tasks = _store().load()
    done = hudlib.done_on(tasks, day)
    events = hudlib.events_on(tasks, day)
    finished = [d for d in done if not d["partial"]]
    s = lambda n: "" if n == 1 else "s"

    print(f"# Daily recap — {day.isoformat()}")
    print()
    if not done:
        print(f"No tasks completed on {day.isoformat()}.")
    else:
        by_agent = {}
        for d in done:
            by_agent.setdefault(d["agent"] or "Unassigned", []).append(d)
        print(f"**{len(finished)} task{s(len(finished))} done** across {len(by_agent)} agent{s(len(by_agent))}"
              if finished else f"**No task finished**, {len(done)} in progress")
        print()
        for agent in sorted(by_agent):
            print(f"## {agent}")
            for d in by_agent[agent]:
                line = f"- **{d['title']}**"
                if d["partial"]:
                    line += f" _(in progress, {d['n_done']}/{d['n']} subtasks done)_"
                elif d["result"]:
                    line += f" — {d['result']}"
                print(line)
                for k in d["subs"]:   # subtasks grouped under their parent
                    print(f"  - {k['title']}" + (f" — {k['result']}" if k["result"] else ""))
            print()
    print(f"_{events} event{s(events)} logged on {day.isoformat()}._")


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


def _chat_line(m):
    who = f"{m['sender']} (you)" if m["kind"] == "user" else m["sender"]
    return f"[{m['at']}] {who}: {m['text']}"


def cmd_chat_send(a):
    name = a.name or os.environ.get("AGENTBOARD_NAME") or ("Troy" if a.user else None)
    if not name:
        raise BoardError("give --name (or set AGENTBOARD_NAME) so the board can show who's talking")
    m = _store().chat_send(name, a.text, kind="user" if a.user else "agent")
    print(_chat_line(m))


def cmd_chat_tail(a):
    """Print recent chat; --follow polls and streams new messages (Ctrl+C stops)."""
    s = _store()
    msgs = s.chat_list(limit=a.limit)
    for m in msgs:
        print(_chat_line(m))
    if not a.follow:
        return
    last = msgs[-1]["seq"] if msgs else 0
    try:
        while True:
            time.sleep(a.interval)
            for m in s.chat_list(after=last):
                print(_chat_line(m))
                last = m["seq"]
    except KeyboardInterrupt:
        pass


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
    if target in WAIT_FLAGS and t["status"] == "done":   # signed off without a pause on the way: nothing left to wait for
        return f"done (target was {target})"
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


# Kept out of the status-color families (--warn/--hwarn amber ~25-50°, --ok/--hok green ~145-165°,
# --err/--hbad red near 0/360°): an agent's color shows up on its cards' avatar ring and progress bar
# fill at all times, not just during ask/review/abandoned, so a palette hue in one of those bands
# would make a normal in-progress card from that agent misread as needing attention at a glance.
SPAWN_PALETTE = ["#22d3ee", "#6366f1", "#f472b6", "#3b82f6", "#d946ef", "#8b5cf6"]


def _as_escape(s):
    """Escape a string for embedding inside a double-quoted AppleScript literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _notify_cfg(board_dir):
    cfg = promptlib.load_config(board_dir).get("notify", {})
    return bool(cfg.get("enabled")), cfg.get("sound")


def _notify(board_dir, title, subtitle, body):
    """Native macOS notification via osascript — same no-dependency mechanism as `spawn`.

    Opt-in and off by default (see [notify] in config.toml); a notification failing or the
    platform not supporting it should never break an agent's ask/review, so this never raises.
    """
    if sys.platform != "darwin":
        return
    enabled, sound = _notify_cfg(board_dir)
    if not enabled:
        return
    script = f'display notification "{_as_escape(body)}" with title "{_as_escape(title)}" subtitle "{_as_escape(subtitle)}"'
    if sound:
        script += f' sound name "{_as_escape(sound)}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except OSError:
        pass


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
    t, created = _store().start_card(a.title, _agent_name(a), a.color or os.environ.get("AGENTBOARD_COLOR"),
                                     a.description or "", a.id, a.project, blocked_by=a.blocked_by, force=a.force,
                                     parent_id=a.parent)
    if not created:
        print(f"agentboard: you already hold {t['id']}; logged on it, no twin made", file=sys.stderr)
    print(t["id"])  # agents use this id for update/done; the sibling list goes to stderr so $(...) still captures only the id
    if a.parent:
        _print_subtasks(_store().load(), a.parent, file=sys.stderr)


INSTRUCTIONS = """\
## Agent board

This project tracks agent work on a shared board (`agentboard`). When you begin a distinct piece of work:

    ID=$(agentboard start "<short title>" --name "<your session name>" [--color <color>])
    agentboard update "$ID" <0-100> "<one-line status>"     # your REAL % done, updated every time it changes
    agentboard review "$ID" "<one-line result>"                # work complete -> the USER signs off and marks it done
    agentboard ask "$ID" "<one-line question>"                 # ONLY if blocked on the user; keep working after they answer

The percentage is what the list and HUD show at a glance, without anyone opening the card — keep
it current. Call `update` again whenever your estimate changes, not just at fixed checkpoints, and
walk it back if you discover more work than you thought; don't leave it sitting at a stale number.

Add `--body "<markdown>"` (or `--body-file <path>` for multi-line content) to `review`/`ask`
for a proper recap, diff, or report — it renders as formatted markdown in the detail panel,
which opens automatically when your card needs input or is ready for review.

NEVER mark your own task done. Finish with `review` and stop. Run
`agentboard done "$ID"` only if the user explicitly tells you to.

If you are handed a task id instead, run `agentboard claim <id> --name "<your session name>"`.
Use your own session name (and color, if you have one) so people can tell agents apart.
Create one task per deliverable, not per command. Keep titles short and status lines to one line.

Before claiming or starting a card, if anything about it is ambiguous, ask your orchestrator/coordinating
session a one-line question (e.g. via SendMessage) and wait for its answer first. It has visibility into
the whole board and can often answer without bothering the user; it escalates to them if it can't. This
is a one-time check before you start, not an ongoing back-and-forth once work is underway.

## Projects

Group related tasks under a project so they show up together on the board:

    agentboard project add "<name>" [--color <color>] [--description "..."]   # prints its id
    agentboard project list
    agentboard project assign <task_id> <project_id>     # tie any existing card to a project
    agentboard project unassign <task_id>                 # untie it
    agentboard add "<title>" --project <project_id>       # or tie it at creation time
    agentboard start "<title>" --name "<you>" --project <project_id>

## Subtasks

A big card can be split into subtasks (one level deep). A subtask is a normal task with a parent:

    agentboard add "<title>" --parent <parent_id>              # Troy/ORCH at planning time; follows the parent's column
    agentboard start "<title>" --name "<you>" --parent <id>    # an agent adding one mid-flight

When you claim a parent that has no subtasks yet, break it down first (same command). `claim <parent>`
takes every subtask with it. Then work the subtasks, not the parent (updating a subtask before its parent is in Doing is refused):

    agentboard update <sub_id> <0-100> "<one-line status>"     # a subtask at 100% closes itself: no review step
    agentboard review <parent_id> "<one-line result>"          # the deliverable is ready; open subtasks close with it

The parent's % is computed (the mean of its subtasks, shown with a Σ), so `update <parent>` only sets its
status line. Never call `review` or `done` on a subtask. Finished subtasks stay in their parent's card, shown as
completed, while the parent stays in Doing. `rm <parent>` and `done <parent>` take the remaining subtasks with them.

## Talking to other agents

Coordinating with another agent — who's on what, asking for a hand, splitting or handing off
work — goes in the shared chat, not only a private message, so the user can see it and jump in:

    agentboard chat send "<message>" --name "<your session name>"
    agentboard chat tail                                   # catch up, including the user jumping in
    agentboard chat tail --follow                           # keep watching live (Ctrl+C stops)

Write it like a quick Slack message to a teammate, not a status report: short, plain, skimmable in
a second — what you're doing or what you need, then stop.

    Good:          "grabbing the HUD legend task, shout if you're already on it"
    Good:          "done with the scroll-jump fix, up for review"
    Over-formal:   "I have completed the scroll-jump bug fix. The render() function's focus-restore
                    logic now uses preventScroll:true. The card is ready for your review."

Got a lot to say (a commit audit, a multi-part handoff)? Say it briefly and point at the card/task
id for the detail — don't paste the whole report inline.

Check it when you're blocked on coordinating with another agent, same as you'd check for a reply
to a private message. Use a private message instead only for something that genuinely shouldn't
be visible on the board.

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
    seed(s.start, "Draft API docs", "scribe", "#6366f1", task_id="demo-docs")
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
    agents = [("nova", "#22d3ee"), ("atlas", "#3b82f6"), ("scribe", "#6366f1"), ("echo", "#f472b6")]
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
                    q = random.choice(["Deploy to staging or prod?", "OK to drop the legacy column?",
                                        "Retry limit: 3 or 5?", "Use the new API key or rotate?"])
                    s.ask(t["id"], q)
                    _notify(s.dir, f"{t.get('agent') or 'An agent'} needs your input", t["title"], q)
                    time.sleep(random.uniform(3, 7))
                    continue
                p = min(100, t.get("progress", 0) + random.randint(3, 9))
                if p >= 100:
                    result = random.choice(["Shipped", "Merged", "All tests green"])
                    s.review(t["id"], result)
                    _notify(s.dir, f"{t.get('agent') or 'An agent'} ready for review", t["title"], result)
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
    n = 0
    for i in ids:
        gone = {t["id"] for t in s.load()}
        if i not in gone:   # already taken out with its parent
            continue
        s.delete(i)
        n += len(gone - {t["id"] for t in s.load()})   # a parent takes its subtasks with it
    print(f"removed {n} task(s)")


def cmd_claim(a):
    name = _agent_name(a)
    s = _store()
    t = s.claim(a.id, name, a.color or os.environ.get("AGENTBOARD_COLOR"), a.force)
    print(f"claimed {t['id']} as {name}")
    _print_subtasks(s.load(), t["id"])


def _print_subtasks(tasks, parent_id, file=None):
    """Under a parent, list its subtasks (id  title) so the ids to update are in the agent's terminal."""
    kids = [k for k in tasks if k.get("parent_id") == parent_id]
    if not kids:
        return
    print(f"{parent_id} is split into subtasks: update these (its % is computed from them), not the parent:", file=file)
    for k in kids:
        print(f"  {k['id']}  {k['title']}" + ("  (done)" if k["status"] == "done" else ""), file=file)


def _pct_and_text(a):
    """`update ID 50 "text"`, or text-only `update ID "text"` (the % stays as it was)."""
    try:
        return int(a.progress), a.text
    except ValueError:
        if a.text is not None:
            raise BoardError(f"progress must be a number from 0 to 100, got {a.progress!r}") from None
        return None, a.progress


def cmd_update(a):
    s = _store()
    kids = [k for k in s.load() if k.get("parent_id") == a.id]
    pct, text = _pct_and_text(a)
    t = s.update(a.id, pct, text)
    if kids:
        print(f"{t['id']}: Σ {t['progress']}% (a parent's % is computed from its subtasks; update those instead)")
    elif t["status"] == "done" and t.get("parent_id"):
        print(f"{t['id']}: 100% — subtask done")
    else:
        print(f"{t['id']}: {t['progress']}%")


def _read_body(a):
    """--body-file wins if given (handles multi-line content without shell quoting pain)."""
    if a.body_file:
        try:
            return Path(a.body_file).expanduser().read_text()
        except OSError as e:
            raise BoardError(f"could not read --body-file: {e}") from e
    return a.body


def cmd_ask(a):
    s = _store()
    t = s.ask(a.id, a.question, _read_body(a))
    _notify(s.dir, f"{t.get('agent') or 'An agent'} needs your input", t["title"], a.question)
    print(f"{t['id']}: waiting on user — {a.question}")


def cmd_review(a):
    s = _store()
    t = s.review(a.id, a.text, _read_body(a))
    if t.get("parent_id"):
        print(f"{t['id']}: subtask finished (100%) — subtasks have no review step; review the parent, {t['parent_id']}, when the deliverable is ready")
        return
    _notify(s.dir, f"{t.get('agent') or 'An agent'} ready for review", t["title"], a.text)
    print(f"{t['id']}: ready for review — waiting on the user to mark it done")


def cmd_done(a):
    # a.text, not `a.text or ""`: an explicit "" would blank out a review's result/status_text
    # (store.update treats "not None" as "replace it"); omitting it should leave them alone.
    _store().update(a.id, text=a.text, status="done")
    print(f"{a.id}: done")


def cmd_prompt(a):
    s = _store()
    all_tasks = s.load()
    text, warnings = promptlib.build_prompt(Store.get(all_tasks, a.id), s.dir, public=a.public, tasks=all_tasks)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(text)


def cmd_rebuild(a):
    s = _store()
    ids = [t["id"] for t in s.load()] if a.all else [a.id]
    with s.transaction() as tasks:
        for tid in ids:
            t = Store.get(tasks, tid)
            t["prompt"], warnings = promptlib.build_prompt(t, s.dir, tasks=tasks)
            for w in warnings:
                print(f"{tid}: warning: {w}", file=sys.stderr)
    print(f"rebuilt {len(ids)} prompt(s)")


def cmd_backup(a):
    s = _store()
    b = s.backups
    if a.list:
        st = b.status()
        for p in b.snapshots():
            ok, msg, n = backuplib.verify_file(p)
            print(f"{p.name:<44} {p.stat().st_size // 1024:>6} KB  {backuplib.human_age((time.time() - p.stat().st_mtime) / 60):<12} {n.get('tasks', '?')} tasks" + ("" if ok else f"  BAD: {msg}"))
        print(f"{st['snapshots']} snapshots; newest {backuplib.human_age(st['last_backup_min'])}; nightly copy " + (f"to {st['sync_dir']} (last {st['last_sync'] or 'never'})" if st["sync_dir"] else "not set ([backup] sync_dir in config.toml)"))
        return
    if a.sync:
        dest = b.sync(force=True)
        print(f"copied to {dest}" if dest else "no sync_dir set in config.toml (or nothing to copy)")
        return
    ok, msg, _ = backuplib.verify_file(s.path)
    if not ok:
        raise BoardError(f"not backing up: the board file is {msg}. Restore a good one with `agentboard restore latest`.")
    dest = b.take(a.label or "")
    b.prune()
    b.sync()
    print(dest)


def cmd_restore(a):
    s = _store()
    b = s.backups
    try:
        src = b.resolve(a.which)
    except FileNotFoundError as e:
        raise BoardError(str(e)) from e
    ok, msg, n = backuplib.verify_file(src)
    if not ok:
        raise BoardError(f"{src.name} is not a good board file: {msg}")
    now_ok, _, now_n = backuplib.verify_file(s.path)
    print(f"restore {src.name}: {n['tasks']} tasks, {n['projects']} projects, {n['chat']} chat messages (the board has " + (f"{now_n['tasks']} tasks now)" if now_ok else "an unreadable file now)"))
    if not a.yes:
        if not sys.stdin.isatty():
            raise BoardError("restore replaces the board; add --yes to do it (the board as it is now is kept first as a before-restore snapshot)")
        if input("replace the board with it? [y/N] ").strip().lower() != "y":
            raise BoardError("not restored")
    with s._lock():
        _, saved = b.restore(a.which)
    print(f"restored. The board as it was is saved as {saved.name}" if saved else "restored.")


def cmd_verify(a):
    s = _store()
    b = s.backups
    bad = 0
    ok, msg, n = backuplib.verify_file(s.path)
    print(f"{'ok ' if ok else 'BAD'} tasks.json  {n.get('tasks', '')} tasks" if ok else f"BAD tasks.json: {msg}")
    bad += not ok
    prev = Path(f"{s.path}.bak")
    if prev.exists():
        ok2, msg2, n2 = backuplib.verify_file(prev)
        print(f"{'ok ' if ok2 else 'BAD'} tasks.json.bak (the version before the last save)" + (f"  {n2['tasks']} tasks" if ok2 else f": {msg2}"))
    files = b.snapshots() if a.all else b.snapshots()[:1]
    for p in files:
        ok3, msg3, n3 = backuplib.verify_file(p)
        print(f"{'ok ' if ok3 else 'BAD'} {p.name}" + (f"  {n3['tasks']} tasks" if ok3 else f": {msg3}"))
        bad += not ok3
    age = b.age_minutes()
    if age is None:
        print("BAD no snapshots yet (run `agentboard backup`)")
        bad += 1
    elif age > backuplib.STALE_MIN:
        print(f"BAD the newest snapshot is {backuplib.human_age(age)}; snapshots are taken when the board is saved or `agentboard serve` runs")
        bad += 1
    else:
        print(f"ok  newest snapshot {backuplib.human_age(age)}")
    sd = b.sync_dir()
    print(f"nightly copy: {sd} (last {b.last_sync() or 'never'})" if sd else "nightly copy: not set ([backup] sync_dir in config.toml)")
    if bad:
        sys.exit(1)


def cmd_dedupe(a):
    plan = _store().dedupe(apply=a.apply)
    if not plan:
        print("no duplicate cards")
        return
    for keep, twin in plan:
        print(f"{'merged' if a.apply else 'would merge'} {twin} into {keep}")
    print(f"{len(plan)} duplicate card(s) merged; a snapshot named before-dedupe was taken first" if a.apply else "dry run: add --apply to merge them")


def cmd_board_new(a):
    d = boardlib.new(a.name, a.path, a.color)
    print(f"created board {a.name} at {d}\nuse it: agentboard --board {a.name} add \"First task\"   (or AGENTBOARD_BOARD={a.name}; `agentboard board use {a.name}` makes it the default outside a project folder)")


def cmd_board_add(a):
    d = Path(a.path).expanduser()
    if not d.is_dir():
        raise BoardError(f"{d} is not a folder")
    boardlib.register(a.name, d, a.color)
    print(f"registered {a.name} -> {d.resolve()}")


def cmd_board_list(a):
    reg = boardlib.load()
    try:
        here = find_dir()
    except BoardError:
        here = None
    rows = [(n, b["path"], b["color"]) for n, b in sorted(reg["boards"].items())]
    if not rows:
        print("no registered boards; create one with `agentboard board new <name>`")
    for n, path, color in rows:
        marks = (" *" if reg["current"] == n else "") + (" (this folder)" if here and boardlib.name_for(here) == n else "")
        print(f"{n:<16} {path}" + (f"  [{color}]" if color else "") + marks)
    if here and boardlib.name_for(here) is None:
        print(f"(this folder's board, not registered: {here})")


def cmd_board_use(a):
    boardlib.use(a.name)
    print(f"current board: {a.name} (used when the folder has no .agentboard and no --board)")


def cmd_board_rm(a):
    boardlib.remove(a.name)
    print(f"forgot {a.name} (its folder and cards are untouched)")


def cmd_run(a):
    s = _store()
    name = a.name or os.environ.get("AGENTBOARD_NAME") or "oneshot"
    if a.detach:
        runslib.check_startable(s, a.id, name, a.force)
        runslib.claude_binary(s.dir)
        tail = [x for flag, v in (("--name", a.name), ("--color", a.color), ("--cwd", a.cwd), ("--budget", a.budget), ("--max-minutes", a.max_minutes))
                if v is not None for x in (flag, str(v))] + (["--force"] if a.force else [])
        pid, log = runslib.detach(tail, s.dir, a.id)
        print(f"{a.id}: run started in the background (supervisor pid {pid}); watch it with `agentboard runs`, stop it with `agentboard runs --kill {a.id}`; log {log}")
        return
    rec = runslib.run_card(s, a.id, name=a.name, color=a.color, cwd=a.cwd, budget=a.budget, minutes=a.max_minutes, force=a.force)
    if rec["status"] != "finished":
        sys.exit(1)


def cmd_runs(a):
    s = _store()
    if a.kill:
        print(f"{a.kill}: {runslib.kill_run(s.dir, a.kill)}")
        return
    rows = runslib.list_lines(s.dir)
    print("\n".join(rows) if rows else "no runs yet")


def cmd_sms_serve(a):
    smslib.serve(_store(), a.port)


def cmd_sms_try(a):
    print(smslib.apply(_store(), " ".join(a.text)))


def cmd_serve(a):
    serve(_store(), a.port, not a.no_open)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentboard", description="Kanban board for parallel CLI agents")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--board", metavar="NAME", help="use this registered board from any folder (or $AGENTBOARD_BOARD); see `agentboard board list`")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "create .agentboard/ in the current directory")
    sp = add("add", cmd_add, "add a task")
    sp.add_argument("title")
    sp.add_argument("-d", "--description")
    sp.add_argument("--status", choices=["backlog", "todo", "doing", "done"],
                    help="column to add to (default: backlog; a subtask follows its parent)")
    sp.add_argument("--ctx", action="append", default=[], metavar="PROVIDER[:ARG]")
    sp.add_argument("--id")
    sp.add_argument("--project", help="project id to tie this task to (a subtask inherits its parent's)")
    sp.add_argument("--parent", metavar="ID", help="make this a subtask of that task (one level deep)")
    sp.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID",
                     help="task id this depends on; repeat for multiple")
    sp = add("list", cmd_list, "list tasks")
    sp.add_argument("--status")
    sp.add_argument("--all", action="store_true", help="include archived tasks")
    sp.add_argument("--stale", action="store_true",
                     help="only show Doing tasks idle past the stale threshold (default "
                          f"{hudlib.ABANDONED_MIN} min; see [board].stale_minutes in config.toml)")
    sp = add("tail", cmd_tail, "watch board activity live in the terminal (same feed as the HUD); Ctrl+C stops")
    sp.add_argument("-n", "--lines", type=int, default=10, help="recent events to print before following (default 10; 0 for none)")
    sp.add_argument("--interval", type=float, default=1.0, help="poll interval in seconds (default 1)")
    sp = add("backup", cmd_backup, "snapshot the board now (hourly ones are automatic); --list shows them")
    sp.add_argument("--label", help="name this snapshot (it is then never pruned), e.g. before-cleanup")
    sp.add_argument("--list", action="store_true", help="list snapshots and the nightly-copy status")
    sp.add_argument("--sync", action="store_true", help="copy the newest snapshot to [backup] sync_dir now")
    sp = add("restore", cmd_restore, "put a snapshot back as the board: a file, a name in .agentboard/backups, `latest`, or `previous` (the version before the last save)")
    sp.add_argument("which")
    sp.add_argument("--yes", action="store_true", help="do not ask (the board as it is now is kept first as a before-restore snapshot)")
    sp = add("verify", cmd_verify, "check the board file, its .bak and the newest snapshot (exit 1 if any is bad or the newest is over 2 hours old)")
    sp.add_argument("--all", action="store_true", help="check every snapshot")
    sp = add("dedupe", cmd_dedupe, "find accidental twin cards (`<id>-2` made by a second `start`) and, with --apply, merge them into the original")
    sp.add_argument("--apply", action="store_true", help="merge them (a snapshot is taken first); without it only lists them")
    sp = add("report", cmd_report, "markdown recap of what was completed today (or --date), by agent — for a standup or daily log")
    sp.add_argument("--date", help="YYYY-MM-DD (default: today)")
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
    sp.add_argument("--parent", metavar="ID", help="start it as a subtask of that task (one level deep)")
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
    sp.add_argument("progress", metavar="PCT", help="0-100; or, with no PCT, the status text alone")
    sp.add_argument("text", nargs="?")
    sp = add("ask", cmd_ask, "agent: flag that you are blocked on the user")
    sp.add_argument("id")
    sp.add_argument("question")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--body", help="markdown body (recap/diff/report) shown in the detail panel")
    g.add_argument("--body-file", help="read --body from a file instead (handles multi-line content)")
    sp = add("review", cmd_review, "agent: work complete — hand to the user for sign-off")
    sp.add_argument("id")
    sp.add_argument("text", help="one-line result")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--body", help="markdown body (recap/diff/report) shown in the detail panel")
    g.add_argument("--body-file", help="read --body from a file instead (handles multi-line content)")
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

    sp = add("run", cmd_run, "run a card with a one-shot, non-interactive `claude -p`, then move it to review (or ask)")
    sp.add_argument("id")
    sp.add_argument("--name", help="the agent name the card is claimed under (default $AGENTBOARD_NAME or 'oneshot')")
    sp.add_argument("--color")
    sp.add_argument("--cwd", help="work in this folder as it is (default: a fresh git worktree next to the current repo, removed afterwards if clean)")
    sp.add_argument("--budget", type=float, help="hard spend cap in USD passed to claude (default [run] budget_usd, else 5)")
    sp.add_argument("--max-minutes", type=float, help="hard wall-clock limit (default [run] max_minutes, else 45)")
    sp.add_argument("--force", action="store_true", help="take the card even if another agent holds it")
    sp.add_argument("--detach", action="store_true", help="return at once and supervise in the background (what ORCH uses)")
    sp = add("runs", cmd_runs, "list one-shot runs (live and finished); --kill CARD stops one")
    sp.add_argument("--kill", metavar="CARD", help="stop the live run on this card")

    sp = sub.add_parser("sms", help="text the board from your phone (Twilio webhook; off until you switch it on in config.toml)")
    ssub = sp.add_subparsers(dest="sms_cmd", required=True)
    sp2 = ssub.add_parser("serve", help="run the inbound-SMS endpoint on its own port (point the tunnel at it)")
    sp2.add_argument("--port", type=int, default=8766)
    sp2.set_defaults(fn=cmd_sms_serve)
    sp2 = ssub.add_parser("try", help="run a command text locally (no Twilio, no network): agentboard sms try add: buy milk")
    sp2.add_argument("text", nargs="+")
    sp2.set_defaults(fn=cmd_sms_try)

    sp = sub.add_parser("board", help="named boards: new, add, list, use, rm (registry in ~/.agentboard/boards.toml)")
    bsub = sp.add_subparsers(dest="board_cmd", required=True)
    bp = bsub.add_parser("new", help="create a board folder and register it")
    bp.add_argument("name")
    bp.add_argument("--path", help="the board folder (default ~/.agentboard/boards/<name>/.agentboard)")
    bp.add_argument("--color", help="tints the board's header")
    bp.set_defaults(fn=cmd_board_new)
    bp = bsub.add_parser("add", help="register an existing board folder under a name")
    bp.add_argument("name")
    bp.add_argument("path")
    bp.add_argument("--color")
    bp.set_defaults(fn=cmd_board_add)
    bsub.add_parser("list", help="registered boards").set_defaults(fn=cmd_board_list)
    bp = bsub.add_parser("use", help="the board used when the folder has none")
    bp.add_argument("name")
    bp.set_defaults(fn=cmd_board_use)
    bp = bsub.add_parser("rm", help="forget a board (never deletes its cards)")
    bp.add_argument("name")
    bp.set_defaults(fn=cmd_board_rm)

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

    sp = sub.add_parser("chat", help="shared channel for agents (and you) to self-organize, visible on the board")
    csub = sp.add_subparsers(dest="chat_cmd", required=True)

    def cadd(name, fn, help):
        csp = csub.add_parser(name, help=help)
        csp.set_defaults(fn=fn)
        return csp

    csp = cadd("send", cmd_chat_send, "post a message (who's on what, asking for a hand, handing off work)")
    csp.add_argument("text")
    csp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    csp.add_argument("--user", action="store_true", help="post as the human (Troy), not an agent")
    csp = cadd("tail", cmd_chat_tail, "read recent messages, optionally following live")
    csp.add_argument("--limit", type=int, default=30)
    csp.add_argument("--follow", action="store_true", help="keep polling and print new messages (Ctrl+C stops)")
    csp.add_argument("--interval", type=float, default=2.0, help="seconds between polls with --follow")

    a = p.parse_args(argv)
    if a.board:
        os.environ["AGENTBOARD_BOARD"] = a.board
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
