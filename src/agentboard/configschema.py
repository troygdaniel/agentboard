"""One schema for config.toml: every known key with its type, range, default and a one-line meaning (overnight-config-validation).

Tonight several settings silently did the wrong thing: a typo in a key was ignored, a value of the wrong type fell through to whatever the
reader did with it, a switch could turn a safety feature off without a word. This module is the one place that says what config.toml may
hold. Three things use it:

    validate(conf)   -> [Finding]        unknown sections and keys (with the closest valid name), wrong types, out-of-range values, unsafe values
    clean(conf)      -> (conf, findings) the same config with every invalid CORE value replaced by its default: FAIL CLOSED, never a guess.
                                         Unknown keys and sections pass through untouched (a plugin's section, or a typo check reports).
    effective(conf)  -> {section: {key: (value, source)}}   source: "default", "file" or "default (file value invalid)"
    docs()           -> markdown         the reference page, generated from the schema so the docs cannot drift (docs/config.md)

A plugin registers its own sections with api.add_config(section, {key: Field(...)}); they join the schema while plugins are loaded.
The schema holds no behaviour: a module still reads its own section (prompt.load_config hands it the cleaned config), it just no longer
has to guard against a string where an int should be.
"""
import difflib
import os
import string
from dataclasses import dataclass, field

PLAIN_TYPES = {"bool": bool, "int": int, "float": (int, float), "str": str, "list[str]": list, "table": dict, "list[table]": list}


@dataclass(frozen=True)
class Field:
    type: str                      # one of PLAIN_TYPES
    default: object = None
    meaning: str = ""
    min: object = None             # ints and floats: the smallest allowed value
    max: object = None
    choices: tuple = ()            # strings: the only allowed values
    unsafe: str = ""               # a value that is allowed but worth a WARN: the condition as a short predicate name (see UNSAFE)
    keys: dict = field(default_factory=dict)   # for a "table" / "list[table]": the fields of each entry


@dataclass(frozen=True)
class Finding:
    level: str      # "FAIL" (invalid: the default is used), "WARN" (allowed but unsafe), "INFO" (unknown section: maybe a plugin's)
    where: str      # "chat.autopilot_every", "providers.docs.type", "[texts]"
    text: str       # what is wrong, in words, naming the key and the shape; never the value of a string (it may be private)
    fix: str = ""   # the closest valid name, or the default used


def _hex_colour(v):
    return isinstance(v, str) and len(v) in (4, 7) and v[0] == "#" and all(c in string.hexdigits for c in v[1:])


PROVIDER_KEYS = {
    "type": Field("str", meaning="what the provider does", choices=("markdown", "file-tail", "http", "command")),
    "path": Field("str", meaning="markdown, file-tail: the file, relative to the project root or absolute (inside the project under the lock)"),
    "max_chars": Field("int", meaning="markdown: cut the block here", min=1, max=1_000_000),
    "entry_pattern": Field("str", meaning="file-tail: a regex for the line that starts an entry (omit for the last N lines)"),
    "entries": Field("int", 3, "file-tail: how many entries", min=1, max=10_000),
    "url": Field("str", meaning="http: the address; {query} is the card's argument or title, URL-quoted"),
    "json_path": Field("str", meaning="http: dotted path to the list inside the JSON answer"),
    "fields": Field("list[str]", meaning="http: which fields of each result to show"),
    "timeout": Field("int", 10, "http, command: seconds before giving up", min=1, max=600),
    "run": Field("str", meaning="command: the shell command; {arg} and {title} are substituted, already quoted (do not quote them again)"),
    "label": Field("str", meaning="the heading of this provider's block in the prompt (default: the provider's name)"),
    "private": Field("bool", False, "skipped by `agentboard prompt --public`"),
    "redact": Field("list[str]", meaning="regexes whose matches are masked in this provider's block before it is cut"),
}

SCHEMA = {
    "board": {
        "owner": Field("str", "you", "your name: what the board, the HUD and every prompt call the human"),
        "stale_minutes": Field("int", 120, "a Doing card silent this long is marked abandoned on the board and the HUD", min=1, max=100_000),
    },
    "ui": {"dispatch": Field("bool", True, "show Copy prompt and the prompt preview")},
    "hud": {"retired": Field("list[str]", [], "agents hidden from the HUD; their cards and history stay")},
    "voice": {
        "words": Field("list[str]", [], "names the dictation should spell right (yours and the agents' are already included)"),
        "model": Field("str", meaning="a whisper ggml-*.bin file; else $AGENTBOARD_WHISPER_MODEL or a model another app installed"),
    },
    "notify": {
        "enabled": Field("bool", False, "native macOS banner when a card needs input or is ready for review (osascript)"),
        "sound": Field("str", meaning="a macOS notification sound name; omit for silent"),
    },
    "prompt": {
        "template_file": Field("str", meaning="a file (inside the board folder, or absolute) that replaces the built-in prompt template"),
        "template": Field("str", meaning="the template itself, inline: {title}, {task_id}, {description} and the other fields"),
    },
    "providers": Field("table", {}, "context providers for prompts, one table each: [providers.<name>]", keys=PROVIDER_KEYS),
    "chat": {
        "idle_model": Field("str", "haiku", "the cheaper model for `agentboard chat idle` and the autopilot"),
        "idle_budget_usd": Field("float", 0.05, "spend cap per draft, passed to claude as --max-budget-usd", min=0.0, max=100.0),
        "casual": Field("bool", False, "the server gives agents' lines a spoken version (runs claude on a timer)", unsafe="starts a program"),
        "casual_per_hour": Field("int", 60, "lines rephrased an hour, at most", min=1, max=10_000),
        "autopilot": Field("bool", False, "the server drafts replies for idle [orch] agents with unread chat (runs claude on a timer)", unsafe="starts a program"),
        "autopilot_every": Field("int", 180, "seconds between autopilot rounds", min=30, max=86_400),
        "autopilot_per_hour": Field("int", 12, "drafts an hour over every agent: the spend ceiling is this times idle_budget_usd", min=1, max=10_000),
        "share_every_min": Field("int", 60, "an idle agent with nothing to answer offers one thing from its own work this often (0 = never)", min=0, max=100_000),
        "live_min": Field("int", 20, "an agent that spoke or touched a card this recently is awake: the board does not speak for it", min=1, max=100_000),
    },
    "run": {
        "claude": Field("str", meaning="the claude binary for one-shot runs (default: the one on PATH)", unsafe="starts a program"),
        "budget_usd": Field("float", 5.0, "hard spend cap per one-shot run", min=0.0, max=1000.0),
        "max_minutes": Field("int", 45, "hard wall-clock limit per one-shot run", min=1, max=1440),
    },
    "reports": {
        "keep_hours": Field("int", 24, "older card reports are deleted hourly; the newest per card always stays", min=1, max=100_000),
        "repo": Field("str", meaning="the git repo whose commits the reports list (default: the folder above .agentboard)"),
    },
    "agent_colors": Field("table", {}, "one CSS colour per agent name, on every card it holds: \"AGENT-1\" = \"#2563eb\"", keys={"*": Field("str", meaning="a CSS colour")}),
    "backup": {"sync_dir": Field("str", meaning="a folder (iCloud, Google Drive) that gets the newest snapshot nightly", unsafe="sends data out")},
    "redact": {
        "enabled": Field("bool", True, "mask secrets on their way into the board", unsafe="turns masking off"),
        "phones": Field("bool", False, "also mask phone numbers"),
        "extra": Field("list[str]", [], "your own regexes; each match becomes [redacted match]"),
    },
    "orch": {"agents": Field("list[table]", [], "the roster the ORCH prompt and the autopilot use: [{name = \"AGENT-1\", color = \"#2563eb\"}]",
                             keys={"name": Field("str", meaning="the agent's name"), "color": Field("str", meaning="a CSS colour")})},
    "knowledge": {"files": Field("list[str]", [], "notes files a plugin's lookup source may search (absolute paths; the core only lists them)")},
}

_PLUGIN = {}   # section -> {key: Field}, from api.add_config while plugins are loaded


def register(section, fields):
    """A plugin's section (plugins.Api.add_config). Refused when it would shadow a core section."""
    if section in SCHEMA:
        raise ValueError(f"section {section!r} belongs to the core")
    if not isinstance(fields, dict) or not all(isinstance(f, Field) for f in fields.values()):
        raise ValueError("fields must be {key: Field}")
    _PLUGIN[section] = dict(fields)


def _reset():   # tests only
    _PLUGIN.clear()


def sections():
    return {**SCHEMA, **_PLUGIN}


# -- checking ---------------------------------------------------------------------------------------------------------------------------
def _ok_type(f, v):
    t = PLAIN_TYPES[f.type]
    if f.type in ("float",) and isinstance(v, bool):
        return False
    if f.type == "int" and isinstance(v, bool):
        return False
    if not isinstance(v, t):
        return False
    if f.type == "list[str]":
        return all(isinstance(x, str) for x in v)
    if f.type == "list[table]":
        return all(isinstance(x, dict) for x in v)
    if f.type == "float" and v != v:   # NaN
        return False
    if f.type == "float" and v in (float("inf"), float("-inf")):
        return False
    return True


def _shape(f):
    s = f.type
    if f.choices:
        s += " (" + " | ".join(f.choices) + ")"
    if f.min is not None or f.max is not None:
        s += f" {f.min if f.min is not None else ''}..{f.max if f.max is not None else ''}"
    return s


def _check_value(where, f, v, out):
    """One key's value against its Field: a Finding appended and False when it must be replaced by the default."""
    if not _ok_type(f, v):
        got = "a boolean" if isinstance(v, bool) else "a string" if isinstance(v, str) else "a number" if isinstance(v, (int, float)) else "a list" if isinstance(v, list) else "a table" if isinstance(v, dict) else type(v).__name__
        out.append(Finding("FAIL", where, f"must be {_shape(f)}, not {got}", f"default {f.default!r} used" if f.default is not None else "ignored"))
        return False
    if f.choices and v not in f.choices:
        close = difflib.get_close_matches(str(v), f.choices, n=1)
        out.append(Finding("FAIL", where, f"must be one of {', '.join(f.choices)}", f"did you mean {close[0]!r}?" if close else "ignored"))
        return False
    if f.min is not None and v < f.min or f.max is not None and v > f.max:
        out.append(Finding("FAIL", where, f"must be {_shape(f)}; it is out of range", f"default {f.default!r} used" if f.default is not None else "ignored"))
        return False
    if f.type == "str" and where.endswith(("color", "colour")) and not _hex_colour(v) and not v.replace("-", "").isalpha():
        out.append(Finding("WARN", where, "does not look like a CSS colour (#rrggbb or a colour name)"))
    if f.unsafe == "turns masking off" and v is False:
        out.append(Finding("WARN", where, "masking is OFF for this board's cards: a key pasted into a card is stored as written (replies and facts stay masked)"))
    elif f.unsafe == "starts a program" and (v is True or (isinstance(v, str) and v.strip())):
        out.append(Finding("WARN", where, "starts a program on this machine (refused under AGENTBOARD_LOCKDOWN)"))
    elif f.unsafe == "sends data out" and isinstance(v, str) and v.strip():
        out.append(Finding("WARN", where, "copies the board to another folder nightly (refused under AGENTBOARD_LOCKDOWN)"))
    return True


def _check_table(where, fields, table, out, clean):
    """Every key of `table` against `fields` ("*": any key). Returns the cleaned table."""
    kept = {}
    for key, v in table.items():
        f = fields.get(key) or fields.get("*")
        if f is None:
            close = difflib.get_close_matches(key, [k for k in fields if k != "*"], n=1, cutoff=0.6)
            out.append(Finding("WARN", f"{where}.{key}", "is not a key the board reads", f"did you mean {close[0]!r}?" if close else "check the spelling"))
            kept[key] = v   # unknown: kept, so a plugin or a later version can still see it
            continue
        if f.type == "table" and isinstance(v, dict) and f.keys:
            kept[key] = _check_table(f"{where}.{key}", f.keys, v, out, clean)
            continue
        if f.type == "list[table]" and isinstance(v, list) and f.keys and all(isinstance(x, dict) for x in v):
            kept[key] = [_check_table(f"{where}.{key}[{i}]", f.keys, x, out, clean) for i, x in enumerate(v)]
            continue
        if _check_value(f"{where}.{key}", f, v, out) or not clean:
            kept[key] = v
        else:
            kept[key] = f.default if f.default is not None else v   # no default to fall back to (a provider type, a path): kept, so the reader's own message names it
    return kept


def check(conf, clean=False):
    """(cleaned conf, findings). With clean=False the conf comes back as it was."""
    out, result = [], {}
    if not isinstance(conf, dict):
        return conf, [Finding("FAIL", "config.toml", "is not a table of sections")]
    known = sections()
    for sect, body in conf.items():
        spec = known.get(sect)
        if spec is None:
            close = difflib.get_close_matches(sect, list(known), n=1, cutoff=0.6)
            out.append(Finding("INFO" if not close else "WARN", f"[{sect}]", "is not a section the board reads" + ("" if close else " (a plugin's, when the plugin is loaded?)"),
                               f"did you mean [{close[0]}]?" if close else ""))
            result[sect] = body
            continue
        if isinstance(spec, Field):   # a whole-section table: [providers], [agent_colors]
            if not isinstance(body, dict):
                out.append(Finding("FAIL", f"[{sect}]", "must be a table", "ignored"))
                if not clean:
                    result[sect] = body
                continue
            if spec.type == "table" and sect == "providers":
                result[sect] = {name: (_check_table(f"{sect}.{name}", spec.keys, p, out, clean) if isinstance(p, dict)
                                       else (out.append(Finding("FAIL", f"{sect}.{name}", "must be a table [providers.<name>]", "ignored")) or p))
                                for name, p in body.items() if isinstance(p, dict) or not clean}
            else:
                result[sect] = _check_table(sect, spec.keys, body, out, clean)
            continue
        if not isinstance(body, dict):
            out.append(Finding("FAIL", f"[{sect}]", "must be a table of keys", "ignored"))
            if not clean:
                result[sect] = body
            continue
        result[sect] = _check_table(sect, spec, body, out, clean)
    return (result if clean else conf), out


def validate(conf):
    return check(conf, clean=False)[1]


def clean(conf):
    return check(conf, clean=True)


# -- what applies now --------------------------------------------------------------------------------------------------------------------
def effective(conf):
    """{section: {key: (value, source)}} for every core key with a default or a value in the file. source: default | file | default (file value invalid)."""
    cleaned, findings = clean(conf)
    bad = {f.where for f in findings if f.level == "FAIL"}
    out = {}
    for sect, spec in SCHEMA.items():
        rows = {}
        if isinstance(spec, Field):   # providers, agent_colors: the entries as given
            body = cleaned.get(sect) if isinstance(cleaned.get(sect), dict) else {}
            for name, v in body.items():
                rows[name] = (v, "file")
            if not rows:
                rows["(none)"] = (spec.default, "default")
        else:
            body = cleaned.get(sect) if isinstance(cleaned.get(sect), dict) else {}
            for key, f in spec.items():
                where = f"{sect}.{key}"
                if key in body and where not in bad:
                    rows[key] = (body[key], "file")
                elif where in bad:
                    rows[key] = (f.default, "default (file value invalid)")
                elif f.default is not None:
                    rows[key] = (f.default, "default")
        out[sect] = rows
    for sect, spec in _PLUGIN.items():
        body = cleaned.get(sect) if isinstance(cleaned.get(sect), dict) else {}
        out[sect] = {k: (body[k], "file") if k in body else (f.default, "default") for k, f in spec.items() if k in body or f.default is not None}
    return out


SAFE_STRINGS = {("board", "owner"), ("chat", "idle_model"), ("notify", "sound"), ("agent_colors", "*")}   # the only strings `config show` prints


def shown(section, key, value):
    """What `agentboard config show` prints for a value: numbers and booleans as they are; a string only from SAFE_STRINGS (a name, a model, a
    sound, a colour); every other string (a path, a pattern, a number, a key, anything a plugin registered), every list and every table is
    "(set, not shown)" (xr-config-show-prints-secrets: a [redact] extra pattern may be the secret itself, a [knowledge] path is private)."""
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and ((section, key) in SAFE_STRINGS or (section, "*") in SAFE_STRINGS) and len(value) <= 40 and "\n" not in value:
        return value
    if isinstance(value, (list, dict)):
        return f"({len(value)} entr{'y' if len(value) == 1 else 'ies'}, not shown)" if value else "(none)"
    return "(set, not shown)"


ENV = {   # the environment variables the core reads (shown by `agentboard config show`; the value is never printed, only set / unset)
    "AGENTBOARD_DIR": "the board folder to use from anywhere",
    "AGENTBOARD_BOARD": "a registered board name (what --board sets)",
    "AGENTBOARD_HOME": "where the boards registry lives (default ~/.agentboard)",
    "AGENTBOARD_NAME": "the default for --name",
    "AGENTBOARD_LOCKDOWN": "the master lock: refuses everything that starts a program or sends data out",
    "AGENTBOARD_NO_PLUGINS": "the narrow lock for plugins",
    "AGENTBOARD_PLUGINS": "exactly 1: plugins may load",
    "AGENTBOARD_UMASK": "an octal umask for the board's files (default 077: private)",
    "AGENTBOARD_CLAUDE": "the claude binary for one-shot runs and chat rounds",
    "AGENTBOARD_WHISPER_MODEL": "a whisper model file for dictation",
}


def env_state(environ=None):
    environ = os.environ if environ is None else environ
    return {k: ("set" if environ.get(k, "") != "" else "unset", meaning) for k, meaning in ENV.items()}


# -- the reference page --------------------------------------------------------------------------------------------------------------------
def _default_text(f):
    if f.default is None:
        return "unset"
    if isinstance(f.default, str):
        return f'"{f.default}"'
    if isinstance(f.default, bool):
        return "true" if f.default else "false"
    if isinstance(f.default, (list, dict)) and not f.default:
        return "none"
    return str(f.default)


def docs():
    """The configuration reference, generated from the schema. docs/config.md is this text; a test fails when they differ."""
    lines = ["# config.toml: every key", "",
             "Generated from `src/agentboard/configschema.py` by `agentboard config docs`; `tests/test_configschema.py` fails when this page and the schema differ, so edit the schema, not this file.",
             "", "`agentboard init` writes the file with every option commented out. `agentboard config show` prints what applies to a board (and where each value came from),",
             "`agentboard config check` lists unknown keys (with the closest valid name), wrong types and out-of-range values; `agentboard doctor` runs the same check.",
             "An invalid value is never guessed at: the default applies and the check says so. An unknown key is kept (a plugin may read it) and reported.", ""]
    for sect, spec in SCHEMA.items():
        if isinstance(spec, Field):
            lines += [f"## `[{sect}]`", "", spec.meaning + ".", ""]
            if spec.keys:
                lines += ["| Key | Type | Default | Meaning |", "|---|---|---|---|"]
                for key, f in spec.keys.items():
                    lines.append(f"| `{key if key != '*' else '<any name>'}` | {_shape(f)} | {_default_text(f)} | {f.meaning} |")
                lines.append("")
            continue
        lines += [f"## `[{sect}]`", "", "| Key | Type | Default | Meaning |", "|---|---|---|---|"]
        for key, f in spec.items():
            note = f" **Unsafe:** {f.unsafe}." if f.unsafe else ""
            lines.append(f"| `{key}` | {_shape(f)} | {_default_text(f)} | {f.meaning}.{note} |")
        lines.append("")
    lines += ["## Environment", "", "| Variable | Meaning |", "|---|---|"]
    for k, meaning in ENV.items():
        lines.append(f"| `{k}` | {meaning} |")
    lines += ["", "Plugins add their own sections to the schema while they are loaded (`api.add_config`); `agentboard config docs` from the board's shell lists them too.", ""]
    return "\n".join(lines)


def plugin_docs():
    lines = []
    for sect, spec in _PLUGIN.items():
        lines += [f"## `[{sect}]` (plugin)", "", "| Key | Type | Default | Meaning |", "|---|---|---|---|"]
        for key, f in spec.items():
            lines.append(f"| `{key}` | {_shape(f)} | {_default_text(f)} | {f.meaning} |")
        lines.append("")
    return "\n".join(lines)
