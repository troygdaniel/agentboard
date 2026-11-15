"""Agent configurations (card agent-config-slice-2, docs/agent-configurations-design.md): a small file saying which agent names and roles exist and how the board
shows them. The owner picks one; the board reflects the terminals the owner starts and starts nothing itself.

A configuration is a JSON object, validated here and nowhere trusted before it is:

    {"configuration": 1, "name": "Day to day", "description": "...",
     "roles": [{"role": "caller", "names": ["Caller-1"], "purpose": "...", "model": "sonnet", "size": "M",
                "may": ["research"], "may_not": ["place a call"], "tools": ["board"], "count": 1}]}

Names, roles and rules only: no person, number or address belongs in one (the shipped examples are scanned by tests/publiccheck.py). Unknown keys are refused, so a
file passed around cannot carry anything the board does not read. `model` and `size` (S, M or L, the words of insights capture 6 and 8) are advice: the board
cannot choose a model. `count`, when given, must equal the number of names.

Behind `[agents] configurations = true` (off by default). `agentboard configuration apply NAME|FILE` writes the applied copy to `.agentboard/configuration.json`; the
roster (hud.roster, the ORCH prompt), the role chips on the page and the role block in a card prompt read it. Applying changes the roster and the labels only:
cards, claims and chat stay with the names. Switching to another configuration leaves an agent that is not in it visible, as before. Nothing here starts a
program, makes a call or sends anything."""
import json
from datetime import datetime
from pathlib import Path

from . import rename, statefile, tomlread
from .store import BoardError

VERSION = 1
FILE = "configuration.json"
BUILTIN_DIR = Path(__file__).parent / "configurations"
BUILTIN = {"build": "build.json", "dream-up": "dream-up.json", "day-to-day": "day-to-day.json"}
BUILTIN_ORDER = ("build", "dream-up", "day-to-day")   # the order the board lists them in
SIZES = ("S", "M", "L")
MAX_ROLES, MAX_NAMES, MAX_LIST = 12, 8, 12
TOP_KEYS = {"configuration", "name", "description", "roles"}
ROLE_KEYS = {"role", "names", "purpose", "model", "size", "may", "may_not", "tools", "count"}
# what a role of the Day to day configuration may never do on its own: a test pins these in the shipped file
OUTSIDE_ACTIONS = ("place a call", "send a message", "pay", "submit a form")
MAX_ERRORS = 6


class ConfigurationError(BoardError):
    """A configuration file that does not meet the schema: the message lists what is wrong, one clause per fault."""


def _text(v, cap, what, bad, required=False):
    if v is None or v == "":
        if required:
            bad(f"{what} is missing")
        return ""
    if not isinstance(v, str) or any(ord(c) < 32 for c in v):
        bad(f"{what} must be one line of text")
        return ""
    v = v.strip()
    if len(v) > cap:
        bad(f"{what} is over {cap} characters")
    return v[:cap]


def _list(v, what, bad, cap=80, limit=MAX_LIST):
    if v is None:
        return []
    if not isinstance(v, list):
        bad(f"{what} must be a list")
        return []
    if len(v) > limit:
        bad(f"{what} has more than {limit} entries")
    out = []
    for i, x in enumerate(v[:limit]):
        s = _text(x, cap, f"{what}[{i + 1}]", bad, required=True)
        if s:
            out.append(s)
    return out


def validate(d, owner="you"):
    """The configuration as the board will keep it (every field present, trimmed), or a ConfigurationError listing what is wrong."""
    errs = []
    bad = errs.append
    if not isinstance(d, dict):
        raise ConfigurationError("a configuration is a JSON object with a name and roles")
    for k in sorted(set(d) - TOP_KEYS):
        bad(f"unknown key {k!r}")
    if d.get("configuration") != VERSION or isinstance(d.get("configuration"), bool):
        bad(f"configuration must be {VERSION} (the file format version)")
    name = _text(d.get("name"), 60, "name", bad, required=True)
    desc = _text(d.get("description"), 240, "description", bad)
    roles_in = d.get("roles")
    roles, seen_names, seen_roles = [], {}, set()
    if not isinstance(roles_in, list) or not roles_in:
        bad("roles must be a list with at least one role")
        roles_in = []
    if len(roles_in) > MAX_ROLES:
        bad(f"more than {MAX_ROLES} roles")
    for i, r in enumerate(roles_in[:MAX_ROLES]):
        at = f"role {i + 1}"
        if not isinstance(r, dict):
            bad(f"{at} must be an object")
            continue
        for k in sorted(set(r) - ROLE_KEYS):
            bad(f"{at}: unknown key {k!r}")
        role = _text(r.get("role"), 30, f"{at}: role", bad, required=True)
        at = f"role {role or i + 1}"
        if role and role.lower() in seen_roles:
            bad(f"{at} is listed twice")
        seen_roles.add(role.lower())
        names_in = r.get("names")
        names = []
        if not isinstance(names_in, list) or not names_in:
            bad(f"{at}: names must be a list with at least one name")
            names_in = []
        if len(names_in) > MAX_NAMES:
            bad(f"{at}: more than {MAX_NAMES} names")
        for n in names_in[:MAX_NAMES]:
            if not isinstance(n, str) or not rename.NAME_RE.match(n.strip()):
                bad(f"{at}: {str(n)[:20]!r} is not a name (1 to 40 letters, digits, space, dot, hyphen or underscore)")
                continue
            n = n.strip()
            k = rename.key(n)
            if k in rename.RESERVED or k == rename.key(owner):
                bad(f"{at}: {n} is a name the board keeps for itself")
            elif k in seen_names:
                bad(f"{at}: {n} is also the name of {seen_names[k]}")
            else:
                seen_names[k] = role or f"role {i + 1}"
                names.append(n)
        count = r.get("count")
        if count is not None and (isinstance(count, bool) or count != len(names_in)):
            bad(f"{at}: count must equal the number of names ({len(names_in)})")
        size = r.get("size")
        if size not in (None, "") and size not in SIZES:
            bad(f"{at}: size must be S, M or L")
        model = _text(r.get("model"), 30, f"{at}: model", bad)
        if model and not all(c.isalnum() or c in "._-" for c in model):
            bad(f"{at}: model is a short name such as sonnet")
        roles.append({"role": role, "names": names, "purpose": _text(r.get("purpose"), 200, f"{at}: purpose", bad),
                      "model": model, "size": size if size in SIZES else "",
                      "may": _list(r.get("may"), f"{at}: may", bad), "may_not": _list(r.get("may_not"), f"{at}: may_not", bad),
                      "tools": _list(r.get("tools"), f"{at}: tools", bad, cap=60), "count": len(names)})
    if errs:
        more = f" (and {len(errs) - MAX_ERRORS} more)" if len(errs) > MAX_ERRORS else ""
        raise ConfigurationError("not a valid configuration: " + "; ".join(errs[:MAX_ERRORS]) + more)
    return {"configuration": VERSION, "name": name, "description": desc, "roles": roles}


MAX_BYTES = 64_000


def loads(text, owner="you"):
    """Validate a configuration given as JSON text."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise ConfigurationError("not a valid configuration: the file is over 64 KB")
    try:
        d = json.loads(text)
    except ValueError as e:
        raise ConfigurationError(f"not a valid configuration: the file is not JSON ({e})") from e
    return validate(d, owner)


def builtin_names():
    return sorted(BUILTIN)


def builtin_list(owner="you"):
    """Every configuration that ships, in the board's order, each as {key, ...the validated configuration}: what the picker lists."""
    return [{"key": k, **builtin(k, owner)} for k in BUILTIN_ORDER]


def builtin(name, owner="you"):
    """A configuration that ships with the board, by name (`day-to-day`)."""
    k = str(name or "").strip().lower().replace(" ", "-")
    if k not in BUILTIN:
        raise ConfigurationError(f"no configuration named {name!r} that ships with the board. They are: {', '.join(builtin_names())}; or give the path of a file")
    return loads((BUILTIN_DIR / BUILTIN[k]).read_text(), owner)


def read_source(what, owner="you"):
    """A configuration from a shipped name or a file path (a path is read as text and validated; nothing else of it is used). A bare shipped name (build, day-to-day) is the
    shipped one even when a folder or a file of that name sits in the current directory (the board's own checkout has a build/ folder); a file is named with a .json ending or a path."""
    p = Path(str(what)).expanduser()
    bare = p.suffix.lower() != ".json" and not any(c in str(what) for c in "/\\~")
    if bare and str(what or "").strip().lower().replace(" ", "-") in BUILTIN:
        return builtin(what, owner), str(what)
    if p.suffix.lower() == ".json" or p.is_file():
        try:
            if p.stat().st_size > 64_000:
                raise ConfigurationError("not a valid configuration: the file is over 64 KB")
            return loads(p.read_text(), owner), str(p.name)
        except OSError as e:
            raise ConfigurationError(f"cannot read {what}: {e.__class__.__name__}") from e
    return builtin(what, owner), str(what)


# -- the setting and the applied copy --------------------------------------------------------------------------------

def enabled(board_dir):
    """Is [agents] configurations = true in the board's config.toml. Read fresh each time, so an edit shows up without a restart."""
    try:
        conf = tomlread.loads((Path(board_dir) / "config.toml").read_text())
    except (OSError, ValueError):
        return False
    sec = conf.get("agents")
    return isinstance(sec, dict) and sec.get("configurations") is True


def path(board_dir):
    return Path(board_dir) / FILE


def applied(board_dir):
    """The applied configuration (validated again on every read, so a hand-edited file is never trusted), else None. Not gated by the setting here:
    callers that act on it check `enabled` first (applied_if_enabled)."""
    d = statefile.load(path(board_dir), {})
    if not isinstance(d, dict) or not isinstance(d.get("configuration"), dict):
        return None
    try:
        return validate(d["configuration"])
    except ConfigurationError:
        return None


def applied_if_enabled(board_dir):
    return applied(board_dir) if enabled(board_dir) else None


def apply(board_dir, cfg, source, now=None):
    """Write `cfg` (already validated) as the applied configuration. Changes the roster and labels only."""
    now = now or datetime.now()
    statefile.write(path(board_dir), {"applied_at": now.strftime("%Y-%m-%dT%H:%M:%S"), "source": source, "configuration": cfg}, indent=2)
    return cfg


def clear(board_dir):
    """Remove the applied configuration (`agentboard configuration clear`); True if there was one."""
    try:
        path(board_dir).unlink()
        return True
    except FileNotFoundError:
        return False


# -- reading it ------------------------------------------------------------------------------------------------------

def roster(cfg):
    """Every default name in the configuration, in order."""
    return [n for r in (cfg or {}).get("roles", []) for n in r["names"]]


def role_of(cfg, name):
    """The role record for an agent name (case does not matter), with the configuration's name added, or None."""
    k = rename.key(name)
    for r in (cfg or {}).get("roles", []):
        for n in r["names"]:
            if rename.key(n) == k:
                return {**r, "configuration": cfg["name"], "name": n}
    return None


def merge(names, board_dir):
    """`names` (the explicit roster) plus the applied configuration's names, when the setting is on and one is applied; the explicit ones first, no name twice."""
    out = list(names)
    cfg = applied_if_enabled(board_dir)
    have = {rename.key(n) for n in out}
    for n in roster(cfg):
        if rename.key(n) not in have:
            out.append(n)
            have.add(rename.key(n))
    return out


def orch_section(cfg, owner="the owner"):
    """What ORCH is told about an applied configuration: the roles (name, purpose, what it may not do) and the one rule that matters."""
    lines = [f"Configuration: {cfg['name']}" + (f" ({cfg['description']})" if cfg["description"] else "")]
    for r in cfg["roles"]:
        lines.append(f"- {', '.join(r['names'])}: {r['role']}, {r['purpose']}" + (f". May not: {'; '.join(r['may_not'])}" if r["may_not"] else ""))
    if any(a in r["may_not"] for r in cfg["roles"] for a in OUTSIDE_ACTIONS):
        lines.append(f"Give each card to the agent whose role fits. A call, a message, a payment or a form is never done on an agent's own say: it is proposed to {owner} "
                     "(`chat send ... --propose`), approved for that one action, and lapses after 30 minutes.")
    return "\n".join(lines)


def roles_by_name(cfg):
    """{agent name: {role, purpose, may_not...}} for the page's role chips."""
    out = {}
    for r in (cfg or {}).get("roles", []):
        for n in r["names"]:
            out[n] = {"role": r["role"], "purpose": r["purpose"], "model": r["model"], "size": r["size"]}
    return out


def role_block(cfg, name, owner="the owner"):
    """The paragraph a card prompt gets for an agent that has a role (empty for one that has none): who it is here, what it may and may not do, and that an
    action outside the board waits for the owner's word, written as a proposal, one action at a time."""
    r = role_of(cfg, name)
    if r is None:
        return ""
    lines = [f"## Your role: {r['role']} ({r['configuration']})", ""]
    if r["purpose"]:
        lines.append(f"You are {r['name']}, the {r['role']}: {r['purpose']}.")
    if r["may"]:
        lines.append("You may: " + "; ".join(r["may"]) + ".")
    if r["may_not"]:
        lines.append("You may not, on your own: " + "; ".join(r["may_not"]) + ".")
    if r["tools"]:
        lines.append("Tools for this role: " + ", ".join(r["tools"]) + ".")
    if any(a in r["may_not"] for a in OUTSIDE_ACTIONS):
        lines.append(f"Anything that reaches outside the board (a call, a message, a payment, a form) is proposed to {owner} first: "
                     f"agentboard chat send \"<one line>\" --name {r['name']} --propose \"<the action>\" --outside --target \"<who or where>\" --say \"<the exact words>\" "
                     "--money \"<amount, or none>\" --shares \"<what of theirs is shared, or none>\" --card <id>; then ask on the card, so it waits on them: "
                     "agentboard ask <id> \"Waiting for your OK on the proposal\". Do it only after they approve that one action (agentboard chat approvals --name "
                     f"{r['name']}): an approval is for that action and nothing else, and it lapses after 30 minutes. Never reuse one for the next action.")
    return "\n".join(lines) + "\n"


def start_lines(cfg):
    """[(name, role, the two lines to type in that agent's terminal)] for `configuration show` and the apply screen."""
    out = []
    for r in cfg["roles"]:
        for n in r["names"]:
            out.append((n, r["role"], [f"/rename {n}", f"export AGENTBOARD_NAME={n}"]))
    return out


def detail(cfg):
    """A configuration as the picker shows it: the validated file plus the terminals the owner types (the board starts nothing)."""
    return {**cfg, "start": [{"name": n, "role": r, "lines": cmds} for n, r, cmds in start_lines(cfg)]}


def page_state(board_dir, owner="you"):
    """GET /api/configurations: is the setting on, what is applied, and what ships (each with its terminals). Off: only {"enabled": false}, so the page can say how to turn it on."""
    if not enabled(board_dir):
        return {"enabled": False}
    rec = statefile.load(path(board_dir), {})
    cur = applied(board_dir)
    return {"enabled": True,
            "applied": {"name": cur["name"], "source": str(rec.get("source", ""))[:80], "at": str(rec.get("applied_at", ""))[:19], **detail(cur)} if cur else None,
            "builtin": [{"key": c["key"], **detail({k: v for k, v in c.items() if k != "key"})} for c in builtin_list(owner)]}


def export_text(cfg):
    """The configuration as the file the owner can share: the validated fields only (never a card, a line of chat or a path), indented JSON."""
    keep = {k: cfg[k] for k in ("configuration", "name", "description", "roles")}
    return json.dumps(keep, indent=2) + "\n"


def filename(cfg):
    """A safe file name for an exported configuration: the name in lower case with hyphens."""
    slug = "".join(c if c.isalnum() else "-" for c in cfg["name"].lower()).strip("-")
    return (slug[:40].strip("-") or "configuration") + ".json"


def describe(cfg, source=None, applied_now=False):
    """The configuration as lines for the terminal: the roles, what each may and may not do, and the terminals to start (the owner types them)."""
    head = f"{'Applied' if applied_now else 'Configuration'}: {cfg['name']}" + (f" ({source})" if source else "")
    out = [head]
    if cfg["description"]:
        out.append(f"  {cfg['description']}")
    out.append("")
    for r in cfg["roles"]:
        adv = " · ".join(x for x in (r["model"], r["size"]) if x)
        out.append(f"  {r['role']}: {', '.join(r['names'])}" + (f"  [{adv}]" if adv else ""))
        if r["purpose"]:
            out.append(f"      {r['purpose']}")
        if r["may"]:
            out.append(f"      may: {'; '.join(r['may'])}")
        if r["may_not"]:
            out.append(f"      may not: {'; '.join(r['may_not'])}")
        if r["tools"]:
            out.append(f"      tools to leave enabled in that terminal: {', '.join(r['tools'])}")
    out += ["", "The board starts nothing. In a new terminal for each agent, type:"]
    for n, role, cmds in start_lines(cfg):
        out.append(f"  {n} ({role}): {cmds[0]}   then   {cmds[1]}")
    return out
