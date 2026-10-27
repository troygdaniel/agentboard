"""Named boards: a small registry in ~/.agentboard/boards.toml (override the folder with AGENTBOARD_HOME).

    current = "work"                       # `agentboard board use work`: the board used when the folder has none
    [boards.work]
    path = "/Users/me/.agentboard/boards/work/.agentboard"
    color = "blue"                         # optional: tints the board's header

The board of the folder you are in is still the default; the registry only names the others."""
import json
import os
import re
import tempfile
from pathlib import Path

from .store import DIR_NAME, BoardError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def home():
    return Path(os.environ.get("AGENTBOARD_HOME") or Path.home() / ".agentboard").expanduser()


def registry_path():
    return home() / "boards.toml"


def check_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BoardError("a board name is 1-40 lowercase letters, digits, - or _, starting with a letter or digit")
    return name


def load():
    """{'current': name|None, 'boards': {name: {'path': str, 'color': str|None}}}. A missing or unreadable file is an empty registry."""
    try:
        import tomllib

        raw = tomllib.loads(registry_path().read_text())
    except OSError:
        raw = {}
    except ValueError as e:
        raise BoardError(f"{registry_path()} is not valid TOML ({e})") from e
    boards = {}
    for name, b in (raw.get("boards") or {}).items():
        if NAME_RE.match(name) and isinstance(b, dict) and isinstance(b.get("path"), str) and b["path"].strip():
            boards[name] = {"path": b["path"], "color": b.get("color") if isinstance(b.get("color"), str) else None}
    cur = raw.get("current")
    return {"current": cur if cur in boards else None, "boards": boards}


def _q(s):
    return json.dumps(s, ensure_ascii=False)   # a JSON string is a valid TOML basic string


def save(reg):
    lines = []
    if reg.get("current"):
        lines.append(f"current = {_q(reg['current'])}")
    for name, b in sorted(reg["boards"].items()):
        lines += ["", f"[boards.{name}]", f"path = {_q(b['path'])}"]
        if b.get("color"):
            lines.append(f"color = {_q(b['color'])}")
    text = "\n".join(lines).lstrip("\n") + "\n"
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".boards-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def path_of(name):
    """The board folder registered under `name`."""
    check_name(name)
    b = load()["boards"].get(name)
    if not b:
        known = ", ".join(sorted(load()["boards"])) or "none yet"
        raise BoardError(f"no board named {name!r} (registered: {known}); create one with `agentboard board new {name}`")
    return Path(b["path"]).expanduser()


def current_dir():
    """The folder of the board chosen with `board use`, or None."""
    reg = load()
    return Path(reg["boards"][reg["current"]]["path"]).expanduser() if reg["current"] else None


def register(name, path, color=None, replace=False):
    check_name(name)
    reg = load()
    if name in reg["boards"] and not replace:
        raise BoardError(f"a board named {name!r} already exists ({reg['boards'][name]['path']})")
    reg["boards"][name] = {"path": str(Path(path).expanduser().resolve()), "color": color or None}
    save(reg)


def new(name, path=None, color=None):
    """Create the board folder (default ~/.agentboard/boards/<name>/.agentboard, so backup copies are named after the board) and register it."""
    check_name(name)
    target = Path(path).expanduser().resolve() if path else home() / "boards" / name / DIR_NAME
    register(name, target, color)
    target.mkdir(parents=True, exist_ok=True)
    tasks = target / "tasks.json"
    if not tasks.exists() or not tasks.read_text().strip():
        tasks.write_text('{"tasks": []}')
    return target


def use(name):
    path_of(name)
    reg = load()
    reg["current"] = name
    save(reg)


def remove(name):
    """Forget a board (its folder and cards are left alone)."""
    check_name(name)
    reg = load()
    if name not in reg["boards"]:
        raise BoardError(f"no board named {name!r}")
    del reg["boards"][name]
    if reg["current"] == name:
        reg["current"] = None
    save(reg)


def name_for(board_dir):
    """The registered name of a board folder, or None."""
    want = Path(board_dir).expanduser().resolve()
    for name, b in load()["boards"].items():
        if Path(b["path"]).expanduser().resolve() == want:
            return name
    return None
