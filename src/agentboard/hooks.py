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
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .store import BoardError, owner_name

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


def remember_session(board_dir, name, session_id=None, transcript=None):
    """Keep this session's name against its id, so the hook can post as it, and the path of its transcript (given, or found
    from the id) so the board can show the session. Silent when there is no id or the dir is missing."""
    from . import transcript as transcriptlib
    sid = session_id or os.environ.get(SESSION_ENV)
    if not sid or not name or name == owner_name(board_dir):
        return None
    d = read_sessions(board_dir)
    rec = {"name": name, "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    path = transcriptlib.find_transcript(sid, transcript)
    old = d.get(sid) if isinstance(d.get(sid), dict) else {}
    if path or old.get("transcript"):
        rec["transcript"] = path or old["transcript"]   # a path once found is kept until a better one comes
    d[sid] = rec
    if len(d) > MAX_SESSIONS:   # oldest out
        for k in sorted(d, key=lambda k: d[k].get("at", ""))[: len(d) - MAX_SESSIONS]:
            d.pop(k, None)
    try:
        sessions_path(board_dir).write_text(json.dumps(d, indent=2))
    except OSError:
        return None
    return sid


def transcript_for(board_dir, name):
    """The transcript path of the newest session that gave itself `name` (case does not matter), or None."""
    recs = [r for r in read_sessions(board_dir).values() if isinstance(r, dict) and str(r.get("name", "")).lower() == str(name or "").lower() and r.get("transcript")]
    recs.sort(key=lambda r: str(r.get("at", "")))
    return recs[-1]["transcript"] if recs else None


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


def hook_command():
    """What the hook runs, with this agentboard's full path (found now). A bare name would be looked up on PATH every time a session
    sends a message, from a settings file that is usually committed with the project: whichever agentboard came first would run."""
    exe = shutil.which("agentboard")
    if exe:
        return f"{shlex.quote(os.path.abspath(exe))} hook send-message"
    return f"{shlex.quote(sys.executable)} -m agentboard hook send-message"   # run as a module: still a full path


def hook_entry(command=None):
    return {"matcher": "SendMessage", "hooks": [{"type": "command", "command": command or hook_command()}]}


def _load(project_dir):
    p = settings_path(project_dir)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except ValueError as e:
        raise BoardError(f"{p} is not valid JSON ({e}); fix it first") from e
    if not isinstance(data, dict):
        raise BoardError(f"{p} is not a JSON object")
    return p, data


def _ours(h):
    """Is this hook entry the one this module writes: <agentboard> hook send-message, bare, with a full path (quoted or not), or
    <python> -m agentboard hook send-message. Read as a shell would, so a path with a space still matches."""
    if not isinstance(h, dict):
        return False
    try:
        argv = shlex.split(str(h.get("command", "")))
    except ValueError:
        return False
    if argv[-2:] != ["hook", "send-message"] or len(argv) < 3:
        return False
    return os.path.basename(argv[0]) == "agentboard" or argv[-3] == "agentboard"


def install(project_dir):
    """Add the SendMessage hook to the project's settings (creating the file), keeping everything else. Idempotent. An older entry that
    names agentboard without a path is rewritten with the full path. Returns (path, changed)."""
    p, data = _load(project_dir)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BoardError(f"{p}: 'hooks' is not an object")
    post = hooks.setdefault("PostToolUse", [])
    if not isinstance(post, list):
        raise BoardError(f"{p}: hooks.PostToolUse is not a list")
    if installed(project_dir):
        changed = False
        for entry in post:
            for h in (entry.get("hooks") or []) if isinstance(entry, dict) and entry.get("matcher") == "SendMessage" else []:
                if _ours(h) and str(h.get("command", "")).strip() == HOOK_COMMAND:   # the old bare form
                    h["command"] = hook_command()
                    changed = True
        if changed:
            p.write_text(json.dumps(data, indent=2) + "\n")
        return p, changed
    post.append(hook_entry())
    from . import private
    with private.as_user():   # the project's .claude/settings.json is shared with Claude Code and your team, not board data
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n")
    return p, True


def uninstall(project_dir):
    """Remove only the hook this module installed (and what it emptied); every other setting and hook stays. Returns (path, changed)."""
    p, data = _load(project_dir)
    hooks = data.get("hooks")
    post = hooks.get("PostToolUse") if isinstance(hooks, dict) else None
    if not isinstance(post, list):
        return p, False
    changed = False
    for entry in list(post):
        if isinstance(entry, dict) and entry.get("matcher") == "SendMessage" and isinstance(entry.get("hooks"), list):
            kept = [h for h in entry["hooks"] if not _ours(h)]
            if len(kept) != len(entry["hooks"]):
                changed = True
                entry["hooks"] = kept
                if not kept:
                    post.remove(entry)
    if not changed:
        return p, False
    if not post:
        del hooks["PostToolUse"]
    if not hooks:
        del data["hooks"]
    if data:
        p.write_text(json.dumps(data, indent=2) + "\n")
    else:
        p.unlink()   # the file held nothing but our hook: leave no empty settings.json behind
    return p, True


def installed_command(project_dir):
    """The command the installed hook runs, or None."""
    try:
        data = json.loads(settings_path(project_dir).read_text())
    except (OSError, ValueError):
        return None
    for entry in (data.get("hooks") or {}).get("PostToolUse") or []:
        if isinstance(entry, dict) and entry.get("matcher") == "SendMessage":
            for h in entry.get("hooks") or []:
                if _ours(h):
                    return str(h.get("command"))
    return None


def installed(project_dir):
    return installed_command(project_dir) is not None
