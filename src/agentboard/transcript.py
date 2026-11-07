"""The session's transcript, read only (Nov 6). Claude Code writes every session's conversation to
~/.claude/projects/<folder>/<session id>.jsonl as it goes. An agent's session registers that path when it claims or starts a
card (found from $CLAUDE_CODE_SESSION_ID, or given with --transcript / $AGENTBOARD_TRANSCRIPT), and the board's server tails
it for the Terminal tab: tool calls as muted one-liners, text as text, newest last. Nothing is written, nothing leaves the
machine, and a transcript that is not there, not readable or outside ~/.claude/projects reads as "no transcript"."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import redact

ENV = "AGENTBOARD_TRANSCRIPT"
TAIL_BYTES = 1536 * 1024    # the end of the file is what the tab shows; a long session's start is not read (tool output lines are big: 256 KB held nine turns)
MAX_LINES = 300
TEXT_MAX = 2000
LINE_MAX = 160

# the one argument that says what a tool call was about, per tool; anything else shows its name alone
TOOL_ARG = {"Read": "file_path", "Edit": "file_path", "Write": "file_path", "NotebookEdit": "notebook_path", "Bash": "description",
            "Grep": "pattern", "Glob": "pattern", "Agent": "description", "WebFetch": "url", "WebSearch": "query",
            "SendMessage": "summary", "Skill": "skill", "Artifact": "action", "TaskStop": "task_id"}


def projects_dir():
    """Where Claude Code keeps transcripts. Read at call time, so a test's HOME counts."""
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def find_transcript(session_id=None, explicit=None):
    """The path of a session's transcript: the one given (--transcript or $AGENTBOARD_TRANSCRIPT) wins; else the file named
    after the session id under any project folder; else None."""
    given = explicit or os.environ.get(ENV)
    if given:
        return str(Path(given).expanduser())
    sid = session_id or ""
    if not re.fullmatch(r"[\w-]{8,}", sid):
        return None
    for f in sorted(projects_dir().glob(f"*/{sid}.jsonl")):
        return str(f)
    return None


def resolved(path):
    """The one real file a registered path points at, as an absolute resolved Path, or None unless it is a .jsonl under ~/.claude/projects
    (symlinks followed first, so a link that leaves the folder is refused). The path comes from a file on disk, not from the request, but
    the rule holds anyway. read() opens exactly this Path: the check and the open see the same file."""
    try:
        p = Path(path).expanduser().resolve()
        root = projects_dir().resolve()
    except (OSError, RuntimeError, ValueError):   # ValueError: a NUL byte in a path from a hand-edited sessions.json
        return None
    return p if p.suffix == ".jsonl" and root in p.parents else None


def allowed(path):
    """Only a file under ~/.claude/projects is served."""
    return resolved(path) is not None


def tool_line(name, inp, board_dir=None):
    """'Read src/agentboard/cli.py', 'Bash Run the tests': the tool and the one argument that says what it was about."""
    inp = inp if isinstance(inp, dict) else {}
    key = TOOL_ARG.get(name)
    arg = inp.get(key) if key else None
    if name == "Bash" and not arg:
        arg = inp.get("command")
    if name == "SendMessage" and not arg:
        arg = f"to {inp.get('to', '')}".strip()
    arg = redact.scrub(" ".join(str(arg or "")[:4 * LINE_MAX].split()), board_dir, bound=2 * LINE_MAX)   # a key in a command or a URL is masked before the line is cut to length
    line = f"{name} {arg}".strip()
    return line if len(line) <= LINE_MAX else line[: LINE_MAX - 1] + "…"


def _at(obj):
    return str(obj.get("timestamp") or "")[:19].replace("T", " ")


def parse_line(line, board_dir=None):
    """One transcript line to the entries the tab shows: [] for the lines that are not part of the conversation."""
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return []
    if not isinstance(obj, dict) or obj.get("isSidechain") or obj.get("isMeta"):
        return []
    kind = obj.get("type")
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    content = msg.get("content")
    at = _at(obj)
    out = []
    if kind == "assistant" and isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and str(b.get("text") or "").strip():
                out.append({"kind": "text", "text": redact.scrub(str(b["text"]).strip(), board_dir, bound=2 * TEXT_MAX)[:TEXT_MAX], "at": at})
            elif b.get("type") == "tool_use":
                name = str(b.get("name") or "tool")
                if name == "AskUserQuestion" and isinstance(b.get("input"), dict):   # a question put to the person in the terminal: the panel shows it
                    for q in b["input"].get("questions") or []:
                        if isinstance(q, dict) and str(q.get("question") or "").strip():
                            opts = [redact.scrub(str(o.get("label") if isinstance(o, dict) else o), board_dir, bound=2 * LINE_MAX)[:LINE_MAX] for o in (q.get("options") or []) if o][:6]
                            out.append({"kind": "ask", "text": redact.scrub(str(q["question"]).strip(), board_dir, bound=2 * TEXT_MAX)[:TEXT_MAX], "options": opts, "at": at})
                    continue
                out.append({"kind": "tool", "text": tool_line(name, b.get("input"), board_dir), "at": at})
    elif kind == "user":
        if isinstance(content, str):
            text = content.strip()
            if text and not text.startswith("<"):   # a line the person typed; the harness's own notes start with a tag
                out.append({"kind": "user", "text": redact.scrub(text, board_dir, bound=2 * TEXT_MAX)[:TEXT_MAX], "at": at})
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    c = b.get("content")
                    text = c if isinstance(c, str) else " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
                    first = redact.scrub(" ".join(text.strip().splitlines()[:1]).strip(), board_dir, bound=2 * LINE_MAX)
                    out.append({"kind": "error", "text": first[:LINE_MAX] or "error", "at": at})
    return out


def tail_text(path, max_bytes=TAIL_BYTES):
    """The last `max_bytes` of the file as whole lines (a cut first line is dropped), and the file's size."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - max_bytes)
        f.seek(start)
        data = f.read()
    text = data.decode("utf-8", "replace")
    if start > 0:
        text = text.partition("\n")[2]   # the first line is cut somewhere: drop it
    return text, size


def read(path, max_lines=MAX_LINES, board_dir=None):
    """What the tab shows for one transcript: the last entries, newest last, with the file's size and last change. A path that
    is missing, unreadable or outside ~/.claude/projects gives no lines and says why, never an error."""
    if not path:
        return {"lines": [], "missing": True, "why": "no transcript registered"}
    real = resolved(path)   # checked and opened as one and the same Path: a "~" or a relative piece can never make open() look elsewhere
    if real is None:
        return {"lines": [], "missing": True, "why": "outside ~/.claude/projects"}
    if real.exists() and not real.is_file():   # a FIFO (open() would block the handler thread for good), a directory, a device: not a transcript
        return {"lines": [], "missing": True, "why": "not a regular file"}
    try:
        text, size = tail_text(real)
        mtime = datetime.fromtimestamp(os.path.getmtime(real)).strftime("%Y-%m-%dT%H:%M:%S")
    except OSError:
        return {"lines": [], "missing": True, "why": "no such file"}
    lines = []
    for raw in text.splitlines():
        lines.extend(parse_line(raw, board_dir))
    return {"lines": lines[-max_lines:], "size": size, "mtime": mtime, "file": real.name}
