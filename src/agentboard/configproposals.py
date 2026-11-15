"""ORCH proposes a change to the agent configuration; the owner accepts or ignores it (card agent-config-slice-3b, docs/agent-configurations-design.md:
"ORCH may PROPOSE one: a suggestion the owner accepts or ignores, never applied on its own").

Two kinds of change, the smallest that the design's picture needs:
  apply     switch to a configuration that ships with the board       {"configuration": "build"}
  add-name  one more name on a role of the applied configuration      {"role": "qa", "name": "QA-2"}   ("add a second QA")
A proposal is a line in `.agentboard/configuration-proposals.json`: {id, at, by, kind, change, why, status, decided_at}. `why` is ORCH's one sentence, the counts that led to it
(from `agentboard insights`: "5 of the last 9 cards were reviewed twice"); the board does not read message text for it and the file never leaves the machine.

What makes it a suggestion and not an action: `propose` writes the line and changes nothing else; only the owner's Accept applies it (a shell with an agent name set is refused, so a session
cannot accept its own proposal); an Ignore is remembered, so ORCH is told not to ask for the same change again for IGNORE_QUIET_DAYS; a change already proposed, a name already on the board
and a configuration already applied are refused up front. Behind `[agents] configurations = true`. Nothing here starts a program."""
from datetime import datetime, timedelta
from pathlib import Path

from . import configurations, redact, rename, statefile
from .store import BoardError, Store

FILE = "configuration-proposals.json"
KINDS = ("apply", "add-name")
STATUSES = ("proposed", "accepted", "ignored")
MAX_KEPT = 50
WHY_MAX = 200
IGNORE_QUIET_DAYS = 7


def path(board_dir):
    return Path(board_dir) / FILE


def _stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _t(s):
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def read(board_dir):
    """Every kept proposal, oldest first; a damaged line is skipped, never trusted."""
    d = statefile.load(path(board_dir), [])
    out = []
    for r in d if isinstance(d, list) else []:
        if isinstance(r, dict) and isinstance(r.get("id"), int) and r.get("kind") in KINDS and r.get("status") in STATUSES and isinstance(r.get("change"), dict):
            out.append(r)
    return out


def pending(board_dir):
    return [r for r in read(board_dir) if r["status"] == "proposed"]


def describe(rec):
    """One line for the terminal and the picker: the change, then ORCH's reason."""
    ch = rec["change"]
    what = (f"Switch to the {ch.get('configuration')} configuration" if rec["kind"] == "apply"
            else f"Add {ch.get('name')} to the {ch.get('role')} role")
    return what + (f": {rec['why']}" if rec.get("why") else "")


def _same(a, b):
    return a["kind"] == b["kind"] and {k: str(v).lower() for k, v in a["change"].items()} == {k: str(v).lower() for k, v in b["change"].items()}


def _name_is_ok(name):
    return isinstance(name, str) and bool(rename.NAME_RE.match(name.strip())) and name == name.strip()


def propose(board_dir, by, kind, change, why, owner="you", now=None):
    """Write a proposal and return it. Refused: a proposer that is not ORCH, a setting that is off, a missing reason, an unknown configuration or role, a name already on the
    board, a configuration already applied, the same change already waiting, or ignored in the last IGNORE_QUIET_DAYS."""
    now = now or datetime.now()
    if not configurations.enabled(board_dir):
        raise BoardError("agent configurations are off: add [agents] configurations = true to config.toml")
    if str(by or "").strip().upper() != "ORCH":
        raise BoardError("only ORCH proposes a configuration change (run it as ORCH: AGENTBOARD_NAME=ORCH); the owner accepts or ignores it")
    why = redact.scrub(" ".join(str(why or "").split()), board_dir, bound=2 * WHY_MAX)[:WHY_MAX].strip()
    if not why:
        raise BoardError("say why in one sentence, with the counts (--why \"5 of the last 9 cards were reviewed twice\")")
    if kind == "apply":
        key = str((change or {}).get("configuration") or "").strip().lower().replace(" ", "-")
        cfg = configurations.builtin(key, owner)   # raises, listing what ships, for an unknown one
        cur = configurations.applied(board_dir)
        if cur is not None and cur["name"] == cfg["name"]:
            raise BoardError(f"{cfg['name']} is already applied")
        change = {"configuration": key}
    elif kind == "add-name":
        cur = configurations.applied(board_dir)
        if cur is None:
            raise BoardError("no configuration is applied: propose one to apply first")
        role = str((change or {}).get("role") or "").strip()
        name = str((change or {}).get("name") or "").strip()
        match = next((r for r in cur["roles"] if r["role"].lower() == role.lower()), None)
        if match is None:
            raise BoardError(f"the applied configuration has no role named {role!r}. Roles: {', '.join(r['role'] for r in cur['roles'])}")
        if not _name_is_ok(name):
            raise BoardError("the new name is 1 to 40 characters: letters, digits, space, dot, hyphen or underscore")
        _check_add(cur, match["role"], name, owner)   # the file with it must still be a valid configuration (a name twice, a reserved name, too many names)
        if rename.key(name) in {rename.key(n) for n in Store(board_dir).known_names()}:
            raise BoardError(f"{name} is already a name on this board: pick one no agent has had")
        change = {"role": match["role"], "name": name}
    else:
        raise BoardError(f"kind must be one of {', '.join(KINDS)}")
    rec = {"id": 0, "at": _stamp(now), "by": "ORCH", "kind": kind, "change": change, "why": why, "status": "proposed"}
    made = []

    def add(d):
        d = [r for r in (d if isinstance(d, list) else []) if isinstance(r, dict)]
        for r in d:
            if not (isinstance(r.get("kind"), str) and isinstance(r.get("change"), dict)):
                continue
            if _same(r, rec) and r.get("status") == "proposed":
                raise BoardError(f"already proposed (#{r['id']}): the owner has not answered it yet")
            if _same(r, rec) and r.get("status") == "ignored" and (_t(r.get("decided_at")) or now) > now - timedelta(days=IGNORE_QUIET_DAYS):
                raise BoardError(f"the owner ignored this on {str(r.get('decided_at'))[:10]} (#{r['id']}): do not ask again for {IGNORE_QUIET_DAYS} days")
        rec["id"] = max([r.get("id", 0) for r in d if isinstance(r.get("id"), int)] + [0]) + 1
        d.append(rec)
        made.append(rec)
        return d[-MAX_KEPT:]
    statefile.update(path(board_dir), add, default=[], indent=1)
    return made[0]


def _check_add(cfg, role, name, owner):
    """Raise a ConfigurationError if `cfg` with `name` added to `role` would not be a valid configuration."""
    configurations.validate(_with_name(cfg, role, name), owner)


def _with_name(cfg, role, name):
    d = {"configuration": configurations.VERSION, "name": cfg["name"], "description": cfg["description"], "roles": []}
    for r in cfg["roles"]:
        r = {**r, "names": list(r["names"])}
        if r["role"].lower() == role.lower():
            r["names"].append(name)
        r["count"] = len(r["names"])
        d["roles"].append(r)
    return d


def _owner_only(who, owner, doing):
    who = str(who or "").strip()
    if who and who.lower() != str(owner).lower():
        raise BoardError(f"only {owner} {doing} a proposal: it is the owner's word, not an agent's (run it from the board's button, or from a shell with no agent name set)")


def _get(board_dir, pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise BoardError("give the number of a proposal (agentboard configuration proposals)") from None
    rec = next((r for r in read(board_dir) if r["id"] == pid), None)
    if rec is None:
        raise BoardError(f"no proposal #{pid}")
    if rec["status"] != "proposed":
        raise BoardError(f"proposal #{pid} was already {rec['status']}")
    return rec


def _mark(board_dir, pid, status, now):
    def set_status(d):
        for r in d if isinstance(d, list) else []:
            if isinstance(r, dict) and r.get("id") == pid:
                r["status"], r["decided_at"] = status, _stamp(now)
        return d
    statefile.update(path(board_dir), set_status, default=[], indent=1)


def accept(board_dir, pid, owner="you", who=None, now=None):
    """The owner's yes: apply the change (the file is validated again) and mark the proposal accepted. Returns (proposal, the configuration now applied)."""
    now = now or datetime.now()
    if not configurations.enabled(board_dir):
        raise BoardError("agent configurations are off: add [agents] configurations = true to config.toml")
    _owner_only(who, owner, "accepts")
    rec = _get(board_dir, pid)
    ch = rec["change"]
    if rec["kind"] == "apply":
        cfg = configurations.builtin(ch.get("configuration"), owner)
        configurations.apply(board_dir, cfg, str(ch.get("configuration")), now)
    else:
        cur = configurations.applied(board_dir)
        if cur is None:
            raise BoardError("the configuration this was for is no longer applied: ignore the proposal")
        if rename.key(ch.get("name")) in {rename.key(n) for n in Store(board_dir).known_names()}:
            raise BoardError(f"{ch.get('name')} has become a name on this board since it was proposed: ignore the proposal")
        cfg = configurations.validate(_with_name(cur, ch.get("role"), ch.get("name")), owner)
        src = str(statefile.load(configurations.path(board_dir), {}).get("source") or "applied")
        configurations.apply(board_dir, cfg, f"{src} + {ch.get('name')}"[:80], now)
    _mark(board_dir, rec["id"], "accepted", now)
    return {**rec, "status": "accepted"}, cfg


def ignore(board_dir, pid, owner="you", who=None, now=None):
    """The owner's no: marked ignored and remembered, so ORCH does not ask for the same change again for a week. Nothing else changes."""
    now = now or datetime.now()
    _owner_only(who, owner, "ignores")
    rec = _get(board_dir, pid)
    _mark(board_dir, rec["id"], "ignored", now)
    return {**rec, "status": "ignored"}


def orch_note(board_dir, owner="the owner", ab="agentboard"):
    """What the ORCH prompt says about proposing: how, that it is only a suggestion, and what is waiting or was ignored (so it is not asked again)."""
    lines = ["Agent configuration changes (the setting is on): from the counts in `" + ab + " insights` you may suggest one change, one sentence, counts only:",
             f"  {ab} configuration propose --apply build --why \"<the counts>\"          (switch to a configuration that ships)",
             f"  {ab} configuration propose --add-name QA-2 --role qa --why \"<the counts>\"   (one more name on a role of the applied one)",
             f"It is a suggestion: {owner} accepts or ignores it (the board's configuration picker, or `" + ab + " configuration accept|ignore N`). Never apply one yourself; "
             f"an ignored one is not asked again for {IGNORE_QUIET_DAYS} days."]
    recs = read(board_dir)
    now = datetime.now()
    waiting = [r for r in recs if r["status"] == "proposed"]
    quiet = [r for r in recs if r["status"] == "ignored" and (_t(r.get("decided_at")) or now) > now - timedelta(days=IGNORE_QUIET_DAYS)]
    if waiting:
        lines.append("Waiting for " + str(owner) + ": " + "; ".join(f"#{r['id']} {describe(r)}" for r in waiting))
    if quiet:
        lines.append("Ignored lately, do not repeat: " + "; ".join(f"#{r['id']} {describe(r)}" for r in quiet))
    return "\n".join(lines)
