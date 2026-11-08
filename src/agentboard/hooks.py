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
from .store import DEFAULT_OWNER, BoardError, owner_name

HOOK_COMMAND = "agentboard hook send-message"
EVENTS = {"send-message": ("PostToolUse", "SendMessage"), "stop": ("Stop", None)}   # hook event -> (settings list, matcher)
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
MAX_SESSIONS = 200
REASON_MAX = 600   # the longest reason the Stop hook returns: the block text with the quoted line and the commands fits


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


def resolve_sender(board_dir, payload, fallback=True):
    """$AGENTBOARD_NAME, else the name this session gave itself, else (with fallback) a short handle from the session id, else None."""
    name = os.environ.get("AGENTBOARD_NAME") or session_name(board_dir, payload.get("session_id"))
    if name or not fallback:
        return name or None
    sid = str(payload.get("session_id") or "")
    return f"session-{sid[:6]}" if sid else "a session"


def clean_to(to):
    """'worker [3fa9c1]' -> 'worker'; 'main' is a subagent's own conversation, not a peer."""
    t = re.sub(r"\s*\[[^\]]*\]\s*$", "", str(to or "")).strip()
    return None if not t or t.lower() == "main" else t


def mirror_send_message(store, payload):
    """Post a SendMessage call to the chat. Returns the message, or None when there is nothing to mirror (not a SendMessage,
    no text, sent to 'main', agent chat off for this board, or a session the board does not know). Only a session that said who it
    is on this board (AGENTBOARD_NAME in its shell, or `agentboard me --name X` once) is mirrored: with the hooks in the user's own
    settings (`hooks install --user`), every Claude Code session on the Mac runs this hook, and the text of a session in another
    project is not this board's business (the chat security review, Nov 8)."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "SendMessage":
        return None
    inp = payload.get("tool_input") or {}
    text = str(inp.get("message") or "").strip()
    to = clean_to(inp.get("to"))
    if not text or not to:
        return None
    if not store.chat_agents():
        return None
    sender = known_name(store.dir, payload)
    if sender is None:
        return None
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
    name = resolve_sender(board_dir, payload, fallback=False)
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
    who = owner if owner != DEFAULT_OWNER else "the board's owner"   # the prose: without a [board] owner the name is "you", and "you wrote to you" reads wrong
    unread = [m for m in store.chat_thread_new(name, after=cursors.get(store.dir, name)) if m.get("via") != "board"]   # the board's own notices need no answer
    if unread:
        last = unread[-1]
        seq = last["seq"]   # the answer names the line it answers (--reply-to), so the panel can say "answered" rather than "wrote back"
        said = untrusted.one_line(last.get("text"), 160)
        more = f" and {len(unread) - 1} more" if len(unread) > 1 else ""
        left = cursors.pending(store.dir, name)
        if left and left["seq"] >= last["seq"]:   # printed by its wait (delivered), and the session has done nothing on the board since
            reason = (f"{who[0].upper()}{who[1:]} wrote to you on the board{more}; your wait printed it but you have not acted on it: “{said}”. Answer with "
                      f"`agentboard chat send \"<one line>\" --name {name} --to {owner} --reply-to {seq}`, then start `agentboard chat inbox --name {name} --wait 3600` "
                      "as a background command so the next line wakes you.")
        else:
            reason = (f"{who[0].upper()}{who[1:]} wrote to you on the board{more}, unread: “{said}”. Read it with `agentboard chat inbox --name {name}`, answer with "
                      f"`agentboard chat send \"<one line>\" --name {name} --to {owner} --reply-to {seq}`, then start `agentboard chat inbox --name {name} --wait 3600` "
                      "as a background command so the next line wakes you.")
        return {"decision": "block", "reason": reason[:REASON_MAX]}
    if not listeners.is_listening(store.dir, name):
        return {"decision": "block", "reason": (f"Nothing is listening for you on the board: a line {who} types there would wait until you happen to look. "
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


def hook_command(event="send-message", board_dir=None):
    """The command a hook runs: agentboard's full path, the event and, when given, the board folder (--dir), so the hook finds the board
    from any folder a session starts in (chat-f6: without it a home-folder session's Stop hook found no board and printed nothing)."""
    cmd = f"{_exe()} hook {event}"
    return cmd + (f" --dir {shlex.quote(str(Path(board_dir).resolve()))}" if board_dir else "")


def hook_entry(command=None, event="send-message", board_dir=None):
    _list, matcher = EVENTS[event]
    entry = {"hooks": [{"type": "command", "command": command or hook_command(event, board_dir)}]}
    return {"matcher": matcher, **entry} if matcher else entry


def hook_board(command):
    """The board folder an installed hook command names (--dir), or None for an older one without it."""
    try:
        argv = shlex.split(str(command or ""))
    except ValueError:
        return None
    if "--dir" in argv:
        j = argv.index("--dir")
        return argv[j + 1] if j + 1 < len(argv) else None
    return None


def stop_hook_state(project_dir):
    """Where the Stop hook is installed and whether its board folder is good, for `agentboard doctor`: [(settings path, text, ok)]; []
    when it is installed nowhere (the user's settings and the project's are both looked at)."""
    out = []
    for folder in (Path.home(), Path(project_dir)):
        cmd = installed_command(folder, "stop")
        if cmd is None:
            continue
        board = hook_board(cmd)
        if board is None:
            out.append((settings_path(folder), "installed without a board folder, so it finds the board only from the project: run agentboard hooks install --user again, then restart sessions", False))
        elif not (Path(board) / "tasks.json").is_file():
            out.append((settings_path(folder), f"installed but no board found at {board}: run agentboard hooks install --user from the board's folder", False))
        else:
            out.append((settings_path(folder), f"installed for the board at {board}", True))
    return out


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
    try:
        i = argv.index("hook")
    except ValueError:
        return False
    if i < 1 or i + 1 >= len(argv) or argv[i + 1] not in EVENTS or (event and argv[i + 1] != event):
        return False
    for extra in argv[i + 2:]:   # only our own options may follow the event (--dir <folder>)
        if extra.startswith("-") and extra != "--dir":
            return False
    return os.path.basename(argv[0]) == "agentboard" or (i >= 3 and argv[i - 1] == "agentboard" and argv[i - 2] == "-m")


def _entries(hooks, event):
    """The entries of the settings list an event's hook lives in that are for it (by matcher), as (list, entry) pairs."""
    name, matcher = EVENTS[event]
    lst = hooks.get(name) if isinstance(hooks, dict) else None
    if not isinstance(lst, list):
        return None, []
    return lst, [e for e in lst if isinstance(e, dict) and (e.get("matcher") == matcher if matcher else not e.get("matcher"))]


def install(project_dir, board_dir=None):
    """Add both hooks to the settings under `project_dir` (the project's .claude/settings.json; the user's own when `project_dir` is the
    home folder), creating the file and keeping everything else. Idempotent: a hook already there is left alone, one that is missing is
    added (an older install had only the mirror). An old bare entry, or one that names no board folder or another one when `board_dir`
    is given, is rewritten. Returns (path, changed)."""
    p, data = _load(project_dir)
    want_board = str(Path(board_dir).resolve()) if board_dir else None
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BoardError(f"{p}: 'hooks' is not an object")
    changed = False
    for event, (name, _matcher) in EVENTS.items():
        lst = hooks.setdefault(name, [])
        if not isinstance(lst, list):
            raise BoardError(f"{p}: hooks.{name} is not a list")
        if installed_command(project_dir, event, data) is None:
            lst.append(hook_entry(event=event, board_dir=board_dir))
            changed = True
            continue
        for e in _entries(hooks, event)[1]:
            for h in e.get("hooks") or []:
                if not _ours(h, event):
                    continue
                cmd = str(h.get("command", "")).strip()
                bare = cmd == HOOK_COMMAND or cmd == f"agentboard hook {event}"   # the old bare form
                if bare or (want_board and hook_board(cmd) != want_board):   # or one that names no board folder, or another board
                    h["command"] = hook_command(event, board_dir)
                    changed = True
    if not changed:
        return p, False
    from . import private
    with private.as_user():   # the project's .claude/settings.json is shared with Claude Code and your team, not board data
        p.parent.mkdir(parents=True, exist_ok=True)
        write_settings(p, json.dumps(data, indent=2) + "\n")
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
        write_settings(p, json.dumps(data, indent=2) + "\n")
    else:
        p.unlink()   # the file held nothing but our hooks: leave no empty settings.json behind
    return p, True


def write_settings(p, text):
    """Write a Claude Code settings file the safe way: through a temp file in the same folder, flushed, then renamed over the target, so a
    failure (disk full, a kill) leaves the old file whole, never a truncated one; the file as it was before agentboard ever touched it is
    kept once as <file>.orig (never overwritten), and the version before the last write as <file>.bak; the file's mode is kept (a new
    file is 0600); a symlinked settings.json (dotfiles) stays a symlink and its target is rewritten. The user's own ~/.claude/settings.json
    holds permissions, env and other hooks, so this matters there most (the chat security review, Nov 8)."""
    import tempfile
    p = Path(p)
    target = p.resolve() if p.is_symlink() else p
    mode = None
    if target.exists():
        mode = os.stat(target).st_mode & 0o777
        if not os.path.exists(f"{target}.orig"):   # the pristine file, once: a later install or uninstall never replaces it
            with contextlib_suppress(OSError):
                shutil.copy2(target, f"{target}.orig")
        with contextlib_suppress(OSError):
            shutil.copy2(target, f"{target}.bak")
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode if mode is not None else 0o600)
        os.replace(tmp, target)
    except BaseException:
        with contextlib_suppress(OSError):
            os.unlink(tmp)
        raise


def contextlib_suppress(*exc):
    import contextlib
    return contextlib.suppress(*exc)


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
