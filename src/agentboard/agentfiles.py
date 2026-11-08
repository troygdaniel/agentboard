"""The agent instruction files (CLAUDE.md, AGENTS.md): finding one, telling whether it already has agentboard's lines, and appending them.
Shared by `agentboard init` (which adds them) and `agentboard doctor` (which only looks). Only appends; never follows a link."""
import os
from pathlib import Path

INSTR_START = "<!-- agentboard:start -->"
INSTR_END = "<!-- agentboard:end -->"
AGENT_FILES = ("CLAUDE.md", "AGENTS.md")


def agent_file(here):
    """The CLAUDE.md or AGENTS.md already in this folder (a real file: a link could lead anywhere), else None."""
    for name in AGENT_FILES:
        p = Path(here) / name
        if p.is_file() and not p.is_symlink():
            return p
    return None


def has_instructions(path):
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return False
    return INSTR_START in text or "## Agent board" in text


def add_instructions(path, text):
    """Append `text` (the instruction lines) to `path` between two comment lines. Only appends: what is already in the file is never rewritten, and
    a file that already has them (our markers, or the heading `agentboard instructions` prints) is left alone. Returns "added" or "already"."""
    path = Path(path)
    if path.exists() and has_instructions(path):
        return "already"
    block = f"{INSTR_START}\n{text.rstrip()}\n{INSTR_END}\n"
    lead = ""
    if path.exists() and path.stat().st_size:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            lead = "\n" if f.read(1) == b"\n" else "\n\n"   # one blank line between what was there and our block
    with open(path, "a") as f:
        f.write(lead + block)
    return "added"
