"""agentboard doctor: a read-only check a person (or a company reviewer) can run on the machine and paste into a review.

It changes nothing and opens no socket of its own: it reads files, and asks the system with `ps`, `lsof` and `git` (read-only commands).
Every line is PASS, WARN, FAIL or INFO. FAIL means a claim the board makes is not true on this machine; WARN means something worth a look
(often "a lock is not set"); INFO is just what is there. It never prints a secret: where it finds something key-shaped it says the kind,
the file and the line, not the text. It names no feature of the board: lock variables and network-capable modules are found by reading
the installed package, so it stays right when a feature moves out into a plugin. With plugins ON (the machine's key, no lock) it also
loads them exactly as `agentboard serve` would, says which failed (by error class), and prints each plugin's own checks as <plugin>:<name>
lines (masked, one line each); with plugins off or locked, nothing is imported.

    agentboard doctor [--project DIR] [--strict]      exit 1 on any FAIL (with --strict, on any WARN too)
"""
import importlib.metadata
import os
import re
import stat
import subprocess
from pathlib import Path

from . import __version__, lockdown
from . import prompt as promptlib
from . import plugins, providers, redact, repoguard, serverstate, untrusted
from . import profile as profilelib
from .store import BoardError

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
LEVELS = (PASS, WARN, FAIL, INFO)
PLUGIN_LINE_MAX = 400     # a plugin's doctor line is cut here (after masking)
PLUGIN_LINES_MAX = 40     # lines one plugin may add
TIMEOUT_S = 10
MAX_FILES = 3000          # tracked files scanned for key-shaped strings
MAX_SHOWN = 5             # hits listed before "and N more"
CORE_OUTBOUND = {"providers"}   # the modules of the core that may open an outbound connection (a URL you write in config.toml)
AUDIT_ONLY = {"guards", "selfcheck"}   # they refuse outside connections / talk to a throwaway loopback server (work profile: `agentboard selfcheck`)

_HERE = Path(__file__).resolve().parent

NETWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:urllib\.request|urllib3|http\.client|socket|ssl|smtplib|ftplib|requests|httpx|aiohttp|websocket)\b", re.M)
SERVER_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:http\.server|socketserver|asyncio)\b", re.M)


def _res(level, name, text):
    return (level, name, text)


def _run_rc(runner, argv):
    """(exit code, stdout) of a read-only command, or (None, "") when it is missing or slow."""
    try:
        p = runner(argv, capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL,
                   env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return p.returncode, p.stdout


def _run(runner, argv):
    """stdout of a read-only command, or None when it is missing, slow or exits non-zero."""
    rc, out = _run_rc(runner, argv)
    return out if rc == 0 else None


def _host(name):
    """The host part of an lsof name like 127.0.0.1:8765, [::1]:8765 or *:8765."""
    return name.rsplit(":", 1)[0].strip("[]")


def _env_on(env, name):
    """Is a hard-off variable on in this environment (lockdown.env_on: the one rule every lock, the plugin gate and this report use)."""
    return lockdown.env_on(name, env)


def _short(path):
    p = str(path)
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home + os.sep) else p


def _is_loopback(host):
    return host in ("localhost", "::1", "[::1]") or host.startswith("127.")


# -- the checks -----------------------------------------------------------------------------------------------------------------
def check_version(runner):
    try:
        dist = importlib.metadata.version("agentboard")
    except importlib.metadata.PackageNotFoundError:
        dist = ""
    commit = ""
    try:
        d = importlib.metadata.distribution("agentboard")
        raw = d.read_text("direct_url.json")
        if raw:
            import json
            info = json.loads(raw)
            commit = (info.get("vcs_info") or {}).get("commit_id", "")[:10]
            url = str(info.get("url", ""))
            if not commit and url.startswith("file://"):
                folder = url[len("file://"):]
                head = (_run(runner, ["git", "-C", folder, "rev-parse", "--short", "HEAD"]) or "").strip()
                dirty = bool((_run(runner, ["git", "-C", folder, "status", "--porcelain", "--untracked-files=no"]) or "").strip()) if head else False
                commit = f"{head}{'+uncommitted' if dirty else ''} (installed from {_short(folder)})" if head else f"(installed from {_short(folder)})"
    except Exception:   # noqa: BLE001  (a missing or odd install record is just "unknown")
        pass
    out = [_res(INFO, "version", f"agentboard {dist or __version__}, commit {commit or 'unknown'}")]
    if dist and dist != __version__:
        out.append(_res(WARN, "version", f"the code says {__version__} but the installed package says {dist}: reinstall, or ask for the version to be synced"))
    return out


def check_locks(env, board_dir=None):
    source = "\n".join(p.read_text(errors="ignore") for p in sorted(_HERE.glob("*.py")) if p.name != "doctor.py")
    names = sorted(set(re.findall(r"AGENTBOARD_NO_[A-Z]+", source)) | {lockdown.ENV})

    def on(name):
        return _env_on(env, name)
    out = []
    if on(lockdown.ENV):
        out.append(_res(PASS, "lock", f"{lockdown.ENV} is on in this shell: chat rounds, one-shot runs, command and http providers, the backup copy, voice and spawn are refused"))
    else:
        out.append(_res(WARN, "lock", f"{lockdown.ENV} is not set in this shell; on a work laptop set it to 1 (it stops everything that starts a program or sends data out)"))
    others = [f"{n} {'on' if on(n) else 'off'}" for n in names if n != lockdown.ENV]
    if others:
        out.append(_res(INFO, "lock", "narrow locks: " + ", ".join(others)))
    why = profilelib.reason(board_dir)
    out.append(_res(PASS, "profile", f"the work profile is on ({why}); `agentboard selfcheck` proves it") if why
                 else _res(INFO, "profile", "the work profile is not on; `agentboard profile work` turns on the lock, loopback-only networking and no program starts (then `agentboard selfcheck`)"))
    return out


def check_plugins():
    """Is any plugin code allowed to run here, and which packages could run? Reads the gate (plugins.disabled_reason) and the entry-point
    NAMES from package metadata: nothing is imported, loaded or run, so this is safe to run on a locked machine."""
    from importlib.metadata import entry_points
    try:
        eps = sorted({(ep.name, str(ep.value).split(":")[0]) for ep in entry_points(group=plugins.GROUP)})
    except Exception:   # noqa: BLE001  (odd package metadata is "could not list", never a crash)
        eps = None
    named = ", ".join(f"{n} ({m})" for n, m in eps) if eps else ""
    why = plugins.disabled_reason()
    if why is None:
        if eps is None:
            return [_res(WARN, "plugins", "plugins are ON (the key is set, no lock) but the installed ones could not be listed")]
        if not eps:
            return [_res(INFO, "plugins", f"plugins are allowed (${plugins.ENV}=1, no lock) but none are installed")]
        return [_res(WARN, "plugins", f"plugins are ON (${plugins.ENV}=1, no lock): code from {named} runs inside agentboard, with the same access as the board")]
    tail = f"; installed but not loaded: {named}" if eps else ("; none are installed" if eps == [] else "")
    return [_res(PASS, "plugins", f"plugins are {why}: nothing is looked up, imported or run{tail}")]


def check_plugin_load(board_dir):
    """With plugins ON, load them the way `agentboard serve` does and say which loaded and which failed (by error class only), then run
    each loaded plugin's own doctor checks (api.add_doctor). With plugins off or locked nothing is imported: check_plugins has said so.

    A plugin's lines are its own claims about its own setup; the core only shapes them: the level must be one of ours, the name becomes
    <plugin>:<name>, the text is one line with nothing invisible, secret-masked and cut, and a check that raises or returns the wrong
    shape is one FAIL line naming the class. Loading a plugin runs its register() (code you installed and switched on), nothing more."""
    if not plugins.enabled():
        return []
    out = []
    try:
        loaded = plugins.load()
    except Exception as e:   # noqa: BLE001  (listing or loading must never crash the report)
        return [_res(FAIL, "plugin", f"plugins could not be loaded: {e.__class__.__name__}")]
    for name, cls in plugins.failed():
        out.append(_res(FAIL, "plugin", f"plugin {name or '?'} failed to load: {cls} (the same load `agentboard serve` does; the board runs without it). "
                                        f"Reinstall it, then: python3 -c 'from importlib.metadata import entry_points as e; [x.load() for x in e(group=\"{plugins.GROUP}\")]'"))
    for name in loaded:
        out.append(_res(PASS, "plugin", f"plugin {name} loads (the same load `agentboard serve` does)"))
    conf = redact.settings(board_dir)
    for pname, fn in plugins.doctor_checks():
        try:
            lines = list(fn(Path(board_dir)))
        except Exception as e:   # noqa: BLE001  (a plugin's check must never stop the report; only its class name is kept)
            out.append(_res(FAIL, pname, f"its doctor check raised {e.__class__.__name__}"))
            continue
        for item in lines[:PLUGIN_LINES_MAX]:
            out.append(_plugin_line(pname, item, board_dir, conf))
        if len(lines) > PLUGIN_LINES_MAX:
            out.append(_res(INFO, pname, f"and {len(lines) - PLUGIN_LINES_MAX} more line(s) not shown"))
    return out


def _plugin_line(pname, item, board_dir, conf):
    """One (level, name, text) from a plugin, shaped for the report: a bad shape is a FAIL that says so, never a crash."""
    if not (isinstance(item, (tuple, list)) and len(item) == 3 and item[0] in LEVELS and isinstance(item[1], str) and isinstance(item[2], str)):
        return _res(FAIL, pname, "its doctor check returned a line that is not (level, name, text)")
    level, name, text = item
    name = re.sub(r"[^a-z0-9_-]", "", name.lower())[:24] or "check"
    text = " ".join(untrusted.text_lines(text)).strip()
    text = redact.scrub(text, board_dir, conf=conf, bound=2 * PLUGIN_LINE_MAX)
    return _res(level, f"{pname}:{name}", text[:PLUGIN_LINE_MAX] or "(no text)")


def _board_pids(runner):
    text = _run(runner, ["ps", "-axo", "pid=,command="])
    if text is None:
        return None
    mine = os.getpid()
    pids = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if not m or int(m.group(1)) == mine:
            continue
        cmd = m.group(2)
        if (re.search(r"(?:^|[\s/])agentboard(?:\s|$)|-m agentboard\b", cmd) and re.search(r"\bserve\b", cmd)
                and not re.search(r"\b(?:doctor|ps|lsof|grep|pgrep)\b", cmd)):
            pids.append(m.group(1))
    return pids


def _lsof(runner, pids, extra):
    text = _run(runner, ["lsof", "-nP", "-a", "-p", ",".join(pids), *extra, "-Fpn"])
    return text.splitlines() if text is not None else None


def check_listeners(runner, pids=None):
    pids = _board_pids(runner) if pids is None else pids
    if pids is None:
        return [_res(INFO, "listeners", "could not list processes (ps), so running servers were not checked")]
    if not pids:
        return [_res(INFO, "listeners", "no agentboard server is running now, so there is nothing to check; run doctor again while it runs")]
    listen = _lsof(runner, pids, ["-iTCP", "-sTCP:LISTEN"])
    conns = _lsof(runner, pids, ["-i"])
    if listen is None or conns is None:
        return [_res(INFO, "listeners", f"{len(pids)} server(s) running but lsof is not available here, so ports were not checked")]
    names = [l[1:] for l in listen if l.startswith("n")]
    outside = [n for n in names if not _is_loopback(_host(n))]
    out = []
    if not names:
        out.append(_res(INFO, "listeners", f"{len(pids)} server(s) running, none listening"))
    elif outside:
        out.append(_res(FAIL, "listeners", "listening beyond this machine: " + ", ".join(sorted(set(outside)))))
    else:
        out.append(_res(PASS, "listeners", f"{len(set(names))} listener(s), all loopback only: " + ", ".join(sorted(set(names)))))
    remote = []
    for n in (l[1:] for l in conns if l.startswith("n")):
        if "->" in n:
            if not _is_loopback(_host(n.split("->", 1)[1])):
                remote.append(n.split("->", 1)[1])
    if remote:
        out.append(_res(FAIL, "connections", f"{len(remote)} connection(s) to other machines: " + ", ".join(sorted(set(remote))[:MAX_SHOWN])))
    else:
        out.append(_res(PASS, "connections", "no open connection to another machine"))
    return out


def check_servers(board_dir, pids, shell_locked):
    """(results, locked): what each RUNNING server on this board says it was started with (server-<pid>.json, see serverstate.py) against
    this shell. `locked` is True only when this shell has the lock AND every server that recorded its state does too, so a later PASS never
    rests on the doctor's own environment alone."""
    if not pids:
        return [], shell_locked
    states = {pid: serverstate.read(board_dir, int(pid)) for pid in pids}
    known = {pid: s for pid, s in states.items() if s}
    if not known:
        return [_res(INFO, "server", f"{len(pids)} agentboard server(s) running but none recorded how it was started for this board "
                                     f"(an older build, or another board): restart the board's server to have its lock state checked")], shell_locked
    out, locked = [], shell_locked
    for pid, s in sorted(known.items(), key=lambda kv: int(kv[0])):
        who = f"server pid {pid}" + (f" (port {s['port']})" if s["port"] else "")
        plugins_on = s["plugins_open"]
        extra = f"; plugins ON: {', '.join(s['plugins_loaded']) or 'allowed'}" if plugins_on else ""
        if s["lockdown"] and not plugins_on:
            out.append(_res(PASS, "server", f"{who} was started with {lockdown.ENV} on and plugins closed" + (", under the work profile (no outside connection, no program started)" if s.get("profile") else "")))
        elif shell_locked and not s["lockdown"]:
            out.append(_res(WARN, "server", f"{who} was started WITHOUT {lockdown.ENV} although this shell has it on{extra}; restart it from a shell that has it"))
        elif plugins_on:
            out.append(_res(WARN, "server", f"{who} was started with plugins ON ({', '.join(s['plugins_loaded']) or 'allowed'}){'' if s['lockdown'] else f'; {lockdown.ENV} is off'}"))
        else:
            out.append(_res(INFO, "server", f"{who} was started without {lockdown.ENV}; plugins closed"))
        locked = locked and s["lockdown"]
    return out, locked


def check_files(board_dir):
    if not board_dir.is_dir():
        return [_res(INFO, "files", f"{_short(board_dir)} does not exist")]
    other, group, total = [], [], 0
    for root, dirs, files in os.walk(board_dir, followlinks=False):
        for name in files + dirs:
            try:
                mode = os.lstat(os.path.join(root, name)).st_mode
            except OSError:
                continue
            if stat.S_ISLNK(mode):
                continue   # a link's own mode means nothing: what matters is what it points at, and that is not ours to read
            total += 1
            if mode & 0o004:
                other.append(name)
            elif mode & 0o040:
                group.append(name)
    try:
        top = board_dir.stat().st_mode & 0o777
    except OSError:
        top = 0
    fix = f"fix: chmod -R go-rwx {_short(board_dir)}"
    if total == 0:
        return [_res(PASS, "files", f"the board folder is empty (mode {top:03o}): nothing in it to read")]
    if other:
        return [_res(FAIL, "files", f"{len(other)} of {total} entries in the board folder (mode {top:03o}) can be read by any user on this machine; {fix}")]
    if top & 0o004:
        return [_res(FAIL, "files", f"the board folder (mode {top:03o}) can be listed by any user on this machine, so the names inside it show (report files carry card titles); the {total} entries are not readable by others; {fix}")]
    if group:
        return [_res(WARN, "files", f"{len(group)} of {total} entries in the board folder (mode {top:03o}) are readable by the group; {fix}")]
    if top & 0o040:
        return [_res(WARN, "files", f"the board folder (mode {top:03o}) can be listed by its group, so the names inside it show; the {total} entries are not readable by it; {fix}")]
    return [_res(PASS, "files", f"{total} entries in the board folder (mode {top:03o}) are private to you")]


def check_watchdog(board_dir):
    """The agent protocol's watchdog: WARN with the counts when the board is stuck somewhere between agents (a stale claim, a vanished
    agent, twins, a split card, an orphan, two sessions under one name), PASS when it is not; INFO when there is no board."""
    from . import watchdog
    from .store import Store
    if not Path(board_dir).is_dir():
        return [_res(INFO, "watchdog", "no board here: nothing to watch")]
    try:
        items = watchdog.findings(Store(board_dir))
    except Exception as e:   # a broken board is verify's business, not this line's
        return [_res(WARN, "watchdog", f"could not read the board: {e.__class__.__name__}")]
    if items:
        return [_res(WARN, "watchdog", f"{watchdog.summary(items)}: run `agentboard watchdog` for the list and the fixes")]
    return [_res(PASS, "watchdog", watchdog.summary(items))]


def _installed_record():
    """The install record of the running copy, or None."""
    try:
        return importlib.metadata.distribution("agentboard")
    except importlib.metadata.PackageNotFoundError:
        return None


def _package_files(folder):
    """The package's files as relative paths, without caches."""
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def check_install(here=None, dist="unset"):
    """Is the installed copy made of the same files as the source it was installed from? A file the source no longer has but the installed
    copy still carries (two removed modules once lingered in site-packages from a stale build/ folder) is code that still runs after
    it was removed from the repo. Reads two folders; runs nothing."""
    here = Path(here) if here else _HERE
    dist = _installed_record() if dist == "unset" else dist
    raw = None
    try:
        raw = dist.read_text("direct_url.json") if dist else None
    except Exception:   # noqa: BLE001  (an odd record is just "unknown")
        pass
    folder = ""
    if raw:
        try:
            import json
            url = str(json.loads(raw).get("url", ""))
            folder = url[len("file://"):] if url.startswith("file://") else ""
        except ValueError:
            folder = ""
    if not folder:
        return [_res(INFO, "install", "no record of which folder this copy was installed from, so it cannot be compared with a source")]
    source = Path(folder) / "src" / "agentboard"
    if not source.is_dir():
        return [_res(INFO, "install", f"installed from {_short(folder)}, which has no src/agentboard any more: nothing to compare with")]
    if source.resolve() == here.resolve():
        return [_res(PASS, "install", f"running from the source itself ({_short(folder)})")]
    stale = sorted(_package_files(here) - _package_files(source))
    if stale:
        shown = ", ".join(stale[:MAX_SHOWN]) + (f" and {len(stale) - MAX_SHOWN} more" if len(stale) > MAX_SHOWN else "")
        return [_res(WARN, "install", f"stale install: {shown} {'is' if len(stale) == 1 else 'are'} in the installed copy but not in the source ({_short(folder)}); "
                                      f"fix: pipx uninstall agentboard; rm -rf {_short(folder)}/build; pipx install {_short(folder)}")]   # build/ first: it is where the stale files come from
    return [_res(PASS, "install", f"the installed copy has no file its source ({_short(folder)}) lacks")]


def check_git(project, board_dir, runner):
    inside = _run(runner, ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"])
    if not inside or inside.strip() != "true":
        return [_res(INFO, "git", f"{_short(project)} is not inside a git repository: nothing is tracked, so nothing to scan")]
    try:
        rel = str(board_dir.resolve().relative_to(Path(project).resolve()))
    except ValueError:
        rel = None
    out = []
    if rel:
        tracked = [l for l in (_run(runner, ["git", "-C", str(project), "ls-files", "--", rel]) or "").splitlines() if l]
        ignored = _run_rc(runner, ["git", "-C", str(project), "check-ignore", "-q", "--", rel])[0] == 0   # 0 ignored, 1 not ignored
        if tracked:
            out.append(_res(FAIL, "board in git", f"{len(tracked)} file(s) of {rel}/ are tracked by git (cards, chat and replies are private): git rm -r --cached {rel}"))
        elif ignored:
            out.append(_res(PASS, "board in git", f"{rel}/ is ignored by git and nothing of it is tracked"))
        else:
            out.append(_res(WARN, "board in git", f"{rel}/ is not ignored by git; add it to .gitignore before a git add ."))
    listing = _run(runner, ["git", "-C", str(project), "ls-files", "-z"]) or ""
    files = [f for f in listing.split("\0") if f and not (rel and (f == rel or f.startswith(rel + "/")))]
    hits, scanned = [], 0
    words = repoguard.private_words()   # the owner's own words, from the file outside the repo (none: that check is skipped, as in publiccheck)
    for f in files[:MAX_FILES]:
        text = repoguard.readable(Path(project) / f)
        if text is None:
            continue
        scanned += 1
        for n, kind, _sample in repoguard.scan_text(text, words):   # the SAME shapes and allow rules as tests/publiccheck.py: one source
            hits.append((FAIL if repoguard.certain(kind) else WARN, kind, f, n))
    note = f" ({len(files) - MAX_FILES} more not scanned)" if len(files) > MAX_FILES else ""
    if not hits:
        out.append(_res(PASS, "tracked files", f"{scanned} tracked file(s) scanned: no key-shaped string, phone number, email, home path or private word (the rules of tests/publiccheck.py){note}"))
    else:
        level = FAIL if any(h[0] == FAIL for h in hits) else WARN
        shown = "; ".join(f"{kind} at {f}:{n}" for _l, kind, f, n in sorted(hits, key=lambda h: (h[0] != FAIL, h[2], h[3]))[:MAX_SHOWN])
        more = f"; and {len(hits) - MAX_SHOWN} more" if len(hits) > MAX_SHOWN else ""
        out.append(_res(level, "tracked files", f"{len(hits)} possible secret(s) or private value(s) in {scanned} tracked file(s): {shown}{more} (the text is not printed; "
                                                f"python3 tests/publiccheck.py lists them all){note}"))
    return out


def check_hooks(project):
    import json
    home = Path.home()
    out = []
    for p in (home / ".claude" / "settings.json", home / ".claude" / "settings.local.json",
              Path(project) / ".claude" / "settings.json", Path(project) / ".claude" / "settings.local.json"):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            out.append(_res(WARN, "hooks", f"{_short(p)} is not valid JSON, so its hooks could not be listed"))
            continue
        items, bare = [], False
        for event, entries in ((data.get("hooks") if isinstance(data, dict) else None) or {}).items():
            for entry in entries if isinstance(entries, list) else []:
                for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
                    cmd = " ".join(str(h.get("command", "")).split()) if isinstance(h, dict) else ""
                    items.append(f"{event}[{entry.get('matcher', '*')}] {cmd[:70]}{'…' if len(cmd) > 70 else ''}")
                    if cmd.split(" ", 1)[0] == "agentboard":
                        bare = True
        out.append(_res(INFO, "hooks", f"{_short(p)}: " + ("; ".join(items) if items else "no hooks")))
        if bare:
            out.append(_res(WARN, "hooks", f"a hook in {_short(p)} runs agentboard by name through PATH; run agentboard hooks install again to write its full path"))
    if not out:
        out.append(_res(INFO, "hooks", "no Claude Code settings file with hooks found (~/.claude or the project)"))
    return out


def check_stop_hook(project):
    """One line on the Stop hook (the one that keeps a session from going quiet on an unread board line): where it is installed and
    whether the board folder it names exists; WARN when it is nowhere or names no board."""
    from . import hooks
    found = hooks.stop_hook_state(project)
    if not found:
        return [_res(WARN, "Stop hook", "not installed: run agentboard hooks install --user once from the board's folder, then restart sessions "
                                        "(without it a session that goes quiet on an unread board line is never nudged)")]
    return [_res(PASS if ok else WARN, "Stop hook", f"{_short(p)}: {text}") for p, text, ok in found]


def config_reads(conf, board_dir):
    """[(label, file name, inside the project?)] for each file config.toml has read into card prompts: markdown and file-tail providers
    and [prompt] template_file. Only file names, never the folder."""
    out = []
    provs = conf.get("providers") if isinstance(conf.get("providers"), dict) else {}
    for name, p in provs.items():
        if isinstance(p, dict) and p.get("type") in ("markdown", "file-tail") and isinstance(p.get("path"), str):
            f = Path(p["path"]).expanduser()
            f = f if f.is_absolute() else Path(board_dir).parent / f
            out.append((f"providers.{name}", f.name[:60], providers.inside_project(f, board_dir)))
    pr = conf.get("prompt") if isinstance(conf.get("prompt"), dict) else {}
    if isinstance(pr.get("template_file"), str) and pr["template_file"].strip():
        f = (Path(board_dir) / pr["template_file"]).expanduser()
        out.append(("prompt.template_file", f.name[:60], providers.inside_project(f, board_dir)))
    return out


def check_config(board_dir, locked=None):
    locked = lockdown.locked() if locked is None else locked
    try:
        conf = promptlib.load_config(board_dir)
    except BoardError as e:
        return [_res(WARN, "config", f"config.toml could not be read: {str(e).splitlines()[0][:100]}")]
    switches = []
    chat = conf.get("chat") if isinstance(conf.get("chat"), dict) else {}
    for key in ("casual", "autopilot"):
        if chat.get(key) is True:
            switches.append(f"chat.{key} (claude -p on a timer)")
    for name, p in (conf.get("providers") or {}).items() if isinstance(conf.get("providers"), dict) else []:
        if isinstance(p, dict) and p.get("type") in ("command", "http"):
            switches.append(f"providers.{name} ({'a shell command' if p['type'] == 'command' else 'a web request'})")
    backup = conf.get("backup") if isinstance(conf.get("backup"), dict) else {}
    if str(backup.get("sync_dir", "")).strip():
        switches.append("backup.sync_dir (a nightly copy to a synced folder)")
    run = conf.get("run") if isinstance(conf.get("run"), dict) else {}
    if run.get("claude"):
        switches.append("run.claude (a different claude program)")
    known = {"chat", "providers", "backup", "run", "notify", "voice", "agent_colors", "owner", "reports", "hud", "prompt", "board", "knowledge"}
    other = sorted(k for k in conf if k not in known)
    out = []
    if not switches:
        out.append(_res(PASS, "config", "no switch in config.toml starts a program or sends data out"))
    elif locked:
        out.append(_res(PASS, "config", f"{len(switches)} switch(es) in config.toml would start a program or send data out, but {lockdown.ENV} is on: " + "; ".join(switches)))
    else:
        out.append(_res(WARN, "config", f"{len(switches)} switch(es) in config.toml start a program or send data out: " + "; ".join(switches) + f" ({lockdown.ENV} would stop them)"))
    reads = config_reads(conf, board_dir)
    if reads:
        outside = [r for r in reads if not r[2]]
        listing = lambda rs: "; ".join(f"{label} ({name})" for label, name, _inside in rs)
        if not outside:
            out.append(_res(INFO, "config reads", f"config.toml reads {len(reads)} file(s) into card prompts, all inside the project folder: {listing(reads)}"))
        elif locked:
            out.append(_res(PASS, "config reads", f"{len(outside)} file(s) named in config.toml are outside the project folder and would be refused ({lockdown.ENV} is on): {listing(outside)}"))
        else:
            out.append(_res(WARN, "config reads", f"config.toml reads {len(outside)} file(s) OUTSIDE the project folder into card prompts: {listing(outside)}; "
                                                f"with {lockdown.ENV} set they are refused"))
    if other:
        out.append(_res(INFO, "config", "other sections, not checked here: " + ", ".join(other)))
    return out


def check_knowledge(board_dir):
    """The notes files a board lists in [knowledge] files = [...] (read only by a plugin's lookup source; empty by default). Only the file
    names are shown, never the folder: it can hold an account name, and this output gets pasted into reviews."""
    try:
        conf = promptlib.load_config(board_dir)
    except BoardError:
        return []
    k = conf.get("knowledge") if isinstance(conf.get("knowledge"), dict) else {}
    files = k.get("files") if isinstance(k.get("files"), list) else []
    if not files:
        return [_res(INFO, "knowledge", "no notes files are listed in config.toml [knowledge] (the default): lookup searches cards and reports only")]
    names, problems = [], []
    for f in files:
        p = Path(f) if isinstance(f, str) and f.strip() else None
        name = (p.name if p else "?")[:60]
        names.append(name)
        if p is None or not p.is_absolute():
            problems.append(f"{name}: not an absolute path")
            continue
        try:
            st = os.lstat(p)
        except OSError:
            problems.append(f"{name}: not found")
            continue
        if stat.S_ISLNK(st.st_mode):
            problems.append(f"{name}: is a symlink (it will be refused)")
        elif not stat.S_ISREG(st.st_mode):
            problems.append(f"{name}: not a regular file")
    note = f" (ignored: {lockdown.ENV} is on)" if lockdown.locked() else ""
    text = f"{len(files)} notes file(s) listed in [knowledge]{note}: " + ", ".join(names)
    return [_res(WARN if problems else INFO, "knowledge", text + ("; " + "; ".join(problems) if problems else ""))]


def check_code():
    outbound, servers = [], []
    for p in sorted(_HERE.glob("*.py")):
        if p.name == "doctor.py":
            continue
        src = p.read_text(errors="ignore")
        if NETWORK_IMPORT.search(src):
            outbound.append(p.stem)
        if SERVER_IMPORT.search(src):
            servers.append(p.stem)
    audit = sorted(set(outbound) & AUDIT_ONLY)
    outbound = [m for m in outbound if m not in AUDIT_ONLY]
    servers = [m for m in servers if m not in AUDIT_ONLY]
    extra = sorted(set(outbound) - CORE_OUTBOUND)
    text = (f"modules that can make an outbound connection: {', '.join(outbound) or 'none'}; modules that can listen: {', '.join(servers) or 'none'}"
            + (f"; the work-profile guards and selfcheck ({', '.join(audit)}) only refuse or talk to loopback" if audit else ""))
    if extra:
        return [_res(WARN, "code", text + f". Beyond the core ({', '.join(sorted(CORE_OUTBOUND))}): {', '.join(extra)}: each is off unless configured; check the lock above")]
    return [_res(PASS, "code", text)]


# -- the whole report -----------------------------------------------------------------------------------------------------------
def check_agents(board_dir, project):
    """Is anything connected to this board? Which agents have reported (names from the cards), and whether this project's CLAUDE.md or AGENTS.md
    carries agentboard's lines. Read-only: it reads tasks.json and one text file, and never writes."""
    import json
    from . import agentfiles
    out = []
    names = None
    try:
        data = json.loads((Path(board_dir) / "tasks.json").read_text())
        names = sorted({str(t["agent"]) for t in (data.get("tasks") if isinstance(data, dict) else []) or [] if isinstance(t, dict) and t.get("agent")})
    except (OSError, ValueError):
        pass   # an unreadable board is the files check's business, not this one's
    if names is not None:
        if names:
            out.append(_res(PASS, "agents", f"{len(names)} agent{'s' if len(names) != 1 else ''} reported to this board: " + ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")))
        else:
            out.append(_res(INFO, "agents", "no agent has reported to this board yet"))
    found = agentfiles.agent_file(project)
    if found is None:
        out.append(_res(INFO, "agents", "no CLAUDE.md or AGENTS.md here: `agentboard instructions` prints the lines to give your agents; `agentboard init --instructions` makes AGENTS.md with them"))
    elif agentfiles.has_instructions(found):
        out.append(_res(PASS, "agents", f"{found.name} has agentboard's instructions"))
    else:
        out.append(_res(INFO, "agents", f"{found.name} does not have agentboard's instructions yet: `agentboard init --instructions` adds them (an agent reads them from there)"))
    return out


def run(board_dir, project=None, env=None, runner=subprocess.run):
    """[(level, name, text)] for the machine as it is now. Changes nothing."""
    board_dir = Path(board_dir)
    project = Path(project) if project else board_dir.parent
    env = os.environ if env is None else env
    results = []
    results += check_version(runner)
    results += check_install()
    results += check_locks(env, board_dir)
    results += check_plugins()
    results += check_plugin_load(board_dir)
    pids = _board_pids(runner)
    results += check_listeners(runner, pids)
    server_lines, locked = check_servers(board_dir, pids or [], _env_on(env, lockdown.ENV))
    results += server_lines
    results += check_config(board_dir, locked=locked)
    results += check_knowledge(board_dir)
    results += check_files(board_dir)
    results += check_watchdog(board_dir)
    results += check_git(project, board_dir, runner)
    results += check_hooks(project)
    results += check_stop_hook(project)
    results += check_agents(board_dir, project)
    results += check_code()
    return results


def render(results, board_dir):
    width = max(len(n) for _l, n, _t in results)
    lines = [f"agentboard doctor   board: {_short(board_dir)}"]
    lines += [f"{level:<4}  {name:<{width}}  {text}" for level, name, text in results]
    counts = {k: sum(1 for r in results if r[0] == k) for k in (FAIL, WARN, PASS, INFO)}
    lines.append(f"{counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[PASS]} PASS, {counts[INFO]} INFO")
    return "\n".join(lines)


def exit_code(results, strict=False):
    return 1 if any(r[0] == FAIL or (strict and r[0] == WARN) for r in results) else 0
