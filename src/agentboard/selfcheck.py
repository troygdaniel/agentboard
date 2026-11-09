"""agentboard selfcheck: PROVE what the work profile promises, in a list a reviewer can read.

Two halves, both offline, both on this very code:

  STATIC   every .py file of the package is parsed (not run) and listed against a short table of what may use the network, start a
           program, run dynamic code or load a third-party package, each with the reason it is there and what locks it off. A new use
           anywhere else FAILS the check, so nobody adds a capability by accident. The page and its scripts are scanned for anything that
           would load from another host. The package must have no dependencies.

  RUNTIME  a throwaway board in a temp folder and a real server on a free loopback port, with both run-time guards (guards.py) installed
           and the profile's locks set. Every route in server.py is requested, then a scripted day of work (add, edit, move to done, chat,
           reply, delete, reports) goes through the real handlers. The guards record every attempt: none may be an outside address and
           none may start a program. Then the red-team checks the server must pass: a wrong Host (DNS rebinding), a foreign Origin or
           Sec-Fetch-Site, a wrong content type, oversized and malformed bodies, two requests in one connection, over-long request lines
           and headers, path traversal in every route that takes a name, every verb, a JSON bomb, a stalled client, a provider that
           tries to reach a URL or run a command, and a report that is a link out of its folder.

Nothing here reads your board, your config or your environment beyond what it says; the temp folder is removed at the end.
Levels: PASS, FAIL (exit code 1), WARN (something a reviewer should read), INFO.
"""
import ast
import contextlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import guards, lockdown, profile

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"
HERE = Path(__file__).resolve().parent

# ---- the tables the static scan checks against: where each capability lives, why, and what locks it -------------------------------
NETWORK_MODULES = {"socket", "ssl", "http.client", "http.server", "socketserver", "urllib.request", "urllib3", "ftplib", "smtplib", "poplib",
                   "imaplib", "telnetlib", "nntplib", "xmlrpc.client", "xmlrpc.server", "asyncio", "requests", "httpx", "aiohttp", "websocket",
                   "websockets", "webbrowser", "wsgiref", "ipaddress_"}
NETWORK_ALLOWED = {
    "server.py": {"http.server": "the board's own listener: loopback only, Host-checked", "webbrowser": "opens the board in your browser; not in the work profile"},
    "providers.py": {"urllib.request": "the http provider (a URL you write in config.toml); locked off by AGENTBOARD_LOCKDOWN"},
    "guards.py": {"socket": "the network guard itself"},
    "lifecycle.py": {"urllib.request": "`status`, `stop` and `restart` ask /api/health on 127.0.0.1 only, through an opener with no proxy; a command, never the server"},
    "selfcheck.py": {"socket": "this audit's probes of its own throwaway server", "http.client": "this audit's requests to its own throwaway server",
                     "http.server": "the throwaway server", "urllib.request": "a probe that must be refused by the guard"},
}
PROCESS_MODULES = {"subprocess", "pty", "multiprocessing", "ctypes", "cffi", "pexpect", "sh", "plumbum"}
PROCESS_CALLS = {"os.system", "os.popen", "os.fork", "os.forkpty"} | {f"os.{n}" for n in ("execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
                                                                                   "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp", "spawnvpe",
                                                                                   "spawnl", "spawnle", "spawnlp", "spawnlpe")}
PROCESS_ALLOWED = {
    "agentchat.py": "claude -p for idle chat drafts; refuses under AGENTBOARD_LOCKDOWN (lockdown.refuse)",
    "cli.py": "osascript windows for `spawn` (refuses under the lock) and git/osascript helpers run by the person at the command line",
    "repoguard.py": "read-only git queries (ls-files) for the repo guard the doctor and the tests share; a command, never the server",
    "doctor.py": "read-only git, pipx and lsof queries for `agentboard doctor` (a command, never the server)",
    "lifecycle.py": "a read-only `ps -o command=` to check that a pid is an agentboard serve, and the detached `agentboard serve` that `restart` and `serve --background` start (a command, never the server)",
    "providers.py": "the command provider (a shell command you write in config.toml); locked off by AGENTBOARD_LOCKDOWN",
    "reports.py": "read-only git queries for a finished card's report; the server's process guard refuses them in the work profile",
    "runs.py": "`agentboard run` (claude -p); refuses under AGENTBOARD_LOCKDOWN",
    "voice.py": "ffmpeg, whisper and the clipboard for dictation; refuses under AGENTBOARD_LOCKDOWN",
    "guards.py": "patches subprocess and os so that they refuse",
    "selfcheck.py": "its canaries: a program start the guard must refuse (nothing is started)",
}
SHELL_TRUE_ALLOWED = {"providers.py"}
DYNAMIC_BUILTINS = {"eval", "exec"}
DYNAMIC_MODULES = {"pickle", "marshal", "shelve", "dill", "cloudpickle"}
DYNAMIC_ALLOWED = {}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
LOADER_PATTERNS = [   # a page loading something: not a link the person clicks
    re.compile(r"""(?i)<(?:script|img|iframe|source|audio|video|embed|object)\b[^>]*\b(?:src|data)\s*=\s*["'](?:https?:)?//([^/"'\s:]+)"""),
    re.compile(r"""(?i)<link\b[^>]*\bhref\s*=\s*["'](?:https?:)?//([^/"'\s:]+)"""),
    re.compile(r"""(?i)url\(\s*["']?(?:https?:)?//([^/"')\s:]+)"""),
    re.compile(r"""(?i)@import\s+["'](?:https?:)?//([^/"')\s:]+)"""),
    re.compile(r"""(?i)\b(?:fetch|open|sendBeacon|importScripts|EventSource|WebSocket|Worker)\s*\(\s*[^)]*?["'](?:(?:https?|wss?):)?//([^/"'\s:]+)"""),
    re.compile(r"""(?i)\bimport\s*\(?[^;\n]*["']https?://([^/"'\s:]+)"""),
]


def _res(level, name, text):
    return (level, name, text)


# ======================================================== STATIC ============================================================
def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


_PROC_NAMES = {c.split(".", 1)[1] for c in PROCESS_CALLS}
_TLDS = "com net org io dev ai cloud xyz info gov edu co uk ca de fr ru cn tv".split()   # (not app or sh: Terminal.app and start.sh are file names)
_BARE_HOST = re.compile(r"(?i)\b(?:[a-z0-9-]+\.)+(?:" + "|".join(_TLDS) + r")\b")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_TEST_NETS = ("192.0.2.", "198.51.100.", "203.0.113.")   # RFC 5737: documentation addresses, never routed; nothing dials them
_RESERVED_NAMES = (".invalid", ".example", ".test", ".localhost", ".example.com", ".example.org", ".example.net")


def address_ok(host):
    """Is this host something a string in the code may name: this machine, a documentation range or a reserved name, or a placeholder."""
    h = host.lower().strip("[]")
    bare = h.split(":")[0]
    return (bare in ("localhost", "127.0.0.1", "::1", "", "example.com", "example.org", "example.net") or h.startswith("127.") or h.startswith(_TEST_NETS)
            or bare.endswith(_RESERVED_NAMES) or "{" in h)


def scan_file(path):
    """{'imports': {module: line}, 'calls': {dotted: line}, 'shell_true': [line], 'dynamic': [(what, line)], 'urls': [(host, line)]} for one source file.
    Imports and calls are the ones written out, with `import os as o`, `from os import system` and `getattr(os, "system")` resolved; code built from
    strings at run time shows only as a computed import, which is a WARN (the run-time guards are what catch that)."""
    src = Path(path).read_text()
    tree = ast.parse(src, filename=str(path))
    docs = _docstring_ids(tree)
    out = {"imports": {}, "calls": {}, "shell_true": [], "dynamic": [], "urls": [], "importlib": []}
    os_names, direct = {"os"}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "os":
                    os_names.add(a.asname or "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os" and not node.level:
            for a in node.names:
                direct[a.asname or a.name] = "os." + a.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out["imports"].setdefault(a.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            out["imports"].setdefault(mod, node.lineno)
            for a in node.names:
                out["imports"].setdefault(f"{mod}.{a.name}", node.lineno)
        elif isinstance(node, ast.Call):
            f = node.func
            dotted = None
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                dotted = f"os.{f.attr}" if f.value.id in os_names else f"{f.value.id}.{f.attr}"
            elif isinstance(f, ast.Name):
                dotted = direct.get(f.id, f.id)
            if dotted:
                out["calls"].setdefault(dotted, node.lineno)
                if dotted in DYNAMIC_BUILTINS:
                    out["dynamic"].append((dotted + "()", node.lineno))
                if dotted in ("__import__", "importlib.import_module", "import_module"):
                    out["importlib"].append((dotted, node.lineno))
                if dotted == "getattr" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value in _PROC_NAMES:
                    out["calls"].setdefault("os." + node.args[1].value, node.lineno)   # getattr(os, "system")(...) is os.system(...)
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    out["shell_true"].append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            for m in re.finditer(r"(?i)\b(?:https?|wss?|ftp)://([A-Za-z0-9._\[\]:{}%@-]+)", node.value):
                out["urls"].append((m.group(1).split("/")[0], node.lineno))
            for m in _IPV4.finditer(node.value):
                if all(0 <= int(x) <= 255 for x in m.group(0).split(".")):
                    out["urls"].append((m.group(0), node.lineno))
            for m in _BARE_HOST.finditer(node.value):
                out["urls"].append((m.group(0), node.lineno))
    return out


def _top(mod):
    return mod.lstrip(".").split(".")[0]


NEWER_STDLIB = frozenset({"tomllib"})   # standard library on 3.11+, imported inside try/except by tomlread.py: not "third-party" on a 3.9 or 3.10 run


def _stdlib_names():
    """The standard library's top-level module names: sys.stdlib_module_names on Python 3.10+; on 3.9 (what /usr/bin/python3 is on a Mac)
    read from the running interpreter's own library folder, so the third-party check still runs there. None only when that folder cannot be read."""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return names
    try:
        import sysconfig
        lib = Path(sysconfig.get_path("stdlib"))
        found = set(sys.builtin_module_names) | NEWER_STDLIB
        for p in lib.iterdir():
            if p.suffix == ".py":
                found.add(p.stem)
            elif p.is_dir() and (p / "__init__.py").is_file():
                found.add(p.name)
        for p in (lib / "lib-dynload").glob("*.so"):
            found.add(p.name.split(".")[0])
        return frozenset(found) if len(found) > 100 else None   # a folder that gave almost nothing was not the library: say "not checked"
    except (OSError, KeyError):
        return None


def static_checks(root=None):
    root = Path(root) if root else HERE
    files = sorted(p for p in root.glob("*.py"))
    scans = {p.name: scan_file(p) for p in files}
    res = []
    stdlib = _stdlib_names()

    # 1. network-capable imports, file by file
    bad, allowed_seen = [], []
    for name, sc in scans.items():
        for mod, line in sc["imports"].items():
            m = mod.lstrip(".")
            for net in NETWORK_MODULES:
                if m == net or m.startswith(net + "."):
                    if net in NETWORK_ALLOWED.get(name, {}):
                        allowed_seen.append(f"{name}:{line} {net}")
                    else:
                        bad.append(f"{name}:{line} imports {net}")
                    break
    seen = sorted({a for a in allowed_seen})
    res.append(_res(FAIL if bad else PASS, "static: network-capable imports",
                    ("; ".join(sorted(set(bad))[:6]) + " (not in the table in selfcheck.py)") if bad else
                    f"only where the table allows ({len({s.split()[0].split(':')[0] for s in seen})} files): " + ", ".join(sorted({f'{n}: {k}' for n, d in NETWORK_ALLOWED.items() for k in d if any(s.startswith(n + ':') and s.endswith(' ' + k) for s in seen)}))))
    # 2. starting programs
    bad = []
    for name, sc in scans.items():
        uses = [(m, l) for m, l in sc["imports"].items() if _top(m) in PROCESS_MODULES and not m.startswith(".")]
        uses += [(c, l) for c, l in sc["calls"].items() if c in PROCESS_CALLS]
        uses += [(m, l) for m, l in sc["imports"].items() if m in PROCESS_CALLS]
        if uses and name not in PROCESS_ALLOWED:
            bad += [f"{name}:{l} {m}" for m, l in uses]
    res.append(_res(FAIL if bad else PASS, "static: program-starting code",
                    ("; ".join(sorted(set(bad))[:6]) + " (not in the table)") if bad else
                    f"only in {len([n for n in PROCESS_ALLOWED if n in scans and any(_top(m) in PROCESS_MODULES or m in PROCESS_CALLS for m in list(scans[n]['imports']) + list(scans[n]['calls']))])} files, each locked or a command: " +
                    ", ".join(sorted(n for n in PROCESS_ALLOWED if n in scans and any(_top(m) in PROCESS_MODULES for m in scans[n]["imports"])))))
    # 3. shell=True
    bad = [f"{n}:{l}" for n, sc in scans.items() for l in sc["shell_true"] if n not in SHELL_TRUE_ALLOWED]
    where = sorted(n for n, sc in scans.items() if sc["shell_true"])
    res.append(_res(FAIL if bad else PASS, "static: shell=True", ("; ".join(bad)) if bad else (f"only in {', '.join(where)} (the command provider, locked)" if where else "nowhere")))
    # 4. dynamic code
    bad = []
    for n, sc in scans.items():
        bad += [f"{n}:{l} {w}" for w, l in sc["dynamic"] if n not in DYNAMIC_ALLOWED]
        bad += [f"{n}:{l} imports {m}" for m, l in sc["imports"].items() if _top(m) in DYNAMIC_MODULES]
    res.append(_res(FAIL if bad else PASS, "static: eval, exec, pickle", "; ".join(bad[:6]) if bad else "none"))
    dyn = [f"{n}:{l} {w}" for n, sc in scans.items() for w, l in sc["importlib"]]
    res.append(_res(WARN if dyn else PASS, "static: computed imports", ("a module named at run time: " + "; ".join(dyn[:4])) if dyn else "none (every import is written out)"))
    # 5. third-party packages
    third = {}
    for n, sc in scans.items():
        for m, l in sc["imports"].items():
            if m.startswith(".") or not m:
                continue
            t = _top(m)
            if t != "agentboard" and stdlib is not None and t not in stdlib:
                third.setdefault(t, f"{n}:{l}")
    res.append(_res(FAIL if third else PASS, "static: third-party packages",
                    ("imports " + ", ".join(f"{k} ({v})" for k, v in sorted(third.items()))) if third else "none: standard library only" + ("" if stdlib else " (not checked: python < 3.10)")))
    res.append(_dependency_check())
    # 6. addresses written in the code
    outside = sorted({f"{n}:{l} {h}" for n, sc in scans.items() for h, l in sc["urls"] if not address_ok(h)})
    res.append(_res(FAIL if outside else PASS, "static: addresses in the code",
                    ("; ".join(outside[:6])) if outside else "no URL, IPv4 address or host name with a common suffix (.com .net .org .io .dev ...) in any code string except this machine, the documentation ranges "
                                                             "192.0.2.x / 198.51.100.x / 203.0.113.x and .invalid / .example names (docstrings are not read; an address built from pieces at run time would not show)"))
    # 7. the page and its scripts
    res.append(_assets_check(root))
    return res


def _dependency_check():
    pyproject = HERE.parents[1] / "pyproject.toml"
    try:
        from . import tomlread as tomllib
        deps = tomllib.loads(pyproject.read_text()).get("project", {}).get("dependencies", None)
        if deps is None:
            return _res(PASS, "static: declared dependencies", "none declared")
        return _res(FAIL if deps else PASS, "static: declared dependencies", ("declares " + ", ".join(map(str, deps))) if deps else "an empty list")
    except (OSError, ImportError, ValueError):
        try:
            import importlib.metadata as md
            req = md.requires("agentboard")
            return _res(FAIL if req else PASS, "static: declared dependencies", ("declares " + ", ".join(req)) if req else "none (installed metadata)")
        except Exception:   # noqa: BLE001
            return _res(INFO, "static: declared dependencies", "could not be read here (no pyproject.toml beside the code, no installed metadata)")


def _page_csp_ok(server_py):
    """The Content-Security-Policy the board page is served with (PAGE_CSP in server.py): nothing by default, requests to itself only, no framing."""
    try:
        for node in ast.parse(Path(server_py).read_text()).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PAGE_CSP" for t in node.targets):
                text = ast.literal_eval(node.value)
                return all(want in text for want in ("default-src 'none'", "connect-src 'self'", "frame-ancestors 'none'", "form-action 'none'", "base-uri 'none'")) and "*" not in text
    except (OSError, ValueError, SyntaxError):
        pass
    return False


def _assets_check(root):
    static = Path(root) / "static"
    found, files = [], 0
    for p in sorted(static.glob("*")) if static.is_dir() else []:
        if p.suffix.lower() not in (".html", ".js", ".css", ".svg"):
            continue
        files += 1
        text = p.read_text(errors="replace")
        for rx in LOADER_PATTERNS:
            for m in rx.finditer(text):
                host = (m.group(1) or "").lower()
                if host and host not in ("localhost", "127.0.0.1"):
                    found.append(f"{p.name} loads from {host}")
    csp = _page_csp_ok(Path(root) / "server.py")
    if found:
        return _res(FAIL, "static: the page loads nothing from outside", "; ".join(sorted(set(found))[:5]))
    return _res(PASS if csp else FAIL, "static: the page loads nothing from outside",
                f"{files} page files scanned, no script, style, image, font, frame or request to another host; Content-Security-Policy default-src 'none', connect-src 'self'" if csp
                else "no loader found, but the page's Content-Security-Policy is missing from server.py")


# ======================================================== RUNTIME ===========================================================
class Resp:
    def __init__(self, raw):
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        self.raw = raw
        self.status = int(lines[0].split()[1]) if lines and lines[0].startswith("HTTP/") and len(lines[0].split()) > 1 else 0
        self.headers = {}
        for l in lines[1:]:
            if ":" in l:
                k, v = l.split(":", 1)
                self.headers[k.strip().lower()] = v.strip()
        self.body = body
        self.count = len(re.findall(rb"(?:^|\r\n)HTTP/1\.[01] \d{3} ", raw))

    def text(self):
        return self.body.decode("utf-8", "replace")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def raw(port, data, timeout=5.0, shutdown=True):
    """Send bytes, read until the server closes (or `timeout`), return Resp; Resp.status 0 when nothing came back."""
    chunks = []
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.settimeout(timeout)
        try:
            s.sendall(data)
            if shutdown:
                s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            while True:
                c = s.recv(65536)
                if not c:
                    break
                chunks.append(c)
        except (socket.timeout, OSError):
            pass
    return Resp(b"".join(chunks))


def routes_from_source(src):
    """(GET routes, POST routes, GET prefixes, POST prefixes) named in a server.py: read from the handlers' own comparisons, `_route_get` for GET and `do_POST`
    for POST, so a path that only one of them knows is counted once and under the right verb."""
    tree = ast.parse(src)
    exact = {"_route_get": set(), "do_POST": set()}
    prefix = {"_route_get": set(), "do_POST": set()}

    def is_path(n, fn):   # GET handlers compare `url.path`; do_POST compares its local `path`: a comparison of the other kind is not that verb's route
        if fn == "_route_get":
            return isinstance(n, ast.Attribute) and n.attr == "path" and isinstance(n.value, ast.Name) and n.value.id == "url"
        return isinstance(n, ast.Name) and n.id == "path"

    def strings(n):
        return [c.value for c in ([n] if isinstance(n, ast.Constant) else getattr(n, "elts", [])) if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("/")]
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in exact:
            for node in ast.walk(fn):
                if isinstance(node, ast.Compare) and len(node.ops) == 1 and is_path(node.left, fn.name) and isinstance(node.ops[0], (ast.Eq, ast.In)):
                    exact[fn.name].update(strings(node.comparators[0]))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith" and is_path(node.func.value, fn.name) and node.args:
                    prefix[fn.name].update(strings(node.args[0]))
    return sorted(exact["_route_get"]), sorted(exact["do_POST"]), sorted(prefix["_route_get"]), sorted(prefix["do_POST"])


class Audit:
    def __init__(self):
        self.res = []
        self.tmp = Path(tempfile.mkdtemp(prefix="agentboard-selfcheck-"))
        self.board = self.tmp / ".agentboard"
        self.port = _free_port()
        self.host = f"localhost:{self.port}"
        self.srv = None
        self.net = self.proc = None
        self.saved_env = {}

    def add(self, level, name, text):
        self.res.append(_res(level, name, text))

    def ok(self, cond, name, good, bad):
        self.add(PASS if cond else FAIL, name, good if cond else bad)

    # -- request helpers ------------------------------------------------------------------------------------------
    def get(self, path, host=None, extra=None, ver="1.1"):
        h = f"GET {path} HTTP/{ver}\r\n" + (f"Host: {host or self.host}\r\n" if host != "" else "") + "".join(f"{k}: {v}\r\n" for k, v in (extra or {}).items()) + "Connection: close\r\n\r\n"
        return raw(self.port, h.encode("latin-1", "replace"))

    def post(self, path, body=b"{}", host=None, extra=None, ctype="application/json", length=None):
        hdrs = {"Content-Type": ctype, "Content-Length": str(len(body) if length is None else length), **(extra or {})}
        h = f"POST {path} HTTP/1.1\r\nHost: {host or self.host}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdrs.items()) + "Connection: close\r\n\r\n"
        return raw(self.port, h.encode("latin-1", "replace") + body)

    def verb(self, method, path="/api/tasks"):
        return raw(self.port, f"{method} {path} HTTP/1.1\r\nHost: {self.host}\r\nConnection: close\r\n\r\n".encode())

    def alive(self):
        return self.get("/api/tasks").status == 200

    # -- setup ----------------------------------------------------------------------------------------------------
    def setup(self):
        from .store import Store
        self.profile_before = profile.reason(profile.find_board())   # what this shell says BEFORE the audit sets its own environment
        self.board.mkdir(parents=True)
        probe = self.tmp / "probe-target.txt"
        probe.write_text("outside the project folder\n")
        (self.board / "config.toml").write_text(
            "[providers.web]\ntype = \"http\"\nurl = \"http://198.51.100.45/latest/{query}\"\n\n"
            f"[providers.cmd]\ntype = \"command\"\nrun = \"touch {self.tmp / 'RAN-A-COMMAND'}\"\n\n"
            f"[providers.out]\ntype = \"markdown\"\npath = \"{probe}\"\n\n"
            "[providers.rel]\ntype = \"markdown\"\npath = \"../probe-target.txt\"\n")
        for key in ("AGENTBOARD_LOCKDOWN", "AGENTBOARD_NO_PLUGINS", "AGENTBOARD_PLUGINS", "AGENTBOARD_PROFILE", "HOME", "XDG_CONFIG_HOME", "AGENTBOARD_BOARD", "AGENTBOARD_DIR"):
            self.saved_env[key] = os.environ.get(key)
        os.environ.update({"AGENTBOARD_LOCKDOWN": "1", "AGENTBOARD_NO_PLUGINS": "1", "AGENTBOARD_PROFILE": "work", "HOME": str(self.tmp), "XDG_CONFIG_HOME": str(self.tmp / "cfg")})
        for key in ("AGENTBOARD_PLUGINS", "AGENTBOARD_BOARD", "AGENTBOARD_DIR"):
            os.environ.pop(key, None)
        self.old_umask = os.umask(0o077)   # what `agentboard` itself sets at start (private.tighten_process): the modes below are the ones it keeps
        from . import private
        private.tighten_dir(self.board)
        self.net = guards.network_guard()
        self.proc = guards.process_guard()
        from . import server
        self.store = Store(self.board)
        self.server = server
        self.handler = None
        self.srv = server.new_server(self.store, self.port)
        handler = self.srv.RequestHandlerClass
        self.handler = handler
        handler.timeout = 2   # the stalled-client check must not take 15 s
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def teardown(self):
        with contextlib.suppress(Exception):
            if self.srv:
                self.srv.shutdown()
                self.srv.server_close()
        for g in (self.proc, self.net):
            if g:
                g.uninstall()
        if getattr(self, "old_umask", None) is not None:
            os.umask(self.old_umask)
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- the checks -----------------------------------------------------------------------------------------------
    def profile_state(self):
        from . import plugins
        cur = self.profile_before
        self.add(PASS if cur else WARN, "profile: on in this shell", cur or "NOT on: run `agentboard profile work` (this machine) or export AGENTBOARD_PROFILE=work; the audit below ran as if it were")
        self.ok(lockdown.locked(), "profile: master lock", "AGENTBOARD_LOCKDOWN is on while the audit runs", "the lock is off")
        self.ok(plugins.disabled_reason() is not None, "profile: plugins refused", f"plugins: {plugins.disabled_reason()}", "plugins could load")
        for feature, fn in (("claude rounds", lambda: lockdown.refuse("claude")), ("agentboard run", lambda: lockdown.refuse("run")), ("spawn", lambda: lockdown.refuse("spawn")),
                            ("voice", lambda: lockdown.refuse("voice"))):
            try:
                fn()
                self.add(FAIL, f"profile: {feature} refused", "it ran")
            except Exception as e:   # noqa: BLE001
                self.add(PASS, f"profile: {feature} refused", "the lock raises 'locked off' for it (each feature's own code calls the lock first: that call is covered by the lock's tests, not exercised here)" if "locked" in str(e) else str(e)[:60])

    def guard_canaries(self):
        """Things that must be refused, tried for real: the guard refuses before anything is sent. Every target is a documentation address (RFC 5737:
        192.0.2.x, 198.51.100.x, 203.0.113.x, never routed) or a .invalid name (RFC 2606, never resolves), so that a guard that ever stopped working
        would not make the audit contact a real host or resolver from the machine it is meant to vouch for."""
        probes = [
            ("a TCP connection to an outside address (documentation range)", lambda: socket.create_connection(("192.0.2.10", 80), timeout=1)),
            ("a TCP connection to a name (.invalid)", lambda: socket.create_connection(("canary.invalid", 80), timeout=1)),
            ("a name lookup", lambda: socket.getaddrinfo("canary.invalid", 80)),
            ("urllib.request to a reserved test address", lambda: urllib.request.urlopen("http://192.0.2.1/", timeout=1)),
            ("a UDP datagram to an outside address (documentation range)", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("198.51.100.7", 53))),
            ("listening on a non-loopback address", lambda: socket.socket().bind(("192.0.2.10", 0))),
            ("starting a program (subprocess)", lambda: subprocess.run(["true"])),
            ("starting a program (os.system)", lambda: os.system("true")),
        ]
        refused, passed = [], []
        for label, fn in probes:
            try:
                fn()
                passed.append(label)
            except guards.Refused:
                refused.append(label)
            except OSError as e:
                (refused if "work profile" in str(e) else passed).append(label)
        self.ok(not passed, "guards: the canaries are refused", f"{len(refused)} of {len(probes)} tries refused before anything was sent", "NOT refused: " + "; ".join(passed))
        self.ok(self.proc.refused() and self.net.refused(), "guards: they record what was tried", f"{len(self.net.refused())} network and {len(self.proc.refused())} program attempts logged", "nothing was logged")
        self.net.events.clear()
        self.proc.events.clear()

    def routes_in_source(self):
        return routes_from_source((HERE / "server.py").read_text())

    def sweep(self):
        """Every route the handlers name (read from server.py's own comparisons, GET and POST apart), requested once. A POST goes with an empty JSON
        object: that exercises only its validation path, and the line says so; day_of_work sends real payloads to as many as can take one."""
        get, post, pre_get, pre_post = self.routes_in_source()
        bad = []
        for path in get:
            r = self.get(path + ("?agent=nobody" if path == "/api/transcript" else ""))
            if r.status >= 500 or r.status == 0:
                bad.append(f"GET {path} -> {r.status}")
        for path in post:
            r = self.post(path, b"{}")
            if r.status >= 500 or r.status == 0:
                bad.append(f"POST {path} -> {r.status}")
        for pre in pre_get + pre_post:
            r = self.get(pre + ("none/none" if pre == "/api/x/" else "none"))
            if r.status >= 500 or r.status == 0:
                bad.append(f"GET {pre}* -> {r.status}")
        self.routes = (get, post, pre_get, pre_post)
        self.ok(not bad and len(get) >= 15 and len(post) >= 15, "runtime: every named route answers without a 5xx",
                f"{len(get)} GET routes and {len(pre_get)} GET prefixes requested; {len(post)} POST routes requested with an empty body (their validation path; see the next line for the real payloads)",
                "; ".join(bad) or "too few routes found in server.py to trust the sweep")

    def day_of_work(self):
        """A scripted day through the real handlers with real payloads: every POST route that can take one is sent one the board accepts (200).
        The rest are named in the line, with why: they answer only their validation path here."""
        accepted, refused, why = set(), [], []
        S = self.store

        def go(path, payload, want=(200,)):
            r = self.post(path, json.dumps(payload).encode())
            (accepted.add(path) if r.status in want else refused.append(f"{path} -> {r.status}"))
            return json.loads(r.body or b"{}") if r.status == 200 else {}

        def card(title):
            return go("/api/tasks", {"title": title, "status": "todo"}).get("id", "")
        aid, bid, cid, did = card("Selfcheck one"), card("Selfcheck two"), card("Selfcheck three"), card("Selfcheck four")
        go("/api/edit", {"id": aid, "description": "made by the selfcheck"})
        go("/api/move", {"id": aid, "status": "doing"})
        go("/api/move", {"id": aid, "status": "done"})          # a finished card: its report and, outside the profile, its git line
        with contextlib.suppress(Exception):
            S.review(bid, "ready")                               # (set up through the store: the throwaway board)
        go("/api/send-back", {"id": bid, "text": "not yet"})
        with contextlib.suppress(Exception):
            S.ask(cid, "which one?")
        go("/api/reply", {"id": cid, "text": "this one"})
        go("/api/bulk-move", {"ids": [did], "status": "doing"})
        go("/api/bulk-archive", {"ids": [did]})
        go("/api/unarchive", {"ids": [did]})
        gone = go("/api/delete", {"id": did})
        if gone.get("prev"):
            go("/api/restore", {"task": gone["prev"], "before": gone.get("prev_before"), "kids": gone.get("prev_kids") or []})
        go("/api/clear-done", {})
        go("/api/demo", {})                                      # the empty board's sample cards (first-run)
        with contextlib.suppress(Exception):                    # a twin card, the one fix the watchdog can do on a fresh board
            S.start("Selfcheck twin", "AGENT-9", None)
            S.start("Selfcheck twin", "AGENT-9", None, task_id="selfcheck-twin-2")
        go("/api/watchdog-fix", {"action": "merge", "id": "selfcheck-twin-2"})
        go("/api/chat-agents", {"on": True})
        go("/api/chat", {"text": "hello from the selfcheck"})
        prop = S.chat_send("AGENT-9", "may I?", kind="agent", propose="do a thing") if S.chat_agents() else None
        if prop:
            go("/api/chat-decide", {"seq": prop["seq"], "decision": "declined"})
        line = S.chat_send(S.owner, "anyone there?", kind="user", to="AGENT-9")
        go("/api/chat-nudge", {"seq": line["seq"]})
        go("/api/chat-agents", {"on": False})
        for path in ("/api/task?id=" + aid, "/reports/", "/summary/", "/api/hud", "/api/boards", "/api/config", "/api/chat", "/"):
            r = self.get(path)
            if r.status != 200:
                refused.append(f"GET {path} -> {r.status}")
        post = set(self.routes[1]) if getattr(self, "routes", None) else set()
        validation_only = sorted(post - accepted)
        for path, reason in (("/api/run-kill", "a card with no running one-shot; `run` is locked off in the profile"), ("/api/transcribe", "voice is locked off in the profile")):
            if path in validation_only:
                why.append(f"{path} ({reason})")
        left = [p for p in validation_only if not any(p in w for w in why)]
        text = (f"{len(accepted)} of {len(post)} POST routes took a real payload the board accepted; the others answered only their validation path: "
                + (", ".join(why + left) or "none") + "; plus the page, a card, reports, summary, hud, boards, config and chat as GETs") if post else f"{len(accepted)} POST routes took a real payload"
        self.add(PASS if not refused and not left else FAIL, "runtime: real payloads through the handlers", text if not refused and not left else "; ".join(refused + [f"{p} never got a real payload" for p in left]))

    def ssrf_and_commands(self):
        """Providers that try to reach a URL, run a command, or read a file outside the project: refused, and nothing is attempted."""
        before = len(self.net.events)
        t = json.loads(self.post("/api/tasks", json.dumps({"title": "Provider probe", "status": "todo", "ctx": ["web:x", "cmd:x", "out", "rel"]}).encode()).body or b"{}")
        r = self.get(f"/api/prompt?id={t.get('id', '')}")
        body = r.text()
        ran = (self.tmp / "RAN-A-COMMAND").exists()
        read = "outside the project folder" in body and "locked" not in body
        attempts = [e for e in self.net.events[before:] if not e[2] or "198.51.100.45" in e[1]]   # (loopback events are this audit's own requests to its server)
        self.ok(not ran, "red-team: a command provider", "the command was not run (the lock refused it)", "THE COMMAND RAN")
        self.ok(not attempts, "red-team: an http provider (SSRF)", "no connection and no lookup was even attempted for the metadata address", f"tried: {attempts[:2]}")
        self.ok(not read, "red-team: a file provider outside the folder", "the file outside the project was not read into the prompt", "the file outside the project folder was read")
        self.ok(r.status == 200 and "warnings" in body, "red-team: the prompt still builds", "the prompt came back with the refusals as warnings", f"status {r.status}")

    def http_hardening(self):
        port, host = self.port, self.host
        # DNS rebinding: the Host header
        statuses = {}
        for label, h in (("another name", f"evil.example:{port}"), ("the right name, another port", f"localhost:{port + 1}"), ("no port", "localhost"), ("upper case", f"LOCALHOST:{port}"),
                         ("an IPv6 address", f"[::1]:{port}"), ("a trailing dot", f"localhost.:{port}"), ("two hosts", f"localhost:{port}, evil.example"), ("empty", "")):
            statuses[label] = self.get("/api/tasks", host=h).status if h != "" else self.get("/api/tasks", host="", ver="1.0").status
        self.ok(all(s == 403 for s in statuses.values()), "http: wrong Host refused (DNS rebinding)", f"{len(statuses)} wrong Host headers, all 403", f"not refused: {[k for k, s in statuses.items() if s != 403]}")
        r1 = self.get("/api/tasks", host=f"127.0.0.1:{port}")
        self.ok(r1.status == 200 and self.get("/api/tasks").status == 200, "http: the two own names work", "localhost:PORT and 127.0.0.1:PORT answer", "the real Host is refused")
        # cross-site
        cases = {"foreign Origin": {"Origin": "http://evil.example"}, "Origin null": {"Origin": "null"}, "Sec-Fetch-Site cross-site": {"Sec-Fetch-Site": "cross-site"},
                 "Sec-Fetch-Site same-site": {"Sec-Fetch-Site": "same-site"}, "Origin of another port": {"Origin": f"http://localhost:{port + 1}"}}
        bad = [k for k, h in cases.items() if self.post("/api/tasks", json.dumps({"title": "csrf"}).encode(), extra=h).status != 403]
        self.ok(not bad, "http: cross-site POST refused (CSRF)", f"{len(cases)} cross-site POSTs, all 403", f"accepted: {bad}")
        ct = {t: self.post("/api/tasks", json.dumps({"title": "ct"}).encode(), ctype=t).status for t in ("text/plain", "text/plain;charset=application/json", "multipart/form-data; boundary=x",
                                                                                                           "application/x-www-form-urlencoded", "application/jsonx", "")}
        self.ok(all(s == 415 for s in ct.values()), "http: only exact application/json is accepted", "form, text, multipart and look-alike types all 415", f"accepted: {[k for k, s in ct.items() if s != 415]}")
        side = self.get("/api/prompt?id=x", extra={"Sec-Fetch-Site": "cross-site"}).status
        side2 = self.get("/api/orch-prompt", extra={"Origin": "http://evil.example"}).status
        self.ok(side == 403 and side2 == 403, "http: GETs with side effects refuse cross-site", "/api/prompt and /api/orch-prompt: 403 for a cross-site browser", f"{side}, {side2}")
        # bodies
        n0 = len(self.store.load())
        sizes = {"declared 2 MB": self.post("/api/tasks", b"{}", length=2_000_000).status, "negative length": self.post("/api/tasks", b"{}", length=-5).status,
                 "length not a number": self.post("/api/tasks", b"{}", length="1e3").status, "a body of 1.1 MB": self.post("/api/tasks", b'{"title":"' + b"a" * 1_100_000 + b'"}').status}
        self.ok(all(s in (400, 413, 0) for s in sizes.values()) and len(self.store.load()) == n0, "http: oversized and malformed bodies refused",
                f"{len(sizes)} cases answered 400 and nothing was written", f"{sizes}")
        bomb = self.post("/api/tasks", b"[" * 400_000 + b"]" * 400_000)
        self.ok(bomb.status in (400, 413) and self.alive(), "http: a JSON bomb gets a clean 400 and the server lives", f"deeply nested JSON: {bomb.status}, still serving", f"status {bomb.status or 'dropped connection'}; alive={self.alive()}")
        huge = self.post("/api/tasks", json.dumps({"title": "x" * 5000}).encode())
        self.ok(huge.status in (200, 400) and self.alive(), "http: a very long title", f"{huge.status}, still serving", f"{huge.status}")
        # smuggling and framing
        two = raw(port, (f"GET /api/tasks HTTP/1.1\r\nHost: {host}\r\n\r\nGET /api/hud HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n").encode())
        self.ok(two.count == 1, "http: one request per connection (no pipelining)", "two requests in one write: exactly one response, then the connection closes", f"{two.count} responses")
        clte = raw(port, (f"POST /api/tasks HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: 4\r\nTransfer-Encoding: chunked\r\n\r\n"
                          f"0\r\n\r\nGET /api/hud HTTP/1.1\r\nHost: {host}\r\n\r\n").encode())
        te = raw(port, (f"POST /api/tasks HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                        f"5\r\n{{}}\r\n\r\n0\r\n\r\nGET /api/hud HTTP/1.1\r\nHost: {host}\r\n\r\n").encode())
        dup = raw(port, (f"POST /api/tasks HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 40\r\n\r\n{{}}").encode())
        self.ok(clte.count <= 1 and te.count <= 1 and dup.count <= 1, "http: no request smuggling", "Content-Length with Transfer-Encoding, chunked bodies and duplicate lengths never yield a second response", f"responses: {clte.count}, {te.count}, {dup.count}")
        cr = self.get("/api/tasks%0d%0aX-Injected:%20yes")
        crlf = raw(port, f"GET /api/tasks HTTP/1.1\r\nHost: {host}\r\nX-A: b\rX-Injected: yes\r\n\r\n".encode())
        self.ok("x-injected" not in cr.headers and "x-injected" not in crlf.headers, "http: no header injection", "an encoded or bare CR in a request never reaches a response header", "a header was injected")
        longline = raw(port, b"GET /" + b"a" * 70_000 + b" HTTP/1.1\r\nHost: " + host.encode() + b"\r\n\r\n")
        manyh = raw(port, f"GET /api/tasks HTTP/1.1\r\nHost: {host}\r\n".encode() + b"".join(f"X-{i}: y\r\n".encode() for i in range(300)) + b"\r\n")
        bighdr = raw(port, f"GET /api/tasks HTTP/1.1\r\nHost: {host}\r\nX-Big: ".encode() + b"y" * 70_000 + b"\r\n\r\n")
        self.ok(longline.status == 414 and manyh.status == 431 and bighdr.status in (400, 431), "http: over-long request line and headers refused", "70 KB line 414, 300 headers 431, one 70 KB header refused", f"{longline.status}, {manyh.status}, {bighdr.status}")
        # stalled client
        t0 = time.time()
        stall = raw(port, f"POST /api/tasks HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: 50\r\n\r\n{{".encode(), timeout=6, shutdown=False)
        took = time.time() - t0
        self.ok(took < 5 and self.alive(), "http: a stalled client is dropped", f"a body that never finishes was cut after {took:.1f} s (the handler timeout; 15 s in the real server)", f"held for {took:.1f} s")
        timeout_cfg = self.handler.timeout
        # a flood of idle connections: count what was really held and what was refused at once
        held, failed = [], 0
        self.handler.timeout = 30   # (the short timeout set for the stalled-client check would free the early connections before the last one is open)
        try:
            for _ in range(self.srv.MAX_CONNECTIONS + 30):
                for attempt in range(4):
                    try:
                        held.append(socket.create_connection(("127.0.0.1", port), timeout=5))
                        break
                    except OSError:
                        time.sleep(0.2)
                else:
                    failed += 1
                    break
            time.sleep(0.5)
            kept, refused = 0, 0
            for c in held:
                c.settimeout(0.1)
                try:
                    data = c.recv(64)
                except socket.timeout:
                    kept += 1   # idle and still open: the server holds a thread for it
                    continue
                except OSError:
                    continue
                refused += 1 if data.startswith(b"HTTP/1.0 503") else 0
            over = raw(port, f"GET /api/tasks HTTP/1.1\r\nHost: {host}\r\n\r\n".encode(), timeout=3)
        finally:
            for c in held:
                with contextlib.suppress(OSError):
                    c.close()
            self.handler.timeout = 2
        time.sleep(0.5)
        cap = self.srv.MAX_CONNECTIONS
        judged = len(held) > cap and not failed
        self.ok(judged and kept == cap and refused >= 1 and over.status == 503 and self.alive(), "http: a flood of connections is capped",
                f"{len(held)} connections opened: {kept} are held idle (the cap, {cap}), {refused} more were refused with 503 at once, one more request got 503, and the server answers normally after they close",
                (f"could only open {len(held)} connections (cap {cap}): the check could not judge" if not judged else f"{kept} held idle (cap {cap}), {refused} refused with 503, a further request got {over.status}; alive={self.alive()}"))
        old = raw(port, b"GET /api/tasks\r\n\r\n")
        absolute = raw(port, f"GET http://evil.example/api/tasks HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n".encode())
        self.ok(b'"title"' not in old.raw and b'"tasks"' not in old.raw, "http: a request with no version and no Host", "nothing of the board comes back (no Host to check, so it is refused)", f"{old.status}: {old.raw[:60]!r}")
        self.ok(absolute.status == 403, "http: an absolute-form target with another Host is refused", "403: the Host header decides, not the target", f"{absolute.status}")
        self.ok(all(self.get(p).headers.get("x-content-type-options") == "nosniff" for p in ("/api/tasks", "/api/hud", "/nosuch", "/reports/")), "http: nosniff on every kind of response", "JSON, report index and error pages all say nosniff", "a response can be sniffed")
        # verbs
        verbs = {m: self.verb(m) for m in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "PROPFIND")}
        self.ok(all(v.status == 501 for v in verbs.values()), "http: other verbs are not implemented", "PUT, DELETE, PATCH, OPTIONS, TRACE, CONNECT and WebDAV verbs: 501 (no CORS preflight can succeed)", f"{ {k: v.status for k, v in verbs.items() if v.status != 501} }")
        head = self.verb("HEAD")
        self.ok(head.status == 501 or not head.body, "http: HEAD", f"{head.status}", f"{head.status} with a body")
        allr = [self.get(p) for p in ("/api/tasks", "/", "/api/hud")]
        self.ok(all("access-control-allow-origin" not in r.headers for r in allr), "http: no CORS headers", "no response grants any other origin access", "a response carries Access-Control-Allow-Origin")
        page = self.get("/")
        csp = page.headers.get("content-security-policy", "")
        self.ok("default-src 'none'" in csp and "frame-ancestors 'none'" in csp and page.headers.get("x-frame-options") == "DENY" and page.headers.get("x-content-type-options") == "nosniff",
                "http: the page cannot be framed, sniffed or made to load elsewhere", "Content-Security-Policy default-src 'none', frame-ancestors 'none', X-Frame-Options DENY, nosniff", "headers missing on the page")
        # traversal
        secret = self.tmp / "TRAVERSAL-TARGET"
        secret.write_text("TOP-SECRET-MARKER")
        enc = [("..%2f" * 6) + "etc/passwd", "%2e%2e/" * 6 + "etc/passwd", "..%5c..%5cetc%5cpasswd", "..%252f..%252fetc/passwd", "../" * 6 + "etc/passwd", "%00", "x.html%00.txt",
               ".", "..", "./../x", f"..%2f{secret.name}"]
        prefixes = ("/reports/", "/b/", "/b/x/reports/", "/static/", "/api/x/home/", "/voice.js/", "//", "/")
        leaks = []
        for e in enc:
            for prefix in prefixes:
                r = self.get(prefix + e)
                t = r.text()
                if r.status >= 500 or "root:" in t or "TOP-SECRET-MARKER" in t:
                    leaks.append(f"{prefix}{e[:20]} -> {r.status}")
        self.ok(not leaks, "red-team: path traversal", f"{len(enc) * len(prefixes)} traversal URLs ({len(enc)} spellings under {len(prefixes)} route prefixes): nothing outside the board served, no 5xx", "; ".join(leaks[:4]))
        # a report that is a link out of its folder
        rep = self.server.reports.reports_dir(self.board)
        rep.mkdir(parents=True, exist_ok=True)
        link = rep / "escape-20261107-000000.html"
        with contextlib.suppress(OSError):
            link.symlink_to(secret)
        r = self.get("/reports/" + link.name)
        self.ok("TOP-SECRET-MARKER" not in r.text(), "red-team: a report that is a symlink out of its folder", "not served", "the file behind a symlink in the reports folder was served")
        # a transcript path outside what a session may register
        with contextlib.suppress(Exception):
            from . import hooks
            hooks.remember_session(self.board, "ProbeAgent", session_id="probe", transcript=str(secret))
        r = self.get("/api/transcript?agent=ProbeAgent")
        self.ok("TOP-SECRET-MARKER" not in r.text(), "red-team: a transcript path that is any file", "an arbitrary registered file is not read back", "the transcript route returned a file that is not a session transcript")
        # board names
        names = [self.get(f"/b/{n}/api/tasks").status for n in ("nosuch", "..", "a" * 80, "UPPER", "x%2fy", "x y")]
        self.ok(all(s in (404, 400, 403) for s in names), "red-team: unknown board names", "not found, and nothing loaded from a path built from the name", f"{names}")
        self.ok(self.alive(), "http: the server is still serving after all of it", "yes", "the server stopped answering")

    def files(self):
        bad = []
        for p in [self.board, *self.board.glob("*")]:
            try:
                mode = p.stat().st_mode & 0o777
            except OSError:
                continue
            if p == self.board and mode & 0o077:
                bad.append(f"{p.name}/ is {mode:o}")
            elif p.is_file() and mode & 0o077 and p.name != "config.toml":
                bad.append(f"{p.name} is {mode:o}")
        self.ok(not bad, "files: private modes", "the board folder is 0700 and what the server wrote is 0600", "; ".join(bad[:4]))

    def guard_results(self):
        net_bad = [e for e in self.net.events if not e[2] and e[0] not in ("getaddrinfo", "gethostbyname")]
        looked = [e for e in self.net.events if not e[2]]
        local = [e for e in self.net.events if e[2]]
        procs = list(self.proc.events)
        self.ok(not looked, "runtime: nothing tried to leave this machine", f"{len(local)} connections and lookups were all loopback or this machine's own; no outside address was ever tried", "tried: " + "; ".join(f"{k} {t}" for k, t, _ in looked[:4]))
        self.ok(not procs, "runtime: no program was started", f"the server and every route started nothing ({len(local)} loopback sockets used)", "tried: " + "; ".join(f"{k} {t}" for k, t, _ in procs[:4]))
        listen = self.srv.server_address[0]
        self.ok(listen == "127.0.0.1", "runtime: listening only on loopback", f"the server's socket is bound to {listen}", f"bound to {listen}")


# ======================================================== LIVE (the running server) ==========================================
LIVE_PATHS = ("/voice.js", "/", "/nosuch", "/api/prompt?id=none", "/api/orch-prompt")   # the only paths the live probes ask for: no card, chat line, report or transcript


def live_checks(port, board_dir=None, runner=None):
    """Read-only probes of the server that is RUNNING on 127.0.0.1:port. GET only for everything that could return board data; the few POSTs carry no body
    and a foreign Origin or a wrong content type, so a correct server refuses them before it reads anything and a wrong one would find an empty body.
    Asks for the page (static), a script, a missing path and the two prompt routes with a cross-site header; never a card, a chat line or a report."""
    res = []

    def ok(cond, name, good, bad):
        res.append(_res(PASS if cond else FAIL, name, good if cond else bad))

    def get(path, host=None, extra=None):
        h = f"GET {path} HTTP/1.1\r\nHost: {host or f'localhost:{port}'}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in (extra or {}).items()) + "Connection: close\r\n\r\n"
        return raw(port, h.encode("latin-1", "replace"), timeout=5)

    try:
        up = get("/voice.js")
    except OSError as e:
        return [_res(FAIL, "live: the server answers", f"nothing is listening on 127.0.0.1:{port} ({e.__class__.__name__}); start `agentboard serve` or give --port")]
    ok(up.status == 200 and b"function" in up.body, "live: the server answers on 127.0.0.1", f"port {port} serves the board's page files", f"status {up.status}")
    wrong = {label: get("/voice.js", host=h).status for label, h in (("another name", f"evil.example:{port}"), ("another port", f"localhost:{port + 1}"), ("no port", "localhost"),
                                                                       ("upper case", f"LOCALHOST:{port}"), ("IPv6", f"[::1]:{port}"), ("two hosts", f"localhost:{port}, evil.example"))}
    ok(all(v == 403 for v in wrong.values()), "live: wrong Host refused (DNS rebinding)", f"{len(wrong)} wrong Host headers, all 403", f"not refused: {[k for k, v in wrong.items() if v != 403]}")
    ok(get("/voice.js", host=f"127.0.0.1:{port}").status == 200, "live: both of its own names work", "localhost:PORT and 127.0.0.1:PORT", "127.0.0.1:PORT is refused")
    page = get("/")
    csp = page.headers.get("content-security-policy", "")
    ok("default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp and page.headers.get("x-frame-options") == "DENY" and page.headers.get("x-content-type-options") == "nosniff",
       "live: the page's policy and headers", "Content-Security-Policy default-src 'none', connect-src 'self', no framing, nosniff", "the page lacks its policy or frame headers")
    ok("access-control-allow-origin" not in page.headers and "access-control-allow-origin" not in get("/nosuch").headers, "live: no CORS header", "no response grants another origin access", "a response carries Access-Control-Allow-Origin")
    ok(get("/nosuch").headers.get("x-content-type-options") == "nosniff" and up.headers.get("x-content-type-options") == "nosniff", "live: nosniff on scripts and errors", "yes", "a script or an error page can be sniffed (an older server: restart it from this build)")
    side = [get(p, extra={"Sec-Fetch-Site": "cross-site"}).status for p in ("/api/prompt?id=none", "/api/orch-prompt")]
    ok(side == [403, 403], "live: GETs with side effects refuse a cross-site browser", "/api/prompt and /api/orch-prompt: 403", f"{side}")
    posts = []
    for extra in ({"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
        h = f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{port}\r\nContent-Type: application/json\r\nContent-Length: 0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in extra.items()) + "Connection: close\r\n\r\n"
        posts.append(raw(port, h.encode()).status)
    h = f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{port}\r\nContent-Type: text/plain\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    posts.append(raw(port, h.encode()).status)
    ok(posts == [403, 403, 403, 415], "live: cross-site and wrong-type POSTs refused (CSRF)", "a foreign Origin, cross-site, Origin null: 403; text/plain: 415 (no body was sent, nothing was written)", f"{posts}")
    verbs = {m: raw(port, f"{m} /nosuch HTTP/1.1\r\nHost: localhost:{port}\r\nConnection: close\r\n\r\n".encode()).status for m in ("PUT", "DELETE", "OPTIONS", "TRACE", "PATCH")}
    ok(all(v == 501 for v in verbs.values()), "live: other verbs are not implemented", "PUT, DELETE, OPTIONS, TRACE, PATCH: 501", f"{verbs}")
    leaks = []
    for e in ("..%2f" * 6 + "etc/passwd", "../" * 6 + "etc/passwd", "%2e%2e/" * 6 + "etc/passwd", "..%252f..%252fetc/passwd", "%00"):
        for pre in ("/reports/", "/b/", "/static/", "/voice.js/", "//"):
            r = get(pre + e)
            if r.status >= 500 or b"root:" in r.body:
                leaks.append(f"{pre}{e[:14]} {r.status}")
    ok(not leaks, "live: path traversal", "25 traversal URLs: nothing outside served, no 5xx", "; ".join(leaks[:3]))
    two = raw(port, f"GET /voice.js HTTP/1.1\r\nHost: localhost:{port}\r\n\r\nGET /voice.js HTTP/1.1\r\nHost: localhost:{port}\r\nConnection: close\r\n\r\n".encode())
    longline = raw(port, b"GET /" + b"a" * 70_000 + f" HTTP/1.1\r\nHost: localhost:{port}\r\n\r\n".encode())
    manyh = raw(port, f"GET /voice.js HTTP/1.1\r\nHost: localhost:{port}\r\n".encode() + b"".join(f"X-{i}: y\r\n".encode() for i in range(300)) + b"\r\n")
    ok(two.count == 1 and longline.status == 414 and manyh.status == 431, "live: framing", "no pipelining (one response per connection), a 70 KB line 414, 300 headers 431", f"{two.count} responses, {longline.status}, {manyh.status}")
    ok(get("/voice.js").status == 200, "live: still serving after the probes", "yes", "the server stopped answering")
    # what the running server says about itself, and who it listens for
    if board_dir:
        try:
            from . import serverstate
            states = [st for st in (serverstate.read(board_dir, int(p)) for p in _server_pids(board_dir)) if st and st["port"] == port]
        except Exception:   # noqa: BLE001
            states = []
        if states:
            st = states[0]
            expected = profile.reason(board_dir) is not None   # this shell is under the profile, so a server that is not is a mismatch (a FAIL); on a home board it is only said (a WARN)
            safe = st["lockdown"] and not st["plugins_open"]
            res.append(_res(PASS if safe else (FAIL if expected else WARN), "live: how it was started",
                            f"pid {st['pid']}: master lock on, plugins closed" if safe else f"pid {st['pid']} was started with the lock {'on' if st['lockdown'] else 'OFF'} and plugins {'OPEN' if st['plugins_open'] else 'closed'}: restart it under `agentboard profile work`"))
            res.append(_res(PASS if st.get("profile") else (FAIL if expected else WARN), "live: the work profile", "the running server is under it (no outside connection, no program start)" if st.get("profile")
                            else "the running server was not started under the work profile: run `agentboard profile work`, then restart it"))
        else:
            res.append(_res(INFO, "live: how it was started", "no server-<pid>.json for this port in the board folder (an older build, or another board)"))
    try:
        from . import doctor
        runner = runner or subprocess.run
        pids = doctor._board_pids(runner)
        res += [(l, f"live: {n}", t) for l, n, t in doctor.check_listeners(runner, pids)]
    except Exception:   # noqa: BLE001
        res.append(_res(INFO, "live: listeners", "could not list the server's sockets here (ps or lsof)"))
    return res


def _server_pids(board_dir):
    from . import serverstate
    return [int(m.group(1)) for p in Path(board_dir).glob(f"{serverstate.PREFIX}*.json") if (m := serverstate._FILE.fullmatch(p.name)) and serverstate.pid_alive(int(m.group(1)))]


def runtime_checks():
    a = Audit()
    try:
        a.setup()
        a.profile_state()
        a.guard_canaries()
        a.sweep()
        a.day_of_work()
        a.ssrf_and_commands()
        a.http_hardening()
        a.files()
        a.guard_results()
    except Exception as e:   # noqa: BLE001  (an audit that crashed is a failed audit, said plainly)
        a.add(FAIL, "runtime: the audit itself", f"stopped with {e.__class__.__name__}: {str(e)[:120]}")
    finally:
        a.teardown()
    return a.res


def run(static=True, runtime=True, live=None, board_dir=None):
    """live: None, or the port of the running server to probe (read-only) after the static scan. With live set the throwaway audit is skipped
    unless runtime is asked for explicitly: the point is the real server."""
    results = []
    if static:
        results += static_checks()
    if runtime and live is None:
        results += runtime_checks()
    if live is not None:
        results += live_checks(int(live), board_dir)
    return results


def render(results):
    width = max(len(n) for _l, n, _t in results)
    live = any(n.startswith("live:") for _l, n, _t in results)
    lines = ["agentboard selfcheck   (the work profile, proved: static scan of the code, then " + ("read-only probes of the running server)" if live else "a live audit of a throwaway server)")]
    lines += [f"{level:<4}  {name:<{width}}  {text}" for level, name, text in results]
    counts = {k: sum(1 for r in results if r[0] == k) for k in (FAIL, WARN, PASS, INFO)}
    lines.append(f"{counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[PASS]} PASS, {counts[INFO]} INFO")
    lines.append("RESULT: " + ("FAIL" if counts[FAIL] else "PASS"))
    return "\n".join(lines)


def exit_code(results):
    return 1 if any(r[0] == FAIL for r in results) else 0
