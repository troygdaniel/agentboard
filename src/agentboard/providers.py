"""Context providers: configurable sources that contribute a block to a task prompt.

A task lists specs like "mail:tailor pants" or "project-docs:PARENTS,Dad".
The part before the first colon names a provider in config.toml; the rest
is its argument (meaning depends on the provider type).
"""
import json
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 5


class ProviderError(Exception):
    pass


def split_spec(spec):
    name, _, arg = spec.partition(":")
    return name.strip(), arg.strip()


def run_provider(name, arg, conf, task, base_dir):
    """Return text for one provider, or "" if it yields nothing."""
    ptype = conf.get("type")
    fn = TYPES.get(ptype)
    if not fn:
        raise ProviderError(f"provider '{name}': unknown type {ptype!r} (known: {', '.join(TYPES)})")
    text = fn(arg, conf, task, base_dir).strip()
    for pattern in conf.get("redact", []):   # redact first: truncating can cut a secret in half so it no longer matches
        text = re.sub(pattern, "[REDACTED]", text)
    limit = conf.get("max_chars")
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "\n[...truncated]"
    return text


def _path(conf, base_dir):
    p = Path(conf["path"]).expanduser()
    # relative paths resolve against the project root (parent of .agentboard/)
    return p if p.is_absolute() else (Path(base_dir).parent / p)


def markdown(arg, conf, task, base_dir):
    """Sections (## / ### headings) of a markdown file whose title contains any
    comma-separated name in arg. No arg -> the whole file."""
    path = _path(conf, base_dir)
    if not path.exists():
        raise ProviderError(f"file not found: {path}")
    content = path.read_text()
    wanted = [s.strip().lower() for s in arg.split(",") if s.strip()]
    if not wanted:
        return content
    out, keep, keep_level = [], False, 0
    for line in content.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            if keep and level <= keep_level:
                keep = False
            if not keep and any(w in m.group(2).lower() for w in wanted):
                keep, keep_level = True, level
        if keep:
            out.append(line)
    return "\n".join(out)


def file_tail(arg, conf, task, base_dir):
    """Last N entries of a file. Entries start at lines matching entry_pattern;
    without a pattern, the last N lines. arg overrides N."""
    path = _path(conf, base_dir)
    if not path.exists():
        raise ProviderError(f"file not found: {path}")
    n = int(arg) if arg.isdigit() else int(conf.get("entries", 3))
    if n <= 0:
        return ""   # lines[-0:] would be the whole file
    lines = path.read_text().splitlines()
    pattern = conf.get("entry_pattern")
    if not pattern:
        return "\n".join(lines[-n:])
    starts = [i for i, l in enumerate(lines) if re.search(pattern, l)]
    if not starts:
        return "\n".join(lines[-n:])
    return "\n".join(lines[starts[-n:][0]:])


def http(arg, conf, task, base_dir):
    """GET a URL with {query} filled from arg (or the task title). json_path
    walks into the response; fields picks keys to show for each item."""
    query = arg or task["title"]
    url = conf["url"].replace("{query}", urllib.parse.quote(query))
    try:
        with urllib.request.urlopen(url, timeout=conf.get("timeout", TIMEOUT)) as r:
            body = r.read().decode()
    except Exception as e:
        raise ProviderError(f"request failed: {e}")
    try:
        data = json.loads(body)
    except ValueError:
        return body
    for key in filter(None, conf.get("json_path", "").split(".")):
        data = data.get(key, []) if isinstance(data, dict) else data
    items = data if isinstance(data, list) else [data]
    fields = conf.get("fields")
    blocks = []
    for item in items:
        if isinstance(item, dict):
            keys = fields or list(item)
            blocks.append("\n".join(f"{k}: {str(item.get(k, ''))[:500]}" for k in keys))
        else:
            blocks.append(str(item))
    return "\n---\n".join(blocks)


def command(arg, conf, task, base_dir):
    """Run a shell command (cwd = project root). {arg} and {title} are
    substituted shell-quoted."""
    import shlex
    cmd = conf["run"].replace("{arg}", shlex.quote(arg)).replace("{title}", shlex.quote(task["title"]))
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=conf.get("timeout", TIMEOUT), cwd=Path(base_dir).parent)
    except subprocess.TimeoutExpired:
        raise ProviderError("command timed out")
    if r.returncode != 0:
        raise ProviderError(f"command failed ({r.returncode}): {r.stderr.strip()[:200]}")
    return r.stdout


TYPES = {"markdown": markdown, "file-tail": file_tail, "http": http, "command": command}
