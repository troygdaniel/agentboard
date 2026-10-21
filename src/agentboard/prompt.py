"""Assemble a task prompt from a template plus context providers."""
import shlex
import shutil
import sys
import tomllib
from pathlib import Path

from . import providers

DEFAULT_TEMPLATE = """\
# Task: {title}

Task ID: {task_id}

## Step 0: claim this task (do this first)

Run this so the board knows you have it. Use your own session name{color_hint}:

    {ab} claim {task_id} --name "<your session name>"

## Progress reporting

Report progress as you work (the board shows a live progress bar):

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


def load_config(board_dir):
    path = Path(board_dir) / "config.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def agentboard_cmd(board_dir):
    """Absolute command agents can run from any directory."""
    exe = Path(sys.executable).parent / "agentboard"
    if not exe.exists():
        exe = shutil.which("agentboard")
    runner = shlex.quote(str(exe)) if exe else f"{shlex.quote(sys.executable)} -m agentboard"
    return f"AGENTBOARD_DIR={shlex.quote(str(board_dir))} {runner}"


def build_prompt(task, board_dir, public=False):
    """Return (prompt, warnings). public=True skips providers marked private."""
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
    if ptconf.get("template_file"):
        template = (Path(board_dir) / ptconf["template_file"]).expanduser().read_text()
    elif ptconf.get("template"):
        template = ptconf["template"]

    values = {
        "title": task["title"],
        "task_id": task["id"],
        "description": task.get("description") or task["title"],
        "ab": agentboard_cmd(board_dir),
        "context": context,
        "color_hint": ptconf.get("color_hint", " and color if you know it (add --color <color>)"),
    }
    out = template
    for k, v in values.items():  # str.replace so braces in context text are safe
        out = out.replace("{" + k + "}", v)
    return out, warnings
