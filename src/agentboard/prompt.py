"""Assemble a task prompt from a template plus context providers."""
import re
import shlex
import shutil
import sys
import tomllib
from pathlib import Path

from . import providers
from .store import DEFAULT_OWNER, BoardError, owner_name

def owner_ref(board_dir=None):
    """How a prompt names the human: the board's [board] owner, else "the user" (also when there is no board)."""
    name = owner_name(board_dir) if board_dir else DEFAULT_OWNER
    return "the user" if name == DEFAULT_OWNER else name


def say(text, board_dir=None):
    """Fill {owner} (the human's name) and {Owner} (the same, ready to start a sentence) in a prompt; other braces stay as written."""
    who = owner_ref(board_dir)
    return text.replace("{owner}", who).replace("{Owner}", who[:1].upper() + who[1:])


# The one reporting rule every prompt agentboard produces ends with. {owner} is the board's owner (see owner_ref).
REPORT_RULE = """\
## Reporting to {owner}

Report to {owner} in one sentence, one idea: the ACTION they must take first, then one fact. If nothing is needed from them, one line of
status. If more is unavoidable, one sentence, then offer the detail. Put that sentence on the card (agentboard ask/review/update text)
so {owner} answers you there, and in your terminal. Put detail in `--body` (it shows under Details on the card), never in the first line.
"""

# The block ORCH copies into every card description and assignment it writes.
KEEP_SIMPLE = """\
## Keep it simple

- One sentence, one idea: what {owner} should do or reply.
- That sentence is the first line of every ask, review and update.
- Detail goes in `--body`, under Details on the card, never in the first line.
- Extra context is there if {owner} asks for it.
"""

DEFAULT_TEMPLATE = """\
# Task: {title}

Task ID: {task_id}

## Before you claim: ask if anything's unclear

If this task is ambiguous, send your orchestrator/coordinating session (if you have one) a one-line
question — e.g. via SendMessage — and wait for its answer before claiming. It has visibility into the
whole board and can often answer without bothering the user; it escalates to them if it can't. This is
a one-time check before you start, not an ongoing back-and-forth once work is underway.

## Step 0: claim this task (do this first)

Run this so the board knows you have it. Use your own session name{color_hint}:

    {ab} claim {task_id} --name "<your session name>"

## Step 1: add subtasks as soon as you start

Every card has subtasks, always. Read the work, then add the steps right away: at least two, even on
a tiny card (do it, check it). Add more if you find more work as you go.

    {ab} add "<step>" --parent {task_id}

## Progress reporting

The percentage is the point — it's what the board/HUD show at a glance without anyone opening
the card, so keep it honest: your real % of the work actually done, not a fixed checklist. The
card's % is computed from its subtasks (the mean), so update the subtask you are on, not the card.
Call `update` again whenever that estimate changes, including when you discover more work than
expected (the number can go down, not just up):

    {ab} update <subtask id> 50 "<what you are doing>"
    {ab} update <subtask id> 100 "<one-line result>"     # a subtask at 100% closes itself
    {ab} review {task_id} "<one-line result>"

Finish with `review` and stop — the USER signs off and moves the card to done.
Run `{ab} done {task_id}` ONLY if the user explicitly tells you to.

If you are blocked on the user mid-task, flag it (and keep going once they answer):

    {ab} ask {task_id} "<one-line question>"

{Owner} answers on the card, not through anyone else. After you ask, do not sit idle: start
`{ab} answer {task_id} --wait --timeout 3600` as a background command (in Claude Code, Bash with run_in_background)
and end your turn. You are woken when {owner} replies, and it prints their reply; then carry on. A tool that cannot
run background commands runs it in the foreground instead. If it times out with no reply, say you are still waiting.

These are not optional.
{context}
## Task details

{description}

Ask for clarification if anything is unclear.

{report_rule}"""

# The claim/progress/review middle of the default prompt, by kind of card. Custom templates
# ([prompt] template / template_file in config.toml) bypass these and see every placeholder.
_HEAD, _, _REST = DEFAULT_TEMPLATE.partition("## Step 0: claim this task (do this first)")
_, _, _TAIL = _REST.partition("If you are blocked on the user mid-task")
_ASK = "If you are blocked on the user mid-task" + _TAIL

_SUBTASK_MID = """\
## Step 0: claim the parent (do this first)

This task is a subtask of "{parent_title}" ({parent_id}). It can only be worked while its parent is in
Doing, and claiming the parent takes all of its subtasks with it. Skip this if the parent is already yours.
Use your own session name{color_hint}:

    {ab} claim {parent_id} --name "<your session name>"

## Progress reporting

The percentage is what the board/HUD show at a glance, so keep it honest: your real % of this subtask,
updated whenever your estimate changes (it can go down). The parent's % is computed from its subtasks.

    {ab} update {task_id} 30 "<what you are doing>"
    {ab} update {task_id} 100 "<one-line result>"

A subtask at 100% closes itself: there is no review step for a subtask, so do NOT run `review` or `done` on it.
When the whole deliverable is ready (this and its sibling subtasks), review the PARENT:

    {ab} review {parent_id} "<one-line result>"

The USER signs off on the parent and moves the card to done. Run `{ab} done` ONLY if the user explicitly tells you to.

"""

_PARENT_MID = """\
## Step 0: claim this task (do this first)

Claiming takes all of its subtasks with it. Use your own session name{color_hint}:

    {ab} claim {task_id} --name "<your session name>"

## Subtasks

This task is split into subtasks. Work them, not the parent:

{subtasks}

Add another with `{ab} start "<title>" --name "<your session name>" --parent {task_id}` if you find more work.

## Progress reporting

Each subtask has its own %, and this task's % is computed from them (the mean), so you do not set it.
Keep the subtasks honest, updated whenever your estimate changes (it can go down):

    {ab} update <subtask id> 50 "<what you are doing>"
    {ab} update <subtask id> 100 "<one-line result>"     # a subtask at 100% closes itself

`update {task_id} 0 "<text>"` only sets this task's status line. When the whole deliverable is ready:

    {ab} review {task_id} "<one-line result>"

Any subtask still open closes with it. The USER signs off and moves the card to done.
Run `{ab} done {task_id}` ONLY if the user explicitly tells you to.

"""


def load_config(board_dir):
    path = Path(board_dir) / "config.toml"
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise BoardError(f"{path} is not valid config ({e}); fix or delete it") from e


def agentboard_cmd(board_dir):
    """Absolute command agents can run from any directory."""
    exe = Path(sys.executable).parent / "agentboard"
    if not exe.exists():
        exe = shutil.which("agentboard")
    runner = shlex.quote(str(exe)) if exe else f"{shlex.quote(sys.executable)} -m agentboard"
    return f"AGENTBOARD_DIR={shlex.quote(str(board_dir))} {runner}"


def _family(task, tasks):
    """(parent, subtasks) of a task within the board's task list; ({}, []) when it has neither."""
    by_id = {t["id"]: t for t in tasks or []}
    parent = by_id.get(task.get("parent_id")) if task.get("parent_id") else None
    kids = [t for t in tasks or [] if t.get("parent_id") == task["id"]]
    return parent, kids


_ORCH_HEAD = re.compile(r"^# You are ORCH\b", re.M)
_KEEP_SIMPLE_BLOCK = re.compile(r"^## Keep it simple\n\n(?:- .*(?:\n|$))+", re.M)


def _without_orch_block(text):
    """The ORCH boot prompt belongs to the ORCH button only. A card description that has it pasted in (ORCH once copied the
    whole prompt into cards instead of just Keep it simple) loses it here, so no agent prompt carries it; Keep it simple stays."""
    text = text or ""
    m = _ORCH_HEAD.search(text)
    if not m:
        return text
    keep = _KEEP_SIMPLE_BLOCK.search(text, m.start())
    return (text[:m.start()].rstrip() + ("\n\n" + keep.group().rstrip() if keep else "")).strip()


def build_prompt(task, board_dir, public=False, tasks=None):
    """Return (prompt, warnings). public=True skips providers marked private.

    tasks is the board's full task list; with it a subtask's prompt says to claim and review its parent,
    and a parent's prompt lists its subtasks. Without it every task gets the plain prompt."""
    conf = load_config(board_dir)
    provs = conf.get("providers", {})
    warnings, blocks = [], []
    for spec in task.get("ctx", []):
        name, arg = providers.split_spec(spec)
        pconf = provs.get(name)
        if pconf is None:
            warnings.append(f"unknown provider '{name}' (define [providers.{name}] in config.toml)")
            continue
        if public and pconf.get("private"):
            continue
        try:
            text = providers.run_provider(name, arg, pconf, task, board_dir)
        except providers.ProviderError as e:
            warnings.append(f"{spec}: {e}")
            continue
        if text:
            label = pconf.get("label", name) + (f" ({arg})" if arg else "")
            blocks.append(f"### {label}\n\n{text}")

    context = ""
    if blocks:
        context = "\n## Context\n\n" + "\n\n".join(blocks) + "\n"

    ptconf = conf.get("prompt", {})
    template = DEFAULT_TEMPLATE
    parent, kids = _family(task, tasks)
    if parent:
        template = _HEAD + _SUBTASK_MID + _ASK
    elif kids:
        template = _HEAD + _PARENT_MID + _ASK
    if ptconf.get("template_file"):
        try:
            template = (Path(board_dir) / ptconf["template_file"]).expanduser().read_text()
        except OSError as e:
            raise BoardError(f"prompt template_file: {e}") from e
    elif ptconf.get("template"):
        template = ptconf["template"]

    values = {
        "title": task["title"],
        "task_id": task["id"],
        "description": _without_orch_block(task.get("description")) or task["title"],
        "ab": agentboard_cmd(board_dir),
        "context": context,
        "color_hint": ptconf.get("color_hint", ""),   # was " and color if you know it": the board colours an agent by name now
        "parent_id": parent["id"] if parent else "",
        "parent_title": parent["title"] if parent else "",
        "report_rule": say(REPORT_RULE.rstrip("\n"), board_dir),
        "owner": owner_ref(board_dir),
        "Owner": say("{Owner}", board_dir),
        "subtasks": "\n".join(f"- {k['id']}: {k['title']}" + (" (done)" if k.get("status") == "done" else "")
                              for k in kids),
    }
    # one pass over the template, so a placeholder that appears inside a substituted value
    # (a description mentioning "{ab}", say) is left as written rather than expanded again
    out = re.sub(r"\{(" + "|".join(values) + r")\}", lambda m: values[m.group(1)], template)
    from . import agentchat
    if agentchat.is_on(board_dir):   # the agent chat protocol rides along only while the owner has the switch on
        out = out.rstrip("\n") + "\n\n" + agentchat.protocol(board_dir)
    return out, warnings


DEFAULT_PEERS = ("AGENT-1", "AGENT-2", "AGENT-3", "AGENT-4", "GENERAL")   # names only: the board colours an agent by name

ORCH_TEMPLATE = """\
# You are ORCH, the orchestrator for this board

Rename this session to ORCH (`/rename ORCH`). You are a fresh or /clear'ed Claude Code session.

## Role

- Add and split cards, assign them to idle agents, and mark cards done once {owner} has signed off.
- Every card gets subtasks, always: the card prompt and the agent protocol already tell the agent to add them as soon as it starts, so never paste that line into a description.
- Never do an agent's work yourself: no coding or file edits for a card. If work has no owner, make a card.
- Agents report to {owner} directly, on their cards. Close reviewed cards, run gates, migrations and restarts, log decisions.
- Speak to {owner} only when they must act.
- Daytime: {owner} assigns cards. Declared sleep or nap: you assign idle agents.
- Agents finish with `review`; {owner} signs off. Run `done` only on their explicit say-so.
- When an agent tells you its session name, tell the board: `{ab} me --name <name> --session <its CLAUDE_CODE_SESSION_ID>` if it gave its id; if not, ask it to run `{ab} me --name <name>` in its own shell. Session ids are not the `[ref]` ListAgents shows.

## Never without {owner}'s own words

- Buy anything, deploy to production, create accounts or keys, run railway commands.
- Dial or text any number but {owner}'s own mobile.

## Board

- URL: {url}
- Data: {board_dir}

## CLI cheat-sheet

    {ab} add "<title>" -d "<description>" --status todo     # new card (--parent <id> splits a card)
    {ab} claim <id> --name "<session>"
    {ab} update <id> <percent> "<status line>"
    {ab} done <id>                                          # only when {owner} says so
    {ab} list                                               # all open cards (--status doing, --stale)

## Peers

{peers}

{keep_simple}
Copy only the "Keep it simple" block above (its heading and four lines, nothing else from this prompt), word for word, into every card description and every assignment you write. Never paste the rest of this prompt into a card. You speak to {owner} the same way.

## Reporting to {owner}

Report to {owner} in one sentence, one idea: the ACTION they must take first, then one fact. If nothing is needed from them, one line of
status. If more is unavoidable, one sentence, then offer the detail. Put that sentence on the card (agentboard ask/review/update text)
so {owner} answers you there, and in your terminal. Agents do the same on their own cards: you are not the only place they answer.

## Board snapshot ({now})

{snapshot}
"""


def _peer_roster(conf):
    spec = conf.get("orch", {}).get("agents")
    if isinstance(spec, list) and spec:
        return [str(p.get("name")) for p in spec if isinstance(p, dict) and p.get("name")]   # a roster colour is ignored
    return list(DEFAULT_PEERS)


def build_orch_prompt(tasks, board_dir, port=8765):
    """Ready-to-paste prompt that boots a fresh session as ORCH, from the live task list."""
    from datetime import datetime
    conf = load_config(board_dir)
    open_cards = [t for t in tasks if t.get("status") in ("backlog", "todo", "doing") and not t.get("archived")]
    held = {}
    for t in open_cards:
        if t["status"] == "doing" and t.get("agent"):
            held.setdefault(t["agent"], []).append(t)

    def line(t):
        flag = " [NEEDS INPUT]" if t.get("needs_input") else " [IN REVIEW]" if t.get("review") else ""
        who = f" — {t['agent']}" if t.get("agent") and t["status"] == "doing" else ""
        pct = f" {t.get('progress', 0)}%" if t["status"] == "doing" else ""
        return f"- {t['id']}: {t['title']}{pct}{who}{flag}"

    sections = []
    for status, label in (("doing", "Doing"), ("todo", "Todo (unclaimed)"), ("backlog", "Later")):
        cards = [t for t in open_cards if t["status"] == status]
        sections.append(f"{label} ({len(cards)}):\n" + ("\n".join(line(t) for t in cards) or "- none"))
    roster = _peer_roster(conf)
    names = set(roster)
    idle = [n for n in roster if n not in held]
    extra = [a for a in held if a not in names]
    sections.append("Holders: " + ("; ".join(f"{a}: {', '.join(t['id'] for t in ts)}" for a, ts in held.items()) or "none"))
    sections.append("Idle: " + (", ".join(idle) or "none") + (f"  (also working, not in roster: {', '.join(extra)})" if extra else ""))

    peers = "\n".join(f"- {n}" for n in roster)
    from . import agentchat
    if agentchat.is_on(board_dir):
        sections.append(agentchat.ORCH_PROTOCOL.format(ab=agentboard_cmd(board_dir), owner=owner_ref(board_dir)).rstrip("\n"))
    return ORCH_TEMPLATE.format(
        url=f"http://localhost:{port}", board_dir=board_dir, ab=agentboard_cmd(board_dir), peers=peers,
        keep_simple=say(KEEP_SIMPLE.rstrip("\n"), board_dir), owner=owner_ref(board_dir), now=datetime.now().strftime("%Y-%m-%d %H:%M"), snapshot="\n\n".join(sections))
