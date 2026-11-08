"""Two Claude Code hooks, installed together by `agentboard hooks install` into the project's .claude/settings.json.

Mirror the real conversation. ORCH and the agents already talk to each other through their sessions' SendMessage tool; none
of that reaches the board. A PostToolUse hook on SendMessage runs `agentboard hook send-message` with the tool call on stdin,
and this module posts its first line to the shared chat as the session that sent it, to whom it went, the rest behind the
detail, marked as mirrored.

Do not go quiet on an unread line. A session that has finished its turn reads nothing until something wakes it; a line the owner
typed on the board would sit in its inbox. A Stop hook runs `agentboard hook stop` as the session is about to go quiet: with an
unread line from the owner for this session it answers "block" with the line as the reason, so the session answers first; with
nothing unread but no wait running (listeners.py) it answers "block" once with the command that keeps the session reachable.
It never blocks twice in a row (stop_hook_active), so a session that ignores it still stops.

The sender is resolved from the session: a session says who it is the first time it runs claim, start, chat or me with
--name, and that name is kept against its CLAUDE_CODE_SESSION_ID in .agentboard/sessions.json; the hook payloads carry the
same id. A hook must never get in an agent's way, so every path here swallows its errors and exits 0."""
import json
import os
import re
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import cursors, listeners, untrusted
from .store import BoardError, owner_name

HOOK_COMMAND = "agentboard hook send-message"
EVENTS = {"send-message": ("PostToolUse", "SendMessage"), "stop": ("Stop", None)}   # hook event -> (settings list, matcher)
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
MAX_SESSIONS = 200
REASON_MAX = 400


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
    text = store._scrub(text, 4300)   # masked BEFORE the first line is cut to 300: a key must not be cut in half and left behind
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


# ---- the Stop hook: an unread line from the owner, or no wait running, is said before the session goes quiet -----------------
def known_name(board_dir, payload):
    """The board name of the session the payload came from, or None when it never said (a session that is not an agent here)."""
    name = os.environ.get("AGENTBOARD_NAME") or session_name(board_dir, payload.get("session_id"))
    return name if name and name != owner_name(board_dir) else None


def stop_decision(store, payload):
    """What `agentboard hook stop` answers Claude Code: {'decision': 'block', 'reason': …} to keep the session going, or None to let
    it stop. Block for an unread line the owner wrote to this session on the board (its words, quoted as data), else once for a
    session with no wait running; never when this stop already follows a block."""
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    name = known_name(store.dir, payload)
    if not name:
        return None
    owner = store.owner
    unread = store.chat_thread_new(name, after=cursors.get(store.dir, name))
    if unread:
        last = unread[-1]
        said = untrusted.one_line(last.get("text"), 160)
        more = f" and {len(unread) - 1} more" if len(unread) > 1 else ""
        left = cursors.pending(store.dir, name)
        if left and left["seq"] >= last["seq"]:   # printed by its wait (delivered), and the session has done nothing on the board since
            reason = (f"{owner} wrote to you on the board{more}; your wait printed it but you have not acted on it: “{said}”. Answer with "
                      f"`agentboard chat send \"<one line>\" --name {name} --to {owner}`, then start `agentboard chat inbox --name {name} --wait 3600` "
                      "as a background command so the next line wakes you.")
        else:
            reason = (f"{owner} wrote to you on the board{more}, unread: “{said}”. Read it with `agentboard chat inbox --name {name}`, answer with "
                      f"`agentboard chat send \"<one line>\" --name {name} --to {owner}`, then start `agentboard chat inbox --name {name} --wait 3600` "
                      "as a background command so the next line wakes you.")
        return {"decision": "block", "reason": reason[:REASON_MAX + 200]}
    if not listeners.is_listening(store.dir, name):
        return {"decision": "block", "reason": (f"Nothing is listening for you on the board: a line {owner} types there would wait until you happen to look. "
                                                f"Start `agentboard chat inbox --name {name} --wait 3600` as a background command (Bash with run_in_background) "
                                                "and end your turn; it prints the line and exits when one arrives, and that wakes you.")}
    return None


def run_stop_hook(store, stdin=None, stdout=None):
    """`agentboard hook stop`: print the decision as JSON (nothing when the session may stop), exit 0 whatever happens."""
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        out = stop_decision(store, payload)
    except (ValueError, BoardError, OSError, AttributeError, TypeError):
        out = None
    if out:
        print(json.dumps(out), file=stdout or sys.stdout)
    return 0


# ---- installing the hooks into a project's .claude/settings.json -----------------------------------------------------------
def settings_path(project_dir):
    return Path(project_dir) / ".claude" / "settings.json"


def _exe():
    """This agentboard's full path (found now). A bare name would be looked up on PATH every time a session sends a message, from a
    settings file that is usually committed with the project: whichever agentboard came first would run."""
    exe = shutil.which("agentboard")
    if exe:
        return shlex.quote(os.path.abspath(exe))
    return f"{shlex.quote(sys.executable)} -m agentboard"   # run as a module: still a full path


def hook_command(event="send-message"):
    return f"{_exe()} hook {event}"


def hook_entry(command=None, event="send-message"):
    _list, matcher = EVENTS[event]
    entry = {"hooks": [{"type": "command", "command": command or hook_command(event)}]}
    return {"matcher": matcher, **entry} if matcher else entry


def _load(project_dir):
    p = settings_path(project_dir)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except ValueError as e:
        raise BoardError(f"{p} is not valid JSON ({e}); fix it first") from e
    if not isinstance(data, dict):
        raise BoardError(f"{p} is not a JSON object")
    return p, data


def _ours(h, event=None):
    """Is this hook entry one this module writes: <agentboard> hook <event>, bare, with a full path (quoted or not), or
    <python> -m agentboard hook <event>. Read as a shell would, so a path with a space still matches."""
    if not isinstance(h, dict):
        return False
    try:
        argv = shlex.split(str(h.get("command", "")))
    except ValueError:
        return False
    if len(argv) < 3 or argv[-2] != "hook" or argv[-1] not in EVENTS or (event and argv[-1] != event):
        return False
    return os.path.basename(argv[0]) == "agentboard" or argv[-3] == "agentboard"


def _entries(hooks, event):
    """The entries of the settings list an event's hook lives in that are for it (by matcher), as (list, entry) pairs."""
    name, matcher = EVENTS[event]
    lst = hooks.get(name) if isinstance(hooks, dict) else None
    if not isinstance(lst, list):
        return None, []
    return lst, [e for e in lst if isinstance(e, dict) and (e.get("matcher") == matcher if matcher else not e.get("matcher"))]


def install(project_dir):
    """Add both hooks to the project's settings (creating the file), keeping everything else. Idempotent: a hook already there is
    left alone, one that is missing is added (an older install had only the mirror). An old bare entry is rewritten with the full
    path. Returns (path, changed)."""
    p, data = _load(project_dir)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BoardError(f"{p}: 'hooks' is not an object")
    changed = False
    for event, (name, _matcher) in EVENTS.items():
        lst = hooks.setdefault(name, [])
        if not isinstance(lst, list):
            raise BoardError(f"{p}: hooks.{name} is not a list")
        if installed_command(project_dir, event, data) is None:
            lst.append(hook_entry(event=event))
            changed = True
            continue
        for e in _entries(hooks, event)[1]:
            for h in e.get("hooks") or []:
                if _ours(h, event) and str(h.get("command", "")).strip() == HOOK_COMMAND:   # the old bare form
                    h["command"] = hook_command(event)
                    changed = True
    if not changed:
        return p, False
    from . import private
    with private.as_user():   # the project's .claude/settings.json is shared with Claude Code and your team, not board data
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n")
    return p, True


def uninstall(project_dir):
    """Remove only the hooks this module installed (and what they emptied); every other setting and hook stays. Returns (path, changed)."""
    p, data = _load(project_dir)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return p, False
    changed = False
    for event, (name, _matcher) in EVENTS.items():
        lst, mine = _entries(hooks, event)
        for entry in mine:
            if not isinstance(entry.get("hooks"), list):
                continue
            kept = [h for h in entry["hooks"] if not _ours(h)]
            if len(kept) != len(entry["hooks"]):
                changed = True
                entry["hooks"] = kept
                if not kept:
                    lst.remove(entry)
        if lst is not None and not lst and changed:
            del hooks[name]
    if not changed:
        return p, False
    if not hooks:
        del data["hooks"]
    if data:
        p.write_text(json.dumps(data, indent=2) + "\n")
    else:
        p.unlink()   # the file held nothing but our hooks: leave no empty settings.json behind
    return p, True


def installed_command(project_dir, event="send-message", data=None):
    """The command the installed hook for `event` runs, or None."""
    if data is None:
        try:
            data = json.loads(settings_path(project_dir).read_text())
        except (OSError, ValueError):
            return None
    for entry in _entries(data.get("hooks") or {}, event)[1]:
        for h in entry.get("hooks") or []:
            if _ours(h, event):
                return str(h.get("command"))
    return None


def installed(project_dir, event="send-message"):
    return installed_command(project_dir, event) is not None


def status(project_dir):
    """Which of the two hooks the project has: 'installed', 'not installed', or 'partly installed (missing: stop)'."""
    missing = [e for e in EVENTS if not installed(project_dir, e)]
    if not missing:
        return "installed"
    if len(missing) == len(EVENTS):
        return "not installed"
    return f"partly installed (missing: {', '.join(missing)}; run hooks install)"
