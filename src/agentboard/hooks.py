"""Mirror the real conversation. ORCH and the agents already talk to each other through their sessions' SendMessage tool; none
of that reaches the board. A Claude Code hook (PostToolUse on SendMessage) runs `agentboard hook send-message` with the tool
call on stdin, and this module posts its first line to the shared chat as the session that sent it, to whom it went, the rest
behind the detail, marked as mirrored. `agentboard hooks install` writes that one hook into the project's .claude/settings.json.

The sender is resolved from the session: a session says who it is the first time it runs claim, start, chat or me with
--name, and that name is kept against its CLAUDE_CODE_SESSION_ID in .agentboard/sessions.json; the hook payload carries the
same id. A hook must never get in an agent's way, so every path here swallows its errors and exits 0."""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .store import BoardError

HOOK_COMMAND = "agentboard hook send-message"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
MAX_SESSIONS = 200


def sessions_path(board_dir):
    return Path(board_dir) / "sessions.json"


def read_sessions(board_dir):
    try:
        d = json.loads(sessions_path(board_dir).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_session(board_dir, name, session_id=None):
    """Keep this session's name against its id, so the hook can post as it. Silent when there is no id or the dir is missing."""
    sid = session_id or os.environ.get(SESSION_ENV)
    if not sid or not name or name == "Troy":
        return None
    d = read_sessions(board_dir)
    d[sid] = {"name": name, "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    if len(d) > MAX_SESSIONS:   # oldest out
        for k in sorted(d, key=lambda k: d[k].get("at", ""))[: len(d) - MAX_SESSIONS]:
            d.pop(k, None)
    try:
        sessions_path(board_dir).write_text(json.dumps(d, indent=2))
    except OSError:
        return None
    return sid


def session_name(board_dir, session_id):
    rec = read_sessions(board_dir).get(session_id or "")
    return rec.get("name") if isinstance(rec, dict) else None


def resolve_sender(board_dir, payload):
    """$AGENTBOARD_NAME, else the name this session gave itself, else a short handle from the session id."""
    name = os.environ.get("AGENTBOARD_NAME") or session_name(board_dir, payload.get("session_id"))
    if name:
        return name
    sid = str(payload.get("session_id") or "")
    return f"session-{sid[:6]}" if sid else "a session"


def clean_to(to):
    """'worker [3fa9c1]' -> 'worker'; 'main' is a subagent's own conversation, not a peer."""
    t = re.sub(r"\s*\[[^\]]*\]\s*$", "", str(to or "")).strip()
    return None if not t or t.lower() == "main" else t


def mirror_send_message(store, payload):
    """Post a SendMessage call to the chat. Returns the message, or None when there is nothing to mirror (not a SendMessage,
    no text, sent to 'main', or agent chat off for this board)."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "SendMessage":
        return None
    inp = payload.get("tool_input") or {}
    text = str(inp.get("message") or "").strip()
    to = clean_to(inp.get("to"))
    if not text or not to:
        return None
    if not store.chat_agents():
        return None
    sender = resolve_sender(store.dir, payload)
    first, _, rest = text.partition("\n")
    return store.chat_send(sender, first.strip()[:300], to=to, detail=rest.strip() or None, via="mirror")


def run_hook(store, stdin=None):
    """`agentboard hook send-message`: read the payload, mirror it, say nothing, exit 0 whatever happens."""
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        mirror_send_message(store, payload)
    except (ValueError, BoardError, OSError, AttributeError, TypeError):
        pass
    return 0


# ---- installing the hook into a project's .claude/settings.json ------------------------------------------------------------
def settings_path(project_dir):
    return Path(project_dir) / ".claude" / "settings.json"


def hook_entry():
    return {"matcher": "SendMessage", "hooks": [{"type": "command", "command": HOOK_COMMAND}]}


def install(project_dir):
    """Add the SendMessage hook to the project's settings (creating the file), keeping everything else. Idempotent.
    Returns (path, changed)."""
    p = settings_path(project_dir)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except ValueError as e:
        raise BoardError(f"{p} is not valid JSON ({e}); fix it first") from e
    if not isinstance(data, dict):
        raise BoardError(f"{p} is not a JSON object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BoardError(f"{p}: 'hooks' is not an object")
    post = hooks.setdefault("PostToolUse", [])
    if not isinstance(post, list):
        raise BoardError(f"{p}: hooks.PostToolUse is not a list")
    if installed(project_dir):
        return p, False
    post.append(hook_entry())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")
    return p, True


def installed(project_dir):
    try:
        data = json.loads(settings_path(project_dir).read_text())
    except (OSError, ValueError):
        return False
    for entry in (data.get("hooks") or {}).get("PostToolUse") or []:
        if isinstance(entry, dict) and entry.get("matcher") == "SendMessage":
            for h in entry.get("hooks") or []:
                if isinstance(h, dict) and HOOK_COMMAND in str(h.get("command", "")):
                    return True
    return False
