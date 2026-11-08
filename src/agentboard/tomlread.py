"""Reading TOML on every Python agentboard supports: `tomllib` (the standard library, 3.11+) when it is there, otherwise the small reader below.

agentboard has no dependencies, and a work PC may have only the Python it came with (3.9 on a 2021 Mac, 3.10 on Ubuntu 22.04), where
`tomllib` does not exist. Rather than pull `tomli` from the package index (a dependency, and a download a locked-down machine may not
allow), this module reads the TOML the board uses: tables and arrays of tables (dotted headers, quoted parts), bare, quoted and dotted keys,
basic and literal strings (single and multi-line, with escapes), integers, floats, booleans, dates and times (as `datetime` objects, like
tomllib), arrays (multi-line, trailing comma) and inline tables, comments. What it refuses it refuses loudly, as a TOMLDecodeError (a
ValueError, as tomllib's is), never by guessing: a file tomllib reads and this reader does not is a bug, and `tests/test_tomlread.py`
feeds both the same documents on a Python that has both.

    from . import tomlread
    tomlread.loads(text)        # dict
    tomlread.load(binary_file)  # dict, UTF-8 (a BOM is fine)
    tomlread.TOMLDecodeError    # ValueError
    tomlread.USING_TOMLLIB      # True when the standard library's tomllib is doing the work
"""
import re
from datetime import date, datetime, time, timedelta, timezone

try:
    import tomllib as _std
    USING_TOMLLIB = True
except ModuleNotFoundError:   # Python 3.9 and 3.10
    _std = None
    USING_TOMLLIB = False


class TOMLDecodeError(ValueError):
    """One class whichever reader did the work (tomllib's own error is re-raised as this, so callers catch one thing)."""


def loads(text):
    if _std is not None:
        try:
            return _std.loads(text)
        except _std.TOMLDecodeError as e:
            raise TOMLDecodeError(str(e)) from e
    try:
        return _Reader(text).document()
    except TOMLDecodeError:
        raise
    except ValueError as e:   # a date that does not exist (2026-02-30), an offset out of range: the reader's own error, never a traceback
        raise TOMLDecodeError(f"bad value: {e}") from e


def load(f):
    """A binary file, UTF-8 (a BOM is accepted), like tomllib.load."""
    data = f.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig")
    return loads(data)


# -- the small reader (used only without tomllib) ---------------------------------------------------------------------------------
_BARE = re.compile(r"[A-Za-z0-9_-]+")
_WS = " \t"
_INT = re.compile(r"[+-]?(?:0|[1-9](?:_?[0-9])*)")
_FLOAT = re.compile(r"[+-]?(?:0|[1-9](?:_?[0-9])*)(?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?")
_SPECIAL = re.compile(r"[+-]?(?:inf|nan)")
_PREFIXED = re.compile(r"0(?:x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*|o[0-7](?:_?[0-7])*|b[01](?:_?[01])*)")
_DATETIME = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[Tt ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|z|[+-]\d{2}:\d{2})?)?")
_TIME = re.compile(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?")
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


class _Reader:
    def __init__(self, text):
        if "\x00" in text:
            raise TOMLDecodeError("NUL byte in TOML text")
        self.s = text.replace("\r\n", "\n")
        self.i = 0
        self.root = {}
        self.cur = self.root
        self.explicit = set()        # ids of tables defined by a [header] (defining one twice is an error)
        self.array_tables = set()    # ids of lists made by [[header]]
        self.inline = set()          # ids of inline tables and arrays (closed: no later key may add to them)

    # -- errors and position --
    def fail(self, msg):
        line = self.s.count("\n", 0, self.i) + 1
        col = self.i - (self.s.rfind("\n", 0, self.i) + 1) + 1
        raise TOMLDecodeError(f"{msg} (at line {line}, column {col})")

    def peek(self, n=1):
        return self.s[self.i:self.i + n]

    def skip_ws(self):
        while self.peek() in ("", " ", "\t"):
            if not self.peek():
                return
            self.i += 1

    def skip_comment(self):
        if self.peek() == "#":
            j = self.s.find("\n", self.i)
            seg = self.s[self.i:j if j >= 0 else len(self.s)]
            if re.search(r"[\x00-\x08\x0a-\x1f\x7f]", seg):
                self.fail("control character in comment")
            self.i = j if j >= 0 else len(self.s)

    def skip_ws_comments_newlines(self):
        while True:
            self.skip_ws()
            self.skip_comment()
            if self.peek() == "\n":
                self.i += 1
                continue
            return

    def end_of_line(self):
        self.skip_ws()
        self.skip_comment()
        if self.peek() not in ("", "\n"):
            self.fail("expected a newline")

    # -- the document --
    def document(self):
        while True:
            self.skip_ws_comments_newlines()
            c = self.peek()
            if not c:
                return self.root
            if c == "[":
                self.header()
            else:
                self.key_value(self.cur)
            self.end_of_line()

    def header(self):
        self.i += 1
        is_array = self.peek() == "["
        if is_array:
            self.i += 1
        self.skip_ws()
        keys = self.dotted_key()
        self.skip_ws()
        close = "]]" if is_array else "]"
        if self.peek(len(close)) != close:
            self.fail("expected " + close)
        self.i += len(close)
        node = self.root
        for k in keys[:-1]:
            node = self.descend(node, k)
        last = keys[-1]
        if is_array:
            lst = node.get(last)
            if lst is None:
                lst = node[last] = []
                self.array_tables.add(id(lst))
            elif not isinstance(lst, list) or id(lst) not in self.array_tables:
                self.fail(f"cannot redefine {last!r} as an array of tables")
            self.cur = {}
            lst.append(self.cur)
            self.explicit.add(id(self.cur))
            return
        t = node.get(last)
        if t is None:
            t = node[last] = {}
        elif not isinstance(t, dict) or id(t) in self.explicit or id(t) in self.inline:
            self.fail(f"table {last!r} is defined twice")
        self.explicit.add(id(t))
        self.cur = t

    def descend(self, node, k):
        """A header's middle part: walk into a table, or the last table of an array of tables, making tables on the way."""
        v = node.get(k)
        if v is None:
            v = node[k] = {}
        elif isinstance(v, list) and id(v) in self.array_tables:
            if not v:
                self.fail(f"{k!r} is an empty array of tables")
            v = v[-1]
        elif not isinstance(v, dict) or id(v) in self.inline:
            self.fail(f"key {k!r} is not a table")
        return v

    def key_value(self, table):
        keys = self.dotted_key()
        self.skip_ws()
        if self.peek() != "=":
            self.fail("expected =")
        self.i += 1
        self.skip_ws()
        value = self.value()
        node = table
        for k in keys[:-1]:
            v = node.get(k)
            if v is None:
                v = node[k] = {}
            elif not isinstance(v, dict) or id(v) in self.inline or id(v) in self.explicit:
                self.fail(f"key {k!r} is not an open table")
            node = v
        if keys[-1] in node:
            self.fail(f"key {keys[-1]!r} is set twice")
        node[keys[-1]] = value

    def dotted_key(self):
        keys = [self.simple_key()]
        while True:
            self.skip_ws()
            if self.peek() != ".":
                return keys
            self.i += 1
            self.skip_ws()
            keys.append(self.simple_key())

    def simple_key(self):
        c = self.peek()
        if c == '"':
            return self.basic_string()
        if c == "'":
            return self.literal_string()
        m = _BARE.match(self.s, self.i)
        if not m:
            self.fail("expected a key")
        self.i = m.end()
        return m.group(0)

    # -- values --
    def value(self):
        c = self.peek()
        if c == '"':
            return self.multiline_basic() if self.peek(3) == '"""' else self.basic_string()
        if c == "'":
            return self.multiline_literal() if self.peek(3) == "'''" else self.literal_string()
        if c == "[":
            return self.array()
        if c == "{":
            return self.inline_table()
        if self.s.startswith("true", self.i):
            self.i += 4
            return True
        if self.s.startswith("false", self.i):
            self.i += 5
            return False
        m = _DATETIME.match(self.s, self.i)
        if m and not (m.group(2) is None and _TIME.match(self.s, self.i)):
            return self.date_time(m)
        m = _TIME.match(self.s, self.i)
        if m:
            self.i = m.end()
            try:
                return time.fromisoformat(m.group(0)[:15]) if "." in m.group(0) else time.fromisoformat(m.group(0))
            except ValueError:
                self.fail("bad time")
        m = _SPECIAL.match(self.s, self.i)
        if m:
            self.i = m.end()
            return float(m.group(0))
        m = _PREFIXED.match(self.s, self.i)
        if m:
            self.i = m.end()
            return int(m.group(0).replace("_", ""), 0)
        m = _FLOAT.match(self.s, self.i)
        if m and m.group(0) and (m.group(0) != _INT.match(self.s, self.i).group(0)):
            self.i = m.end()
            return float(m.group(0).replace("_", ""))
        m = _INT.match(self.s, self.i)
        if m and m.group(0):
            self.i = m.end()
            return int(m.group(0).replace("_", ""))
        self.fail("expected a value")

    def date_time(self, m):
        self.i = m.end()
        try:
            return self._date_time(m)
        except ValueError:   # a day that does not exist, an offset past 24 h: the reader's own error with a position, not a traceback
            self.fail("bad date or time")

    def _date_time(self, m):
        d = date.fromisoformat(m.group(1))
        if m.group(2) is None:
            return d
        hms = m.group(2)
        if "." in hms:   # fromisoformat before 3.11 wants exactly 3 or 6 fraction digits
            head, frac = hms.split(".")
            hms = f"{head}.{(frac + '000000')[:6]}"
        t = time.fromisoformat(hms)
        dt = datetime.combine(d, t)
        z = m.group(3)
        if z:
            if z in ("Z", "z"):
                tz = timezone.utc
            else:
                sign = 1 if z[0] == "+" else -1
                tz = timezone(sign * timedelta(hours=int(z[1:3]), minutes=int(z[4:6])))
            dt = dt.replace(tzinfo=tz)
        return dt

    def basic_string(self):
        self.i += 1
        out = []
        while True:
            c = self.peek()
            if not c or c == "\n":
                self.fail("unterminated string")
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\\":
                out.append(self.escape())
                continue
            if (c < " " and c != "\t") or c == "\x7f":   # a tab is allowed in a basic string
                self.fail("control character in string")
            out.append(c)
            self.i += 1

    def escape(self):
        self.i += 1
        c = self.peek()
        if c in _ESCAPES:
            self.i += 1
            return _ESCAPES[c]
        if c in ("u", "U"):
            n = 4 if c == "u" else 8
            hexs = self.s[self.i + 1:self.i + 1 + n]
            if len(hexs) != n or not re.fullmatch(r"[0-9A-Fa-f]+", hexs):
                self.fail("bad unicode escape")
            self.i += 1 + n
            try:
                return chr(int(hexs, 16))
            except ValueError:
                self.fail("bad unicode escape")
        self.fail("bad escape")

    def literal_string(self):
        self.i += 1
        j = self.s.find("'", self.i)
        if j < 0 or "\n" in self.s[self.i:j]:
            self.fail("unterminated literal string")
        seg = self.s[self.i:j]
        if re.search(r"[\x00-\x08\x0a-\x1f\x7f]", seg):
            self.fail("control character in string")
        self.i = j + 1
        return seg

    def multiline_basic(self):
        self.i += 3
        if self.peek() == "\n":
            self.i += 1
        out = []
        while True:
            c = self.peek()
            if not c:
                self.fail("unterminated multi-line string")
            if self.peek(3) == '"""':
                extra = 0   # up to two quotes may sit right before the closing three
                while self.peek(4 + extra) == '"' * (4 + extra) and extra < 2:
                    extra += 1
                out.append('"' * extra)
                self.i += 3 + extra
                return "".join(out)
            if c == "\\":
                nxt = self.s[self.i + 1:self.i + 2]
                if nxt in ("\n", " ", "\t") and self.s[self.i + 1:].lstrip(" \t").startswith("\n"):   # line-ending backslash
                    self.i += 1
                    while self.peek() in (" ", "\t", "\n") and self.peek():
                        self.i += 1
                    continue
                out.append(self.escape())
                continue
            if (c < " " and c not in "\n\t") or c == "\x7f":
                self.fail("control character in string")
            out.append(c)
            self.i += 1

    def multiline_literal(self):
        self.i += 3
        if self.peek() == "\n":
            self.i += 1
        j = self.s.find("'''", self.i)
        if j < 0:
            self.fail("unterminated multi-line literal string")
        extra = 0   # up to two quotes may sit right before the closing three ('''a''''' is a'')
        while extra < 2 and self.s[j + 3 + extra:j + 4 + extra] == "'":
            extra += 1
        seg = self.s[self.i:j + extra]
        if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", seg):
            self.fail("control character in string")
        self.i = j + 3 + extra
        return seg

    def array(self):
        self.i += 1
        out = []
        self.inline.add(id(out))
        while True:
            self.skip_ws_comments_newlines()
            if self.peek() == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.skip_ws_comments_newlines()
            c = self.peek()
            if c == ",":
                self.i += 1
                continue
            if c == "]":
                self.i += 1
                return out
            self.fail("expected , or ] in array")

    def inline_table(self):
        self.i += 1
        out = {}
        self.inline.add(id(out))
        self.skip_ws()
        if self.peek() == "}":
            self.i += 1
            return out
        while True:
            self.skip_ws()
            self.key_value(out)
            self.skip_ws()
            c = self.peek()
            if c == ",":
                self.i += 1
                continue
            if c == "}":
                self.i += 1
                return out
            self.fail("expected , or } in inline table")
