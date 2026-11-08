"""The work profile: one switch that makes the board provably safe on a managed PC.

    agentboard profile work          # this machine, every board, every shell: writes ~/.config/agentboard/profile (mode 0600)
    export AGENTBOARD_PROFILE=work   # this shell and what it starts
    [board] profile = "work"         # in a board's config.toml (agentboard init --profile work writes it)

Any one of the three turns it on, and none can turn another off: a copied config.toml can add the profile but never remove it. A value
other than a plain "off" word means work (fail closed: a typo is a lock, never a hole). What it does, all of it enforced again at run time
by the guards (guards.py) and proved by `agentboard selfcheck`:

  - the master lock (AGENTBOARD_LOCKDOWN=1): no claude rounds, no run, no command/http providers, no sync copy, no voice, no spawn
  - plugins refused (AGENTBOARD_NO_PLUGINS=1), whatever the environment says about them
  - no outbound connection and no name lookup of anything but this machine, for every command (network guard); listening only on loopback
  - in `agentboard serve`: no program is ever started (process guard), no browser is opened, no chat rounds run, git is not asked for the
    "commits made" line on a finished card
  - private file modes (the umask and the 0700/0600 modes the board already keeps)

The effect is set once, early, in this process: the environment it exports is inherited by anything started later, so a nested agentboard
is under it too.
"""
import os
from pathlib import Path

from . import guards, lockdown

ENV = "AGENTBOARD_PROFILE"
WORK = "work"
_OFF = ("", "0", "false", "no", "off", "home")
_NET = []   # the network guard, once installed (a second apply does not stack a second one)
_PROC = []
_ENV0 = {"seen": False, "value": None}   # what the SHELL put in $AGENTBOARD_PROFILE, noted before apply() writes its own work into the environment


def machine_file():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agentboard" / "profile"


def _word_is_work(value):
    return str(value or "").strip().lower() not in _OFF


def sources(board_dir=None):
    """[(where, text)] for every source that says work, strongest first. Never raises."""
    out = []
    v = _ENV0["value"] if _ENV0["seen"] else os.environ.get(ENV)   # (apply() sets the variable for what it starts; that is not the shell's word)
    if v is not None and _word_is_work(v):
        out.append(("environment", f"${ENV}={v.strip()[:20]}"))
    try:
        txt = machine_file().read_text(errors="replace")
        if _word_is_work(txt.split("#", 1)[0]):
            out.append(("machine", f"{machine_file()}"))
    except OSError:
        pass
    if board_dir:
        try:
            from . import prompt as promptlib   # (prompt imports the lock modules; imported here to keep this module light)
            board = promptlib.load_config(board_dir).get("board")
            if isinstance(board, dict) and "profile" in board and _word_is_work(board.get("profile")):
                out.append(("board", f"[board] profile in {Path(board_dir) / 'config.toml'}"))
        except Exception:   # noqa: BLE001  (a config that cannot be read must not switch the profile OFF or crash a start: the other sources stand)
            pass
    return out


def reason(board_dir=None):
    s = sources(board_dir)
    return f"{s[0][0]}: {s[0][1]}" if s else None


def in_effect():
    """True once apply() has run in this process (or the environment says so): a cheap test for code that must behave differently."""
    return bool(_NET) or _word_is_work(os.environ.get(ENV))


def find_board():
    try:
        from .store import find_dir
        return find_dir()
    except Exception:   # noqa: BLE001  (no board here: the machine and the environment still count)
        return None


def apply(board_dir=None):
    """Turn the profile on for this process when any source says so. Returns the reason, or None when it is off. Idempotent."""
    why = reason(board_dir if board_dir is not None else find_board())
    if why is None:
        return None
    if not _ENV0["seen"]:   # note what the shell itself said before this process writes its own work into the variable (for what it starts)
        _ENV0.update(seen=True, value=os.environ.get(ENV))
    os.environ[ENV] = WORK
    os.environ[lockdown.ENV] = "1"
    os.environ["AGENTBOARD_NO_PLUGINS"] = "1"
    if not _NET:
        _NET.append(guards.network_guard())
    return why


def apply_server():
    """What `agentboard serve` adds: no program may be started at all."""
    if in_effect() and not _PROC:
        _PROC.append(guards.process_guard())
    return bool(_PROC)


def reset():   # tests only: take the guards off again
    for g in _NET + _PROC:
        g.uninstall()
    _NET.clear()
    _PROC.clear()
    _ENV0.update(seen=False, value=None)


# -- is this a machine that looks like the owner's own (a home Mac), or a fresh install on a managed PC? ----------------------------------------------
INIT_ENV = "AGENTBOARD_INIT_PROFILE"   # work | home | auto: what `agentboard init` writes when the command line does not say
CORE_ENV = {"AGENTBOARD_PROFILE", INIT_ENV, "AGENTBOARD_ORIG_UMASK", "AGENTBOARD_TRANSCRIPT", "AGENTBOARD_RUN", "AGENTBOARD_MIC", "AGENTBOARD_COLOR", "AGENTBOARD_PRIVATE_WORDS"}   # plus configschema.ENV
HOME_FILES = ("home.env", "facts-never.txt")   # in ~/.config/agentboard: the home setup's own files


def core_env():
    """The AGENTBOARD_ variables this program itself defines (configschema.ENV and the few below it): none of them says 'home setup'."""
    from . import configschema
    return set(configschema.ENV) | CORE_ENV


def home_signals():
    """What on this machine says 'home setup': the NAMES of things, never a value. A home plugin installed (read from package metadata; nothing is imported
    or run), an AGENTBOARD_ variable set that this program does not define itself (AGENTBOARD_PLUGINS=1 or anything a plugin adds), or the home setup's own files in ~/.config/agentboard.
    Empty on a fresh install on a managed PC."""
    out = []
    try:
        from importlib.metadata import entry_points
        from . import plugins
        out += [f"plugin {ep.name} is installed" for ep in entry_points(group=plugins.GROUP)]
    except Exception:   # noqa: BLE001  (metadata that cannot be read says nothing: the other signals still count)
        pass
    core = core_env()
    for k, v in sorted(os.environ.items()):   # an AGENTBOARD_ variable this program does not define belongs to something added on top of it: a home setup
        if k.startswith("AGENTBOARD_") and v.strip() and k not in core and not k.startswith("AGENTBOARD_NO_"):
            out.append(f"${k} is set")
        elif k == "AGENTBOARD_PLUGINS" and _word_is_work(v):
            out.append(f"${k} is set")
    for name in HOME_FILES:
        try:
            if (machine_file().parent / name).exists():
                out.append(f"{machine_file().parent / name} exists")
        except OSError:
            pass
    return out


def init_choice(flag=None, real_cli=False):
    """('work' | 'home' | 'auto', why) for `agentboard init`: the flag, else $AGENTBOARD_INIT_PROFILE, else 'auto' on the real command line and 'home' (the
    plain board) when called from code such as a test. An unknown word is 'auto': a typo never switches the profile off for a managed PC."""
    for src, v in (("--profile", flag), (f"${INIT_ENV}", os.environ.get(INIT_ENV))):
        w = str(v or "").strip().lower()
        if w in ("work", "home", "auto"):
            return w, src
        if w:
            return "auto", f"{src} (unknown word {w[:20]!r})"
    return ("auto", "default") if real_cli else ("home", "default for a call from code")


def set_machine(on):
    """Write (or remove) the machine-wide switch. Returns the path."""
    p = machine_file()
    if on:
        p.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            p.write_text("work\n")
            os.chmod(p, 0o600)
        finally:
            os.umask(old)
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    return p


def describe():
    """The lines `agentboard profile` prints under the switch: what it does."""
    return [
        "master lock on (no claude rounds, run, command or http providers, sync copy, voice or spawn)",
        "plugins refused",
        "no outbound connection and no name lookup of anything but this machine, in every command",
        "listening only on loopback; in serve no program is started and no browser opened",
        "private file modes",
        "prove it: agentboard selfcheck",
    ]
