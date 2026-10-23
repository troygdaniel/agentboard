"""Assemble a task prompt from a template plus context providers."""
import re
import shlex
import shutil
import sys
import tomllib
from pathlib import Path

from . import providers
from .store import BoardError

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

## Progress reporting

The percentage is the point — it's what the board/HUD show at a glance without anyone opening
the card, so keep it honest: your real % of the work actually done, not a fixed checklist. Call
`update` again whenever that estimate changes, including when you discover more work than
expected (the number can go down, not just up):

    {ab} update {task_id} 10 "Starting - reading context"
    {ab} update {task_id} 30 "Planning approach"
    {ab} update {task_id} 50 "<what you are doing>"
    {ab} update {task_id} 70 "<next step>"
    {ab} review {task_id} "<one-line result>"

Finish with `review` and stop — the USER signs off and moves the card to done.
Run `{ab} done {task_id}` ONLY if the user explicitly tells you to.

If you are blocked on the user mid-task, flag it (and keep going once they answer):

    {ab} ask {task_id} "<one-line question>"

These are not optional.
{context}
## Task details

{description}

Ask for clarification if anything is unclear.
"""

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
        "description": task.get("description") or task["title"],
        "ab": agentboard_cmd(board_dir),
        "context": context,
        "color_hint": ptconf.get("color_hint", " and color if you know it (add --color <color>)"),
        "parent_id": parent["id"] if parent else "",
        "parent_title": parent["title"] if parent else "",
        "subtasks": "\n".join(f"- {k['id']}: {k['title']}" + (" (done)" if k.get("status") == "done" else "")
                              for k in kids),
    }
    # one pass over the template, so a placeholder that appears inside a substituted value
    # (a description mentioning "{ab}", say) is left as written rather than expanded again
    out = re.sub(r"\{(" + "|".join(values) + r")\}", lambda m: values[m.group(1)], template)
    return out, warnings
