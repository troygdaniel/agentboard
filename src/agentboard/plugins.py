"""Plugins: the one generic extension point. A plugin is a separate Python package installed next to agentboard; the board loads it only
when this machine says so, and shows only what a loaded plugin registers. With no plugin (or none allowed) the board looks and works
exactly as it does without this module.

Three variables decide, read on every call (never cached):

    AGENTBOARD_PLUGINS=1       the machine's key: exactly "1" (not "true", not " 1"). Unset = nothing is looked up, imported or shown.
    AGENTBOARD_NO_PLUGINS=1    the narrow lock; wins over the key (fails closed: anything but ""/0/false/no locks).
    AGENTBOARD_LOCKDOWN=1      the master lock (lockdown.py); wins over everything and implies the one above.

A plugin is an entry point in the group "agentboard.plugins" whose value is a function taking one argument:

    [project.entry-points."agentboard.plugins"]
    mything = "mything:register"

    def register(api):
        api.add_command("do-thing", "what it does", setup, run)   # agentboard do-thing; setup(parser) adds arguments, run(args, store)
        api.add_route("POST", "do", fn)                           # POST /api/x/mything/do; fn(store, body) -> dict (GET: body = the query)
        api.add_state(fn)                                         # fn(store) -> dict | None, sent with every /api/tasks poll (page: AB.state.mything)
        api.add_thread(fn)                                        # fn(store) runs once in a daemon thread under `agentboard serve`
        api.set_page(script=js_text, style=css_text)              # one script, /api/x/mything/page.js, loaded by the page; the style rides in it
        api.add_source("things", "what it holds", search)           # agentboard lookup "q" --in things; search(store, words, limit) -> [{where, date, title, snippet, score}]

A plugin is code you installed and switched on; it is trusted like any package. What this module guarantees is smaller: nothing loads
unless the machine says so, a plugin can only add routes under its own /api/x/<name>/ and commands that do not shadow a core one, one
plugin failing never stops the board or the others, and an error reaches the client as its class name, never its message.
"""
import json
import os
import re
import threading

from . import lockdown

GROUP = "agentboard.plugins"
ENV = "AGENTBOARD_PLUGINS"
LOCK_ENV = "AGENTBOARD_NO_PLUGINS"
NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,30}")
PATH_RE = re.compile(r"[a-z0-9][a-z0-9_/-]{0,63}")   # no dots, no "..", no leading slash
RESERVED = ("page.js", "page.css")   # page.css stays reserved although there is no such file: the page's CSP allows inline styles, not stylesheet files
_OFF = ("", "0", "false", "no")
_LOCK = threading.Lock()
_LOADED = {}    # name -> Plugin, in load order
_FAILED = []    # (name, ExceptionClassName)
_DONE = [False]


# -- the gate -------------------------------------------------------------------------------------------------------------------
def disabled_reason():
    """Why plugins are off right now, in a few words, or None when they are allowed."""
    if lockdown.locked("plugins"):
        return f"locked: ${lockdown.ENV} is set"
    if os.environ.get(LOCK_ENV, "").strip().lower() not in _OFF:
        return f"locked: ${LOCK_ENV} is set"
    if os.environ.get(ENV) != "1":
        return f"off: ${ENV} is not 1"
    return None


def enabled():
    return disabled_reason() is None


# -- registration ---------------------------------------------------------------------------------------------------------------
class Plugin:
    def __init__(self, name):
        self.name, self.commands, self.routes, self.states, self.threads, self.sources = name, [], {}, [], [], []
        self.script = self.style = None


class Api:
    """What a plugin's register() receives. Every method checks its arguments and raises ValueError on a bad one (the plugin is then
    recorded as failed and the rest of the board carries on)."""

    def __init__(self, plugin):
        self._p = plugin

    def add_command(self, name, help, setup, run):
        if not (isinstance(name, str) and NAME_RE.fullmatch(name)) or not callable(run) or not (setup is None or callable(setup)):
            raise ValueError("bad command")
        self._p.commands.append((name, str(help or ""), setup, run))

    def add_route(self, method, path, fn):
        if method not in ("GET", "POST") or not (isinstance(path, str) and PATH_RE.fullmatch(path)) or "//" in path or ".." in path \
                or path in RESERVED or not callable(fn):
            raise ValueError("bad route")
        if (method, path) in self._p.routes:
            raise ValueError("route registered twice")
        self._p.routes[(method, path)] = fn

    def add_state(self, fn):
        if not callable(fn):
            raise ValueError("bad state")
        self._p.states.append(fn)

    def add_thread(self, fn):
        if not callable(fn):
            raise ValueError("bad thread")
        self._p.threads.append(fn)

    def add_source(self, name, help, search):
        """A place `agentboard lookup` can search. search(store, words, limit) returns hits as dicts (where, date, title, snippet, score);
        the board cleans and cuts every field before printing. It should only read, and never write what it found anywhere."""
        if not (isinstance(name, str) and NAME_RE.fullmatch(name)) or not callable(search) or any(s[0] == name for s in self._p.sources):
            raise ValueError("bad source")
        self._p.sources.append((name, str(help or "")[:120], search))

    def set_page(self, script=None, style=None):
        if not all(x is None or isinstance(x, str) for x in (script, style)):
            raise ValueError("bad page")
        self._p.script, self._p.style = script, style


def load(entry_points=None):
    """Load the allowed plugins once per process and return their names ([] when plugins are off). When off, nothing is looked up and
    nothing is imported. `entry_points` is for tests: an iterable of objects with .name and .load()."""
    with _LOCK:
        if not enabled():
            return []
        if not _DONE[0]:
            _DONE[0] = True
            if entry_points is None:
                from importlib.metadata import entry_points as find
                entry_points = find(group=GROUP)
            for ep in entry_points:
                name = str(getattr(ep, "name", ""))
                try:
                    if not NAME_RE.fullmatch(name) or name in _LOADED:
                        raise ValueError("bad or repeated plugin name")
                    plugin = Plugin(name)
                    ep.load()(Api(plugin))
                    _LOADED[name] = plugin
                except Exception as e:   # noqa: BLE001  (a plugin must never stop the board; only the class name is kept)
                    _FAILED.append((name, e.__class__.__name__))
        return list(_LOADED)


def _reset():   # tests only
    with _LOCK:
        _LOADED.clear()
        _FAILED.clear()
        _DONE[0] = False


def active():
    """The loaded plugins, but only while the gate is open: a lock set after the server started takes them all away at once."""
    return list(_LOADED.values()) if enabled() else []


def failed():
    return list(_FAILED) if enabled() else []


# -- what the server, the CLI and the page use ----------------------------------------------------------------------------------
def commands():
    return [(p.name, *c) for p in active() for c in p.commands]


def sources():
    """[(plugin name, source name, help, search function)] for `agentboard lookup`; empty while plugins are off."""
    return [(p.name, *s) for p in active() for s in p.sources]


def route(method, name, path):
    """('fn', callable) or ('asset', (content_type, text)) for /api/x/<name>/<path>, or None (plugins off, unknown name or path)."""
    for p in active():
        if p.name != name:
            continue
        if method == "GET" and path == "page.js" and _page_js(p) is not None:
            return "asset", ("text/javascript; charset=utf-8", _page_js(p))
        fn = p.routes.get((method, path))
        return ("fn", fn) if fn else None
    return None


def _page_js(p):
    """What /api/x/<name>/page.js serves: the plugin's style (put in a <style> element, because the page's Content-Security-Policy allows
    inline styles but no stylesheet files) followed by its script; None when it registered neither."""
    if p.script is None and p.style is None:
        return None
    css = f"(() => {{ const s = document.createElement('style'); s.textContent = {json.dumps(p.style)}; document.head.appendChild(s); }})();\n" if p.style else ""
    return css + (p.script or "")


def page_tags(base):
    """The <script> tag the page gets for each plugin that registered a script or style (same-origin, covered by the page's script-src 'self').
    Names are validated, so nothing needs escaping."""
    return "".join(f'<script src="{base}/api/x/{p.name}/page.js" defer></script>' for p in active() if _page_js(p) is not None)


def state(store):
    """{plugin name: dict} for /api/tasks: whatever each state function returns (a dict), and nothing from one that fails."""
    out = {}
    for p in active():
        merged = {}
        for fn in p.states:
            try:
                v = fn(store)
            except Exception:   # noqa: BLE001  (a broken state function drops its own part, not the poll)
                continue
            if isinstance(v, dict):
                merged.update(v)
        if merged:
            out[p.name] = merged
    return out


def start_threads(store):
    """Start each plugin's thread function once (daemon). One that raises ends with a single line naming the class; it is never restarted.
    A plugin's loop should ask plugins.enabled() every beat so a lock set later stops it."""
    started = []
    for p in active():
        for fn in p.threads:
            def run(fn=fn, name=p.name):
                try:
                    fn(store)
                except Exception as e:   # noqa: BLE001
                    print(f"agentboard: plugin {name}: {e.__class__.__name__}")
            t = threading.Thread(target=run, daemon=True, name=f"plugin-{p.name}")
            t.start()
            started.append(t)
    return started


def status_lines():
    """The lines `agentboard plugins` prints. It never makes a network call and imports nothing while plugins are off."""
    why = disabled_reason()
    if why:
        return [f"plugins: {why} (nothing is looked up, loaded or imported)"]
    names = load()
    lines = [f"plugins: on, {len(names)} loaded" + (": " + ", ".join(names) if names else " (none installed)")]
    lines += [f"  failed: {n or '?'} ({c})" for n, c in failed()]
    return lines
