"""Start, stop, restart and status for `agentboard serve`, made boring (overnight-rel-server-lifecycle).

    agentboard serve --background      start detached: output to .agentboard/server.log, one line with the pid and the URL once /api/health answers
    agentboard status                  running or not, pid, port, since when, uptime, plugins loaded, lockdown on or off; stale files cleaned
    agentboard stop                    SIGTERM every server of this board and wait until each is gone (in-flight requests finish first)
    agentboard restart                 stop, then start again on the same port with this shell's environment plus every AGENTBOARD_* setting the
                                       old server had and this shell lacks (a restart from a plain shell keeps the keys the board was started
                                       with; --fresh takes this shell's environment only); one line with the old and new pid and what was kept

Everything here reads the board folder's server-<pid>.json files (serverstate.py) and talks to the loopback only (GET /api/health, which
answers with no board data). A stale file (a server killed with -9) is recognised by its dead pid and cleaned. A taken port gets a message
that names who holds it and what to do."""
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import serverstate

LOG_FILE = "server.log"
LOG_MAX_BYTES = 2_000_000   # server.log is rolled to server.log.1 when a background start finds it larger
_SERVE_CMD = re.compile(r"(?:^|[\s/])agentboard(?:\s|$)|-m agentboard\b")   # doctor's own rule for "an agentboard process"
_SERVE_WORD = re.compile(r"\bserve\b")
_NOT_SERVE = re.compile(r"\b(?:doctor|ps|lsof|grep|pgrep|status|stop|restart)\b")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the loopback, never through an http_proxy from the environment
STOP_WAIT_S = 10.0
START_WAIT_S = 15.0
DEFAULT_PORT = 8765


def duration(s):
    s = int(round(s or 0))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60:02d}m"
    return f"{s // 86400}d{s % 86400 // 3600}h"


def _alive(pid):
    """Is the server with this pid running? A child of this process that has exited but was not waited for (a zombie) still answers
    `kill 0`, so it is reaped first: `restart` and the tests start servers as children."""
    try:
        os.waitpid(int(pid), os.WNOHANG)
    except (ChildProcessError, OSError):
        pass
    return serverstate.pid_alive(int(pid))


def command_of(pid, runner=subprocess.run):
    """The command line of a running process from `ps`, or None when ps cannot say."""
    try:
        r = runner(["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    out = (r.stdout or "").strip() if getattr(r, "returncode", 1) == 0 else ""
    return out or None


_NOT_A_SESSION = {"sh", "bash", "zsh", "dash", "fish", "ksh", "tcsh", "csh", "env", "sudo", "nohup", "timeout", "time", "stdbuf", "xargs"}   # a shell or a wrapper runs the command; the session is above it
_SESSION = ["unset"]


def _ps(pid):
    """(parent pid, command name) of a process, or None. A read-only `ps`; it never raises."""
    try:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(int(pid))], capture_output=True, text=True, timeout=3).stdout.strip()
        ppid, _, comm = out.partition(" ")
        return int(ppid), comm.strip()
    except Exception:   # no ps, a refused program start (lockdown), a bad answer: the session is then simply unknown
        return None


def session_id():
    """Which session is running this command, as a string, or None when it cannot be told: AGENTBOARD_SESSION when the session set one (like
    AGENTBOARD_NAME), else the first ancestor process of this command that is not a shell or a wrapper (the agent runtime that spawned the shell, or
    a terminal tab's login), as `pid:N`. Worked out once per process. cursors.py uses it to tell whose delivery a command confirms."""
    named = os.environ.get("AGENTBOARD_SESSION", "").strip()
    if named:
        return named
    if _SESSION[0] != "unset":
        return _SESSION[0]
    found, pid = None, os.getppid()
    for _ in range(12):
        row = _ps(pid) if pid and pid > 1 else None
        if not row:
            break
        ppid, comm = row
        if Path(comm).name.lstrip("-").lower() not in _NOT_A_SESSION:
            found = f"pid:{pid}"
            break
        pid = ppid
    _SESSION[0] = found
    return found


def is_board_server(pid, runner=subprocess.run):
    """Whether the process really is an `agentboard serve`: alive, and its command line says so by doctor's own rule. A pid that a crash or a
    kill -9 left in a state file and that now belongs to another of the user's programs is not, so `stop` never signals it
    (xr-lifecycle-stop-any-pid)."""
    if not _alive(pid):
        return False
    cmd = command_of(pid, runner)
    return bool(cmd and _SERVE_CMD.search(cmd) and _SERVE_WORD.search(cmd) and not _NOT_SERVE.search(cmd))


def _files(board_dir):
    """[(pid, path)] for every server-<pid>.json in the board folder."""
    out = []
    for p in sorted(Path(board_dir).glob(f"{serverstate.PREFIX}*.json")):
        m = serverstate._FILE.fullmatch(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return out


def running(board_dir):
    """The servers of this board that are alive, from their state files: [{pid, port, started, lockdown, plugins_open, plugins_loaded}]."""
    out = []
    for pid, _p in _files(board_dir):
        if is_board_server(pid):
            s = serverstate.read(board_dir, pid)
            if s:
                out.append(s)
    return out


def stale(board_dir):
    """The state files that name no running agentboard server: the pid is gone (killed with -9, a crash), or it now belongs to some other
    program of the user's (pid reuse): [pid]."""
    return [pid for pid, _p in _files(board_dir) if not is_board_server(pid)]


def clean(board_dir):
    """Delete the stale state files (see stale()). Returns the pids cleaned."""
    gone = stale(board_dir)
    for pid in gone:
        try:
            serverstate.path_for(board_dir, pid).unlink()
        except OSError:
            pass
    return gone


def health(port, timeout=2.0):
    """GET /api/health on the loopback: the dict, or None when nothing answers there or what answers is not an agentboard server."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{int(port)}/api/health", headers={"Host": f"localhost:{int(port)}"})
        with _OPENER.open(req, timeout=timeout) as r:
            d = json.loads(r.read(4096).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return None
    return d if isinstance(d, dict) and d.get("ok") is True and isinstance(d.get("agentboard"), str) else None


def status(board_dir):
    """([lines], [running servers]). Stale files are cleaned and said. Exit code is the caller's: 0 when something runs."""
    gone = clean(board_dir)
    live = running(board_dir)
    lines = []
    for s in live:
        h = health(s["port"]) if s["port"] else None
        since = (s["started"] or "?").replace("T", " ")
        if h:
            plug = ", ".join(h.get("plugins") or []) or "none"
            lines.append(f"running: pid {s['pid']} on port {s['port']} since {since} (up {duration(h.get('uptime_s'))}; plugins: {plug}; "
                         f"lockdown {'on' if s['lockdown'] else 'off'}) · http://localhost:{s['port']}/")
        else:
            lines.append(f"recorded: pid {s['pid']} on port {s['port'] or '?'} since {since}, but /api/health does not answer: it is starting, hung, "
                         f"or something else holds the port. Try again in a moment; then `agentboard stop` and `agentboard serve`")
    if gone:
        lines.append(f"cleaned {len(gone)} stale server file{'s' if len(gone) != 1 else ''} (pid {', '.join(map(str, gone))}: not an agentboard serve any more, killed or crashed)")
    if not live:
        lines.append("not running: `agentboard serve` (or `agentboard serve --background` to leave it running without a terminal)")
    return lines, live


def port_taken_message(board_dir, port, err):
    """What `agentboard serve` says when it cannot bind: who holds the port and the next step, instead of a bare errno."""
    mine = [s for s in running(board_dir) if s["port"] == port]
    if mine:
        s = mine[0]
        return (f"agentboard: this board is already served on port {port} by pid {s['pid']} (since {(s['started'] or '?').replace('T', ' ')}). "
                "`agentboard status` shows it; `agentboard restart` replaces it; `agentboard stop` ends it.")
    h = health(port, timeout=1.0)
    if h:
        return (f"agentboard: port {port} is held by another agentboard server (pid {h.get('pid')}, started {str(h.get('started') or '?').replace('T', ' ')}) "
                f"serving a different board. Use `--port {port + 1}` for this one, or stop that one from its own folder.")
    return f"agentboard: cannot listen on port {port} ({getattr(err, 'strerror', None) or err}): something else holds it. Try `--port {port + 1}`."


def stop(board_dir, timeout=STOP_WAIT_S, wait=time.sleep, clock=time.monotonic):
    """SIGTERM every live server of this board and wait until each is gone (the server finishes the requests in flight, closes, removes its
    file). Returns (ok, one line)."""
    live = running(board_dir)   # only pids whose state file, liveness AND command line say "agentboard serve"
    if not live:
        clean(board_dir)
        return True, "not running (nothing to stop)"
    for s in live:
        if not is_board_server(s["pid"]):   # checked again right before the signal
            continue
        try:
            os.kill(s["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            return False, f"pid {s['pid']} belongs to another user: it cannot be stopped from here"
    start = clock()
    while clock() - start < timeout and any(_alive(s["pid"]) for s in live):
        wait(0.1)
    left = [s["pid"] for s in live if _alive(s["pid"])]
    clean(board_dir)
    pids = ", ".join(str(s["pid"]) for s in live)
    ports = ", ".join(str(s["port"]) for s in live if s["port"])
    if left:
        return False, (f"asked pid {pids} to stop, but {', '.join(map(str, left))} still running after {timeout:.0f} s (a request in flight, or stuck): "
                       f"`kill -9 {' '.join(map(str, left))}` ends it; nothing is lost, every save is atomic")
    return True, f"stopped pid {pids} (port {ports or '?'}) in {clock() - start:.1f} s"


def start_background(board_dir, port=DEFAULT_PORT, env=None, timeout=START_WAIT_S, wait=time.sleep, clock=time.monotonic):
    """Start `agentboard serve --no-open` detached (its own session, output appended to .agentboard/server.log, mode 0600) with this
    shell's environment and the given port, and wait until /api/health answers from that pid. Returns (pid or None, one line)."""
    board_dir = Path(board_dir)
    log_path = board_dir / LOG_FILE
    try:
        if log_path.is_file() and not log_path.is_symlink() and log_path.stat().st_size > LOG_MAX_BYTES:
            os.replace(log_path, f"{log_path}.1")   # one roll: the log never grows without end
    except OSError:
        pass
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)   # never written through a planted link
    env = dict(os.environ if env is None else env)
    env["AGENTBOARD_DIR"] = str(board_dir)
    argv = [sys.executable, "-m", "agentboard", "serve", "--port", str(int(port)), "--no-open"]
    try:
        pr = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=fd, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(board_dir.parent))
    finally:
        os.close(fd)
    start = clock()
    while clock() - start < timeout:
        code = pr.poll()
        if code is not None:
            tail = ""
            try:
                tail = log_path.read_text().strip().splitlines()[-1][:200]
            except (OSError, IndexError):
                pass
            return None, f"the server exited at once (code {code})" + (f": {tail}" if tail else "") + f" (log: {log_path})"
        h = health(port, timeout=1.0)
        if h and h.get("pid") == pr.pid:
            return pr.pid, f"started pid {pr.pid} on port {port}: http://localhost:{port}/ (log: {log_path})"
        wait(0.1)
    return pr.pid, f"started pid {pr.pid} on port {port}, but /api/health did not answer within {timeout:.0f} s (log: {log_path})"


_ENV_BOUND = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=")


def server_env(pid, runner=subprocess.run):
    """The AGENTBOARD_* variables a running server was started with, read from its own process: /proc/<pid>/environ on Linux, `ps -E` on
    macOS (both show the environment of your own processes only). {} when it cannot be read. Values are keys and tokens: callers may
    pass them on to a new server and name the variables, never print the values."""
    out = {}
    try:
        for item in Path(f"/proc/{int(pid)}/environ").read_bytes().split(b"\0"):
            k, sep, v = item.partition(b"=")
            if sep and k.startswith(b"AGENTBOARD_"):
                out[k.decode()] = v.decode(errors="replace")
        return out
    except (OSError, ValueError):
        pass
    try:
        r = runner(["ps", "-E", "-ww", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    s = (r.stdout or "").rstrip("\n")
    bounds = [(m.start(1), m.end(), m.group(1)) for m in _ENV_BOUND.finditer(s)]   # VAR= starts; a value runs to the next start
    for i, (start, end, key) in enumerate(bounds):
        if key.startswith("AGENTBOARD_"):
            stop = bounds[i + 1][0] - 1 if i + 1 < len(bounds) else len(s)
            out[key] = s[end:stop]
    return out


def restart(board_dir, port=None, env=None, fresh=False):
    """Stop the board's server(s) and start one again on the same port (the first running one's, else `port`, else 8765) with this shell's
    environment (`env`, else os.environ) plus every AGENTBOARD_* setting the old server had and this shell lacks, so a restart from a plain
    shell does not silently drop the keys the board was started with (texts, replies, facts). `fresh=True` takes this shell's environment
    only. Returns (ok, one line) that names what was kept (names, never values)."""
    live = running(board_dir)
    ports = [s["port"] for s in live if s["port"]]
    use = int(port or (ports[0] if ports else DEFAULT_PORT))
    was = ", ".join(str(s["pid"]) for s in live) or "none"
    base = dict(os.environ if env is None else env)
    kept = {}
    if live and not fresh:   # read before the stop: the old process must still be there
        kept = {k: v for k, v in server_env(live[0]["pid"]).items() if k not in base and k != "AGENTBOARD_DIR"}
        base.update(kept)
    if live:
        ok, line = stop(board_dir)
        if not ok:
            return False, f"restart stopped short: {line}"
    pid, line = start_background(board_dir, use, env=base)
    if pid is None:
        return False, f"restart failed: {line}"
    note = (f" · kept {len(kept)} setting{'s' if len(kept) != 1 else ''} this shell did not have: {', '.join(sorted(kept))}" if kept
            else " · this shell's environment only" if fresh else "")
    return True, f"restarted on port {use}: pid {pid} (was {was}){note} · http://localhost:{use}/"
