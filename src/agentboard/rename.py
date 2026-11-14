"""`agentboard rename OLD NEW`: give an agent a new name without losing its history (card agentboard-rename-agent, docs/agent-configurations-design.md).

What moves, and what does not (the table in the design):

  moves      a card's `agent`, a log line's `by` and `actor`, a `learned` note's `by`, a chat line's `sender` and `to` (tasks.json and archive.json, in one
             write each, after a snapshot); the keys of chat-cursors.json, chat-delivered.json, chat-listeners.json and chat-autopilot.json; the name in
             sessions.json; the roster entry in config.toml's `[orch] agents`; the colour: the pin in `[agent_colors]` moves, or one is added that is the
             palette slot the old name had, so the agent keeps its colour (agentboard-wide: the page picks a colour by name)
  stays      words: a log or chat line that says the old name in its text, the hourly backups, and agent-states.jsonl (the insights history, by name).
             History is history

The old name goes on working: names.add() writes the alias FIRST, so a half-finished rename is safe to run again (the same command finishes it), and
a terminal still started as the old name keeps updating its cards (cli._canon_names). `--undo` runs the last rename the other way and drops the alias.
Refused: a name another agent has or has had (a card, a line, a state file), ORCH, `all`, the owner's name, anything outside letters, digits, space,
dot, hyphen and underscore (the new name goes into config.toml as text), and an old name nobody has. `--dry-run` writes nothing. No program is started."""
import json
import re
from datetime import datetime
from pathlib import Path

from . import backup, cursors, listeners, names, statefile, tomlread
from .store import BoardError

NAME_RE = re.compile(r"^\w[\w .-]{0,39}$")
RESERVED = {"orch", "all", "you"}
RECORDS = "renames.json"
KEEP_RECORDS = 20


def key(name):
    return str(name or "").strip().lower()


def _mention(old):
    return re.compile(r"(?<![\w-])" + re.escape(old) + r"(?![\w-])", re.I)


# -- what the board holds under a name ------------------------------------------------------------------------------

def _cards(store):
    """(data, archive cards) read under the board's lock; the caller holds it."""
    return store._read(), store._read_archive()


def _count_cards(cards, k, mention):
    """Counts for one list of cards: held, open, log lines that carry the name in a field, lines that merely say it, `learned` notes."""
    held = opened = fields = said = learned = 0
    for t in cards:
        if key(t.get("agent")) == k:
            held += 1
            opened += t.get("status") != "done"
        lrn = t.get("learned")
        if isinstance(lrn, dict) and key(lrn.get("by")) == k:
            learned += 1
        for e in t.get("log") or []:
            if not isinstance(e, dict):
                continue
            if key(e.get("by")) == k or key(e.get("actor")) == k:
                fields += 1
            elif mention.search(str(e.get("text") or "")):
                said += 1
    return held, opened, fields, said, learned


def _names_in_use(store, data, archive):
    """Every name (lower-cased) that is on the board in a field a rename would have to keep apart: the card holders and log lines, the chat, the state
    files, the roster. Not the free text of a line, and not the aliases (checked on their own)."""
    used = {"orch", key(store.owner)}
    for t in list(data["tasks"]) + list(archive):
        used.add(key(t.get("agent")))
        lrn = t.get("learned")
        if isinstance(lrn, dict):
            used.add(key(lrn.get("by")))
        for e in t.get("log") or []:
            if isinstance(e, dict):
                used.add(key(e.get("by")))
                used.add(key(e.get("actor")))
    for m in data["chat"]:
        if isinstance(m, dict):
            used.add(key(m.get("sender")))
            used.add(key(m.get("to")))
    d = store.dir
    used.update(cursors.read(d))
    used.update(cursors.read_delivered(d))
    used.update(key(k) for k in listeners._read(d))
    auto = statefile.load(d / "chat-autopilot.json", {})
    if isinstance(auto, dict):
        for f in ("shared", "seen"):
            if isinstance(auto.get(f), dict):
                used.update(key(k) for k in auto[f])
    for rec in statefile.load(d / "sessions.json", {}).values():
        if isinstance(rec, dict):
            used.add(key(rec.get("name")))
    used.update(key(n) for n in _roster(d))
    used.discard("")
    return used


def _roster(board_dir):
    try:
        conf = tomlread.loads((Path(board_dir) / "config.toml").read_text())
    except (OSError, ValueError, tomlread.TOMLDecodeError):
        return []
    spec = (conf.get("orch") or {}).get("agents") if isinstance(conf.get("orch"), dict) else None
    return [str(p["name"]).strip() for p in spec if isinstance(p, dict) and str(p.get("name") or "").strip()] if isinstance(spec, list) else []


# -- config.toml: a few exact edits, checked by reading the result back -----------------------------------------------

def _section(text, name):
    """(start, end) of the body of `[name]` (after its header line, up to the next header or the end), or None."""
    m = re.search(r"^\[" + re.escape(name) + r"\][^\n]*(?:\n|$)", text, re.M)
    if not m:
        return None
    nxt = re.search(r"^\[", text[m.end():], re.M)
    return m.end(), (m.end() + nxt.start()) if nxt else len(text)


def edit_config(text, old, new, pin=None, undoing=False):
    """The config.toml text after the rename, the lines saying what changed, the pin that was made ("added", "moved" or None), and notes for the
    owner. `text` comes back unchanged (changed lines empty) when an edit cannot be made and checked; a note says what to do by hand.
    pin: when undoing, what the rename did to the colour ("added": remove it again; "moved": move it back)."""
    lines, notes, made = [], [], None
    out = text
    roster = _roster_of(text)
    if old in roster and new in roster:
        notes.append(f'[orch] agents already lists "{new}" as well as "{old}": remove one by hand')
    elif old in roster:
        out, n = re.subn(r'(\{\s*name\s*=\s*)"' + re.escape(old) + '"', lambda m: m.group(1) + '"' + new + '"', out)
        if n:
            lines.append(f'[orch] agents: name "{old}" becomes "{new}"')
        else:
            notes.append(f'[orch] agents has "{old}" in a form this edit does not recognise: change it to "{new}" by hand')
    sec = _section(out, "agent_colors")
    body = out[sec[0]:sec[1]] if sec else ""
    own = re.search(r'^([ \t]*)"?' + re.escape(old) + r'"?([ \t]*=[ \t]*)(.*)$', body, re.M)
    if undoing and pin == "added":
        mine = re.search(r'^[ \t]*"?' + re.escape(old) + r'"?[ \t]*=.*\n?', body, re.M)
        if mine:
            body = body[:mine.start()] + body[mine.end():]
            out = out[:sec[0]] + body + out[sec[1]:]
            if not body.strip():   # the table was made by the rename and is empty again: take its header with it
                out = re.sub(r"\n*^\[agent_colors\][ \t]*\n*", "\n", out, count=1, flags=re.M).lstrip("\n") if out.strip() != "[agent_colors]" else ""
            lines.append(f'[agent_colors]: the colour pinned for "{old}" is removed again')
    elif own:
        body = body[:own.start()] + f'{own.group(1)}"{new}"{own.group(2)}{own.group(3)}' + body[own.end():]
        out = out[:sec[0]] + body + out[sec[1]:]
        made = "moved"
        lines.append(f'[agent_colors]: the colour for "{old}" moves to "{new}"')
    elif not undoing and names.agent_slot(new) != names.agent_slot(old):
        colour = f"var(--a{names.agent_slot(old)})"
        entry = f'"{new}" = "{colour}"\n'
        if sec:
            out = out[:sec[0]] + entry + out[sec[0]:]
        else:
            out = out.rstrip("\n") + f"\n\n[agent_colors]\n{entry}"
        made = "added"
        lines.append(f'[agent_colors]: "{new}" = "{colour}" (the colour "{old}" has, so it stays the same)')
    if out != text:
        try:
            conf = tomlread.loads(out)
        except (ValueError, tomlread.TOMLDecodeError):
            return text, [], None, ["config.toml was left as it is: the edit did not read back as TOML. Change the roster and colour for the new name by hand"]
        if made == "added" and (conf.get("agent_colors") or {}).get(new) is None:
            return text, [], None, ["config.toml was left as it is: the colour entry did not read back. Pin the colour by hand if you want it kept"]
    return out, lines, made, notes


def _roster_of(text):
    try:
        conf = tomlread.loads(text)
    except (ValueError, tomlread.TOMLDecodeError):
        return []
    spec = (conf.get("orch") or {}).get("agents") if isinstance(conf.get("orch"), dict) else None
    return [str(p["name"]).strip() for p in spec if isinstance(p, dict) and str(p.get("name") or "").strip()] if isinstance(spec, list) else []


# -- the records, for --undo ----------------------------------------------------------------------------------------------

def _records(board_dir):
    d = statefile.load(Path(board_dir) / RECORDS, [])
    return [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []


def last_record(board_dir):
    """The most recent rename that has not been undone, or None."""
    done = [r for r in _records(board_dir) if not r.get("undone")]
    return done[-1] if done else None


# -- plan and apply -------------------------------------------------------------------------------------------------------

def _valid(old, new, owner):
    new = (new or "").strip()
    if not key(old):
        raise BoardError("say which agent to rename")
    if not new or not NAME_RE.match(new) or new != new.strip():
        raise BoardError("the new name is 1 to 40 characters: letters, digits, space, dot, hyphen or underscore")
    if key(new) in RESERVED or key(new) == key(owner):
        raise BoardError(f"{new} is a name the board keeps for itself")
    if key(old) in RESERVED or key(old) == key(owner):
        raise BoardError(f"{old} is not an agent: the board keeps that name")
    return new


def plan(store, old, new, undoing=None):
    """What a rename of `old` to `new` would touch, as a dict (nothing is written). Raises BoardError for the refusals. `undoing`: the record being undone."""
    old = (old or "").strip()
    new = _valid(old, new, store.owner)
    ok, nk = key(old), key(new)
    al = names.read(store.dir)
    resume = key(al.get(ok, {}).get("to")) == nk       # the alias says this very rename was started: run it again to finish it
    with store._lock():
        data, archive = _cards(store)
        used = _names_in_use(store, data, archive)
        mention = _mention(old)
        cards = list(data["tasks"]) + list(archive)
        held, opened, fields, said, learned = _count_cards(cards, ok, mention)
        chat = sum(1 for m in data["chat"] if isinstance(m, dict) and (key(m.get("sender")) == ok or key(m.get("to")) == ok))
        chat_said = sum(1 for m in data["chat"] if isinstance(m, dict) and key(m.get("sender")) != ok and key(m.get("to")) != ok and mention.search(str(m.get("text") or "")))
    sides = []
    d = store.dir
    if ok in cursors.read(d):
        sides.append("its read position in the chat")
    if ok in cursors.read_delivered(d):
        sides.append("what was delivered to it")
    live = len(listeners._read(d).get(next((k for k in listeners._read(d) if key(k) == ok), ""), []))
    if live:
        sides.append(f"{live} wait{'s' if live != 1 else ''} it has running (they keep running; new ones register as {new})")
    sess = sum(1 for r in statefile.load(d / "sessions.json", {}).values() if isinstance(r, dict) and key(r.get("name")) == ok)
    if sess:
        sides.append(f"{sess} session link{'s' if sess != 1 else ''} for mirrored messages")
    here = held or fields or chat or sides or ok in {key(n) for n in _roster(d)} or ok in used
    if not here:
        if ok in al:
            raise BoardError(f"{old} is already {al[ok]['to']}: nothing is left to rename (the old name still works as an alias)")
        here_names = ", ".join(sorted(n for n in store.known_names() if n != store.owner)[:8])
        raise BoardError(f"no agent named {old} on this board. Names here: {here_names}")
    if ok != nk:
        if nk in used and not resume and not undoing:
            raise BoardError(f"{new} is already on this board (a card, a line or a state file under that name); pick a name no agent has had")
        if nk in al and not (undoing and key(al[nk].get("to")) == ok) and not resume:
            raise BoardError(f"{new} is an old name that still works as an alias for {al[nk]['to']}; pick another, or wait for it to expire")
    text = (d / "config.toml").read_text() if (d / "config.toml").exists() else ""
    _, cfg_lines, _, notes = edit_config(text, old, new, pin=(undoing or {}).get("pin"), undoing=bool(undoing))
    return {"old": old, "new": new, "cards": held, "open": opened, "log_lines": fields + learned, "chat_lines": chat,
            "kept_lines": said + chat_said, "sides": sides, "config": cfg_lines, "notes": notes, "resume": resume,
            "nothing": not (held or fields or learned or chat or sides or cfg_lines)}


def _n(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def describe(p, dry=False):
    """The plan or the result as plain lines for the terminal."""
    out = []
    old, new = p["old"], p["new"]
    out.append(f"{'Would rename' if dry else 'Renamed'} {old} to {new}:")
    out.append(f"  {_n(p['cards'], 'card')} it holds or held ({p['open']} still open stay its), with their claims")
    out.append(f"  {_n(p['log_lines'], 'history line')} that name it in a field, {_n(p['chat_lines'], 'chat line')} it sent or was sent")
    for s in p["sides"]:
        out.append(f"  {s}")
    for c in p["config"]:
        out.append(f"  config.toml, {c}")
    out.append(f"  {_n(p['kept_lines'], 'line')} that say \"{old}\" in their words stay as written: history is history")
    for n in p["notes"]:
        out.append(f"  note: {n}")
    if dry:
        out.append("Nothing was changed. Run it again without --dry-run to rename.")
    else:
        out.append(f"In the terminal that was {old}: type /rename {new} and set AGENTBOARD_NAME={new}.")
        out.append(f"Until then --name {old} still works (it means {new}) for a day after its last use. Undo: agentboard rename --undo")
    return out


def _rekey(d, ok, new, combine=None):
    """Move the entry whose key lower-cases to `ok` to the key `new` (spelled as the file spells its keys). A new-name entry that is already there wins unless
    `combine(old_value, existing)` says how to join them. True if anything moved."""
    moved = False
    for k in [k for k in d if key(k) == ok]:
        v = d.pop(k)
        if new in d and combine:
            d[new] = combine(v, d[new])
        elif new not in d:
            d[new] = v
        moved = True
    return moved


def _side_files(board_dir, old, new):
    ok = key(old)
    lower = key(new)
    with listeners.locked(board_dir, "cursors"):
        for fname, comb in ((cursors.FILE, lambda a, b: max(a, b)), (cursors.DELIVERED, lambda a, b: a if a.get("seq", 0) > b.get("seq", 0) else b)):
            p = Path(board_dir) / fname
            d = statefile.load(p, {})
            if isinstance(d, dict) and _rekey(d, ok, lower, comb):
                backup.write_atomic(p, json.dumps(d), keep_previous=False)
    with listeners.locked(board_dir):
        d = listeners._read(board_dir)
        if _rekey(d, ok, new, lambda a, b: list(b) + list(a)):
            listeners._write(board_dir, d)

    def auto(d):
        if isinstance(d, dict):
            if isinstance(d.get("shared"), dict):
                _rekey(d["shared"], ok, new)
            if isinstance(d.get("seen"), dict):
                _rekey(d["seen"], ok, lower, lambda a, b: max(a, b))
        return d
    p = Path(board_dir) / "chat-autopilot.json"
    if p.exists():
        statefile.update(p, auto)

    def sess(d):
        if isinstance(d, dict):
            for rec in d.values():
                if isinstance(rec, dict) and key(rec.get("name")) == ok:
                    rec["name"] = new
        return d
    p = Path(board_dir) / "sessions.json"
    if p.exists():
        statefile.update(p, sess, indent=2)


def _rewrite(cards, ok, new):
    for t in cards:
        if key(t.get("agent")) == ok:
            t["agent"] = new
        lrn = t.get("learned")
        if isinstance(lrn, dict) and key(lrn.get("by")) == ok:
            lrn["by"] = new
        rep = t.get("reply")
        if isinstance(rep, dict) and key(rep.get("by")) == ok:
            rep["by"] = new
        for e in t.get("log") or []:
            if isinstance(e, dict):
                for f in ("by", "actor"):
                    if key(e.get(f)) == ok:
                        e[f] = new


def apply(store, old, new, undoing=None, now=None):
    """Rename `old` to `new` for real; returns the plan (what changed). The alias is written first, then the cards and chat in one write each (after a
    snapshot), then the state files, then config.toml. Run it again after a crash and it finishes."""
    now = now or datetime.now()
    p = plan(store, old, new, undoing)
    old, new = p["old"], p["new"]
    ok = key(old)
    names.add(store.dir, old, new, now)   # (when undoing, this also drops the alias for the name that is coming back)
    with store._lock():
        data, archive = _cards(store)
        before = (json.dumps(data["tasks"]), json.dumps(data["chat"]), json.dumps(archive))
        _rewrite(data["tasks"], ok, new)
        _rewrite(archive, ok, new)
        for m in data["chat"]:
            if isinstance(m, dict):
                for f in ("sender", "to", "closest"):
                    if key(m.get(f)) == ok:
                        m[f] = new
        if (json.dumps(data["tasks"]), json.dumps(data["chat"])) != before[:2]:
            store.backups.take("before-rename")   # a snapshot first: the rewrite is the one thing here that is hard to take back by hand
            store._write(data)
        if json.dumps(archive) != before[2]:
            store._write_archive(archive)
    _side_files(store.dir, old, new)
    cfg = store.dir / "config.toml"
    pin = None
    if cfg.exists():
        text = cfg.read_text()
        out, lines, pin, notes = edit_config(text, old, new, pin=(undoing or {}).get("pin"), undoing=bool(undoing))
        if out != text:
            backup.write_atomic(cfg, out)   # the version before stays as config.toml.bak
        p["config"], p["notes"] = lines, notes
    if undoing:
        _mark(store.dir, undoing)
    else:
        _record(store.dir, {"old": old, "new": new, "at": now.strftime("%Y-%m-%dT%H:%M:%S"), "pin": pin})
    return p


def _record(board_dir, rec):
    statefile.update(Path(board_dir) / RECORDS, lambda d: ((d if isinstance(d, list) else []) + [rec])[-KEEP_RECORDS:], default=[])


def _mark(board_dir, rec):
    def mark(d):
        for r in (d if isinstance(d, list) else []):
            if r == rec:
                r["undone"] = True
        return d
    statefile.update(Path(board_dir) / RECORDS, mark, default=[])


def undo(store, now=None):
    """Run the last rename the other way. Returns the plan of that, or raises BoardError when there is none to undo."""
    rec = last_record(store.dir)
    if rec is None:
        raise BoardError("no rename to undo (the board keeps the last 20)")
    return apply(store, rec["new"], rec["old"], undoing=rec, now=now)
