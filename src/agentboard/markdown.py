"""Minimal markdown -> HTML for agent-submitted ask/review bodies.

Agent output is untrusted, so this never passes raw HTML through: every line of
text is html-escaped before any tag is generated, and the only tags that can
appear in the output are the fixed set this module emits itself. That makes
sanitization a byproduct of construction rather than a separate pass. Supports
just enough markdown for a recap/diff/report: headings, bold/italic, inline
code, fenced code blocks (so diffs keep their whitespace), links (http/https
only), lists, blockquotes, horizontal rules, and paragraphs.
"""
import html
import re

_FENCE = re.compile(r'^```')
_HEADING = re.compile(r'^(#{1,6})\s+(.*)$')
_HR = re.compile(r'^(-{3,}|\*{3,}|_{3,})$')
_QUOTE = re.compile(r'^>\s?(.*)$')
_UL = re.compile(r'^[-*]\s+(.*)$')
_OL = re.compile(r'^\d+\.\s+(.*)$')
_LANG = re.compile(r'^[\w-]+$')

_ALIGN_CELL = re.compile(r':?-+:?')
_ALIGN_CLASS = {(True, True): ' class="al-c"', (True, False): ' class="al-l"', (False, True): ' class="al-r"'}

_INLINE_CODE = re.compile(r'`([^`]+)`')
_LINK = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')
_BOLD = re.compile(r'\*\*(.+?)\*\*|__(.+?)__')
# emphasis only opens next to a non-word, non-space character, and closes the same way: snake_case_names
# and "2 * 3 * 4" stay as typed, while *this* and _this_ still work
_ITALIC = re.compile(r'(?<![\w*])\*(?![\s*])([^*]+?)(?<![\s*])\*(?![\w*])|(?<![\w_])_(?![\s_])([^_]+?)(?<![\s_])_(?![\w_])')


def _inline(text):
    text = html.escape(text)
    # code spans are verbatim: lift them out before any other rule runs, put them back at the end
    spans = []

    def stash(m):
        spans.append(f'<code>{m.group(1)}</code>')
        return f'\x00{len(spans) - 1}\x00'

    text = _INLINE_CODE.sub(stash, text.replace('\x00', ''))
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>', text)
    text = _BOLD.sub(lambda m: f'<strong>{m.group(1) or m.group(2)}</strong>', text)
    text = _ITALIC.sub(lambda m: f'<em>{m.group(1) or m.group(2)}</em>', text)
    return re.sub(r'\x00(\d+)\x00', lambda m: spans[int(m.group(1))], text)


def _cells(line):
    """Cells of a table row: leading/trailing pipes optional, \\| stays inside its cell."""
    row = line.strip()
    if row.startswith('|'):
        row = row[1:]
    parts = re.split(r'(?<!\\)\|', row)
    if len(parts) > 1 and parts[-1].strip() == '':
        parts.pop()   # the trailing pipe
    return [p.strip().replace('\\|', '|') for p in parts]


def _table_start(lines, i):
    """Alignment spec if lines[i] is a header row and lines[i + 1] its |---|:-:| separator, else None."""
    if i + 1 >= len(lines) or '|' not in lines[i] or '|' not in lines[i + 1]:
        return None
    head, sep = _cells(lines[i]), _cells(lines[i + 1])
    if len(head) != len(sep) or not all(_ALIGN_CELL.fullmatch(c) for c in sep):
        return None
    return [_ALIGN_CLASS.get((c.startswith(':'), c.endswith(':')), '') for c in sep]


def _table(lines, i, align):
    """(html, next index) for the table whose header is lines[i]."""
    def row(tag, cells):
        cells = (cells + [''] * len(align))[:len(align)]   # ragged rows are padded / trimmed to the header
        return '<tr>' + ''.join(f'<{tag}{a}>{_inline(c)}</{tag}>' for c, a in zip(cells, align)) + '</tr>'

    head = row('th', _cells(lines[i]))
    i += 2
    body = []
    while i < len(lines) and lines[i].strip() and not _FENCE.match(lines[i].strip()):   # like GFM: until a blank line
        body.append(row('td', _cells(lines[i])))
        i += 1
    return (f'<div class="md-table"><table><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>', i)


def to_html(md):
    if not md:
        return ''
    lines = md.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out, para, in_list = [], [], None
    i, n = 0, len(lines)

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f'</{in_list}>')
            in_list = None

    def flush_para():
        if para:
            out.append('<p>' + '<br>'.join(_inline(l) for l in para) + '</p>')
            para.clear()

    while i < n:
        stripped = lines[i].strip()

        if _FENCE.match(stripped):
            flush_para(); close_list()
            lang = stripped[3:].strip()
            code = []
            i += 1
            while i < n and not _FENCE.match(lines[i].strip()):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence (or run off the end if unterminated)
            cls = f' class="lang-{html.escape(lang)}"' if lang and _LANG.match(lang) else ''
            out.append(f'<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>')
            continue

        if not stripped:
            flush_para(); close_list()
            i += 1
            continue

        align = _table_start(lines, i)
        if align:
            flush_para(); close_list()
            html_table, i = _table(lines, i, align)
            out.append(html_table)
            continue

        m = _HEADING.match(stripped)
        if m:
            flush_para(); close_list()
            level = len(m.group(1))
            out.append(f'<h{level}>{_inline(m.group(2))}</h{level}>')
            i += 1
            continue

        if _HR.match(stripped):
            flush_para(); close_list()
            out.append('<hr>')
            i += 1
            continue

        m = _QUOTE.match(stripped)
        if m:
            flush_para(); close_list()
            quote = [m.group(1)]
            i += 1
            while i < n and _QUOTE.match(lines[i].strip()):
                quote.append(_QUOTE.match(lines[i].strip()).group(1))
                i += 1
            out.append('<blockquote>' + '<br>'.join(_inline(l) for l in quote) + '</blockquote>')
            continue

        ul, ol = _UL.match(stripped), _OL.match(stripped)
        if ul or ol:
            flush_para()
            tag = 'ul' if ul else 'ol'
            if in_list != tag:
                close_list()
                out.append(f'<{tag}>')
                in_list = tag
            out.append(f'<li>{_inline((ul or ol).group(1))}</li>')
            i += 1
            continue

        close_list()
        para.append(stripped)
        i += 1

    flush_para(); close_list()
    return ''.join(out)
