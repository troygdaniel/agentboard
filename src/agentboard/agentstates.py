"""Agent state history (card agentboard-insights-agent-states, docs/insights-design.md capture 4): what each agent was doing, hour by hour, so idle time can be read
back with its cause instead of guessed from the gaps between cards.

Behind `[insights] enabled = true`. The server calls `sample()` once a minute; it appends one line to `.agentboard/agent-states.jsonl` for every agent whose state
changed, and a heartbeat line for one that has not changed in 15 minutes (so a stretch with no lines is time the board was not watching, not a long state).
A line is {"at": "2026-11-14T14:50:00", "agent": "AGENT-1", "state": "working"}: a name, a state word and a time, no text of any kind, local only.

The states: working (an open card, touched within STALE_MIN minutes), quiet, abandoned (an open card silent that long, see hud.py), waiting (every open card is a
question to the owner), review (every open card waits for the owner's sign-off), listening (no open card and a wait running: waiting for work) and away (no open card and
no wait running). An agent with a card in review that is busy on another card is working: the HUD shows the review first, this does not. Reading and the observations
that use it are in insights.py; this module only writes. No program is started and nothing leaves the board."""
import json
from datetime import datetime
from pathlib import Path

from . import hud, insights, listeners

FILE = "agent-states.jsonl"
STATES = ("working", "quiet", "abandoned", "waiting", "review", "listening", "away")
BEAT_S = 15 * 60          # a line at least this often for every agent, changed or not
MAX_BYTES = 2_000_000     # past this the file is rolled to agent-states.jsonl.1 (one old file is kept)
TAIL_BYTES = 128_000      # how much of the end of the file is read to find each agent's last line


def agent_state(cards, listening, now, abandoned_min=hud.ABANDONED_MIN):
    """The state of one agent from its top-level cards (a list of card dicts) and whether a wait is running under its name."""
    doing = [t for t in cards if t.get("status") == "doing"]
    if not doing:
        return "listening" if listening else "away"
    active = [t for t in doing if not t.get("needs_input") and not t.get("review")]
    if not active:
        return "waiting" if any(t.get("needs_input") for t in doing) else "review"
    stamps = [x for x in (hud._t(t.get("updated")) for t in active) if x]
    last = max(stamps) if stamps else None
    if last is None or (now - last).total_seconds() / 60 > abandoned_min:
        return "abandoned"
    return "quiet" if (now - last).total_seconds() / 60 > hud.STALE_MIN else "working"


def current(tasks, listening_names, now, roster=(), retired=(), abandoned_min=hud.ABANDONED_MIN):
    """{agent: state} for every agent that holds a card on the board or is on the roster, less the retired. `listening_names`: the names with a wait running."""
    retired = {str(r).lower() for r in retired or ()}
    live = {str(n).lower() for n in listening_names or ()}
    held = {}
    for t in tasks:
        if isinstance(t, dict) and t.get("agent") and not t.get("parent_id"):
            held.setdefault(t["agent"], []).append(t)
    for name in roster or ():
        if name:
            held.setdefault(name, [])
    return {name: agent_state(cards, name.lower() in live, now, abandoned_min) for name, cards in held.items() if name.lower() not in retired}


def _stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _t(s):
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def _lines(path):
    """The parsed lines of one file, oldest first; a line that is not one of ours is skipped."""
    out = []
    try:
        text = Path(path).read_text()
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        at = _t(d.get("at")) if isinstance(d, dict) else None
        if at and isinstance(d.get("agent"), str) and d.get("state") in STATES:
            out.append((d["agent"], d["state"], at))
    return out


def read(board_dir):
    """Every recorded state line as (agent, state, time), oldest first: the rolled file, then the current one."""
    d = Path(board_dir)
    return sorted(_lines(d / (FILE + ".1")) + _lines(d / FILE), key=lambda x: x[2])


def _last_by_agent(path):
    """{agent: (state, time)}: each agent's last line, read from the end of the file only."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return {}
    lines = tail.splitlines()[1:] if size > TAIL_BYTES else tail.splitlines()   # the first line of a cut tail is partial
    out = {}
    for raw in lines:
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        at = _t(d.get("at")) if isinstance(d, dict) else None
        if at and isinstance(d.get("agent"), str) and d.get("state") in STATES:
            out[d["agent"]] = (d["state"], at)
    return out


def sample(store, now=None):
    """One tick: with [insights] on, append a line for each agent whose state changed or that has no line for BEAT_S. Returns how many lines were written."""
    if not insights.enabled(store.dir):
        return 0
    from . import configurations, prompt as promptlib
    now = now or datetime.now()
    conf = promptlib.load_config(store.dir)
    states = current(store.load(), listeners.listening(store.dir), now, configurations.merge(hud.roster(conf), store.dir), hud.retired(conf), hud.stale_minutes(conf))
    path = Path(store.dir) / FILE
    try:
        if path.stat().st_size > MAX_BYTES:
            path.replace(path.with_name(FILE + ".1"))   # the next lines start a fresh file, with every agent's state first
    except OSError:
        pass
    last = _last_by_agent(path)
    out = []
    for name, state in sorted(states.items()):
        prev = last.get(name)
        if prev is None or prev[0] != state or (now - prev[1]).total_seconds() >= BEAT_S:
            out.append(json.dumps({"at": _stamp(now), "agent": name, "state": state}))
    if out:
        with open(path, "a") as f:
            f.write("\n".join(out) + "\n")
    return len(out)
