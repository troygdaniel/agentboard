"""agentboard doctor: a read-only check a person (or a company reviewer) can run on the machine and paste into a review.

It changes nothing and opens no socket of its own: it reads files, and asks the system with `ps`, `lsof` and `git` (read-only commands).
Every line is PASS, WARN, FAIL or INFO. FAIL means a claim the board makes is not true on this machine; WARN means something worth a look
(often "a lock is not set"); INFO is just what is there. It never prints a secret: where it finds something key-shaped it says the kind,
the file and the line, not the text. It names no feature of the board: lock variables and network-capable modules are found by reading
the installed package, so it stays right when a feature moves out into a plugin.

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
from .store import BoardError

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
TIMEOUT_S = 10
MAX_FILES = 3000          # tracked files scanned for key-shaped strings
MAX_BYTES = 1_000_000     # a bigger file is skipped
MAX_SHOWN = 5             # hits listed before "and N more"
CORE_OUTBOUND = {"providers"}   # the modules of the core that may open an outbound connection (a URL you write in config.toml)

_OFF = ("", "0", "false", "no")
_HERE = Path(__file__).resolve().parent

KEY_PATTERNS = [   # (kind, regex, level): the first three are never legitimate in a repo
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"), FAIL),
    ("cloud or API key", re.compile(r"\b(?:AKIA[0-9A-Z]{16}|AC[0-9a-f]{32}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abprs]-[A-Za-z0-9-]{10,})\b"), FAIL),
    ("key-like assignment", re.compile(r"""(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b["']?\s*[:=]\s*["']([A-Za-z0-9_\-/+=]{24,})["']"""), WARN),
    ("phone number", re.compile(r"(?<![\d.])(?:\+1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)|(?<!\d)\+1[2-9]\d{9}(?!\d)"), WARN),
]
NETWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:urllib\.request|urllib3|http\.client|socket|ssl|smtplib|ftplib|requests|httpx|aiohttp|websocket)\b", re.M)
SERVER_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:http\.server|socketserver|asyncio)\b", re.M)


def _fake(kind, text):
    """A match that is plainly a placeholder: the 555 exchange is fiction in practice (555-0100 to 555-0199 are reserved for it), a key
    that is one or two characters repeated (ACbbbb... or AKIAXXXX...) is an example, and a quoted "secret" with no digit in it is words."""
    if kind == "phone number":
        d = re.sub(r"\D", "", text)[-10:]
        return "555" in (d[:3], d[3:6])
    if kind == "key-like assignment":
        return not re.search(r"\d", text)
    if kind == "cloud or API key":
        body = re.sub(r"^(?:AKIA|AC|sk-|gh[pousr]_|xox[abprs]-)", "", text)
        return len(set(body.lower())) <= 3
    return False


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


def check_locks(env):
    source = "\n".join(p.read_text(errors="ignore") for p in sorted(_HERE.glob("*.py")) if p.name != "doctor.py")
    names = sorted(set(re.findall(r"AGENTBOARD_NO_[A-Z]+", source)) | {lockdown.ENV})

    def on(name):
        return env.get(name, "").strip().lower() not in _OFF
    out = []
    if on(lockdown.ENV):
        out.append(_res(PASS, "lock", f"{lockdown.ENV} is on: chat rounds, one-shot runs, command and http providers, the backup copy, voice and spawn are refused"))
    else:
        out.append(_res(WARN, "lock", f"{lockdown.ENV} is not set; on a work laptop set it to 1 (it stops everything that starts a program or sends data out)"))
    others = [f"{n} {'on' if on(n) else 'off'}" for n in names if n != lockdown.ENV]
    if others:
        out.append(_res(INFO, "lock", "narrow locks: " + ", ".join(others)))
    return out


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


def check_listeners(runner):
    pids = _board_pids(runner)
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
                                      f"fix: pipx uninstall agentboard; pipx install {_short(folder)}")]
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
    for f in files[:MAX_FILES]:
        p = Path(project) / f
        try:
            if p.is_symlink() or p.stat().st_size > MAX_BYTES:
                continue
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        scanned += 1
        for n, line in enumerate(raw.decode("utf-8", "ignore").splitlines(), 1):
            for kind, rx, level in KEY_PATTERNS:
                if any(not _fake(kind, m.group(m.lastindex or 0)) for m in rx.finditer(line)):
                    hits.append((level, kind, f, n))
    note = f" ({len(files) - MAX_FILES} more not scanned)" if len(files) > MAX_FILES else ""
    if not hits:
        out.append(_res(PASS, "tracked files", f"{scanned} tracked file(s) scanned: no key-shaped string and no phone number{note}"))
    else:
        level = FAIL if any(h[0] == FAIL for h in hits) else WARN
        shown = "; ".join(f"{kind} at {f}:{n}" for _l, kind, f, n in sorted(hits, key=lambda h: (h[0] != FAIL, h[2], h[3]))[:MAX_SHOWN])
        more = f"; and {len(hits) - MAX_SHOWN} more" if len(hits) > MAX_SHOWN else ""
        out.append(_res(level, "tracked files", f"{len(hits)} possible secret(s) or phone number(s) in {scanned} tracked file(s): {shown}{more} (the text is not printed){note}"))
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


def check_config(board_dir):
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
    known = {"chat", "providers", "backup", "run", "notify", "voice", "agent_colors", "owner", "reports", "hud", "prompt", "board"}
    other = sorted(k for k in conf if k not in known)
    out = []
    if not switches:
        out.append(_res(PASS, "config", "no switch in config.toml starts a program or sends data out"))
    elif lockdown.locked():
        out.append(_res(PASS, "config", f"{len(switches)} switch(es) in config.toml would start a program or send data out, but {lockdown.ENV} is on: " + "; ".join(switches)))
    else:
        out.append(_res(WARN, "config", f"{len(switches)} switch(es) in config.toml start a program or send data out: " + "; ".join(switches) + f" ({lockdown.ENV} would stop them)"))
    if other:
        out.append(_res(INFO, "config", "other sections, not checked here: " + ", ".join(other)))
    return out


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
    extra = sorted(set(outbound) - CORE_OUTBOUND)
    text = f"modules that can make an outbound connection: {', '.join(outbound) or 'none'}; modules that can listen: {', '.join(servers) or 'none'}"
    if extra:
        return [_res(WARN, "code", text + f". Beyond the core ({', '.join(sorted(CORE_OUTBOUND))}): {', '.join(extra)}: each is off unless configured; check the lock above")]
    return [_res(PASS, "code", text)]


# -- the whole report -----------------------------------------------------------------------------------------------------------
def run(board_dir, project=None, env=None, runner=subprocess.run):
    """[(level, name, text)] for the machine as it is now. Changes nothing."""
    board_dir = Path(board_dir)
    project = Path(project) if project else board_dir.parent
    env = os.environ if env is None else env
    results = []
    results += check_version(runner)
    results += check_install()
    results += check_locks(env)
    results += check_listeners(runner)
    results += check_config(board_dir)
    results += check_files(board_dir)
    results += check_git(project, board_dir, runner)
    results += check_hooks(project)
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
