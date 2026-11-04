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
            if lang == 'flow':
                svg = flow_svg(code)
                if svg:
                    out.append(svg)
                    continue
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


# ---- ```flow: a small diagram from plain lines, as escaped inline SVG (no library, no outside request) --------------------

_ARROW = re.compile(r'\s*->\s*')
_BAR = re.compile(r'^([^:]{1,40}?)\s*:\s*(\d+(?:\.\d+)?)\s*$')
_CH, _BOX_H, _GAP, _ROW, _BAR_H = 6.6, 34, 30, 50, 22   # px per character at 12px, box height, arrow length, row pitch, bar pitch
_FONT = 'font: 12px system-ui, -apple-system, sans-serif'


def _esc_svg(s):
    return html.escape(s, quote=True)


def flow_svg(code):
    """A ```flow block as one inline SVG, or '' when no line parses. A line `A -> B -> C` is a row of boxes joined by arrows;
    a line `label: 12` is a bar, scaled against the largest bar in the block. Every string is escaped, colours are the page's
    CSS variables (so it follows light and dark), and the SVG scales to its container's width."""
    rows, bars = [], []
    for raw in code:
        line = raw.strip()
        if not line:
            continue
        m = _BAR.match(line)
        if m and '->' not in line:
            bars.append((m.group(1).strip(), float(m.group(2))))
        elif '->' in line:
            steps = [s.strip() for s in _ARROW.split(line) if s.strip()]
            if steps:
                rows.append(steps)
    if not rows and not bars:
        return ''
    parts, y, width = [], 8, 0
    for steps in rows:
        x = 2
        for k, s in enumerate(steps):
            w = max(64, round(len(s) * _CH) + 20)
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{_BOX_H}" rx="8" style="fill:var(--surface);stroke:var(--line)"/>'
                         f'<text x="{x + w / 2:.0f}" y="{y + _BOX_H / 2 + 1:.0f}" text-anchor="middle" dominant-baseline="middle" style="{_FONT};fill:var(--text)">{_esc_svg(s)}</text>')
            x += w
            if k < len(steps) - 1:
                cy = y + _BOX_H / 2
                parts.append(f'<path d="M{x + 4} {cy:.0f} H{x + _GAP - 8}" style="stroke:var(--muted);stroke-width:1.5;fill:none"/>'
                             f'<path d="M{x + _GAP - 10} {cy - 4:.0f} L{x + _GAP - 4} {cy:.0f} L{x + _GAP - 10} {cy + 4:.0f} Z" style="fill:var(--muted)"/>')
                x += _GAP
        width = max(width, x + 2)
        y += _ROW
    if bars:
        label_w = max(round(len(l) * _CH) for l, _ in bars) + 12
        big = max(v for _, v in bars) or 1
        bar_x = 2 + label_w
        bar_w = max(120, (width or 300) - bar_x - 44)
        for label, v in bars:
            fill = max(2, round(bar_w * v / big))
            parts.append(f'<text x="{2 + label_w - 8}" y="{y + _BAR_H / 2:.0f}" text-anchor="end" dominant-baseline="middle" style="{_FONT};fill:var(--muted)">{_esc_svg(label)}</text>'
                         f'<rect x="{bar_x}" y="{y + 4}" width="{fill}" height="{_BAR_H - 8}" rx="4" style="fill:var(--info)"/>'
                         f'<text x="{bar_x + fill + 6}" y="{y + _BAR_H / 2:.0f}" dominant-baseline="middle" style="{_FONT};fill:var(--text)">{v:g}</text>')
            y += _BAR_H
        width = max(width, bar_x + bar_w + 44)
    height = y + 4
    return (f'<svg class="flow" role="img" aria-label="diagram" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'style="display:block;max-width:100%;height:auto">{"".join(parts)}</svg>')


# ---- the review template: Changed / Checked / Next, split out so the panel can lay them out ---------------------------------

_NAMES = (('changed', ('changed', 'did', 'built', 'done', 'what changed')),
          ('checked', ('checked', 'tested', 'verified', 'tests', 'checks', 'proof')),
          ('next', ('next', 'then', 'for you', 'action', 'to do')))
_SEC_HEAD = re.compile(r'^(?:#{1,6}\s*(.+?)\s*#*|\*\*(.+?)\*\*:?)\s*$')
_ARW_LINE = re.compile(r'^(ACTION|STATUS|WHY)\s+\S')


def sections(md):
    """The agent's body split on its Changed / Checked / Next headings (`## Changed`, `**Checked**`, a few spellings each):
    {'changed', 'checked', 'next': html of that section, 'flow': the first ```flow block as SVG, 'rest': html of everything
    else, 'has': whether any of the three was found}. A body without the headings is all `rest`, so an agent that skips the
    template still gets a sensible card."""
    buckets = {'changed': [], 'checked': [], 'next': [], 'rest': []}
    cur, flow, fence, arw = 'rest', None, None, []
    lines = (md or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines and (_ARW_LINE.match(lines[0]) or (arw and not lines[0].strip())):   # STATUS / WHY lines of a multi-line summary belong with the sentence
        if lines[0].strip():
            arw.append(lines[0].strip())
        lines.pop(0)
    for line in lines:
        s = line.strip()
        if fence is not None:
            if _FENCE.match(s):
                if fence == 'flow' and flow is None:
                    flow = fence_lines
                else:
                    buckets[cur].extend(['```' + fence, *fence_lines, '```'])
                fence = None
            else:
                fence_lines.append(line)
            continue
        if _FENCE.match(s):
            fence, fence_lines = s[3:].strip(), []
            continue
        m = _SEC_HEAD.match(s)
        if m:
            name = (m.group(1) or m.group(2) or '').strip(' :').lower()
            hit = next((k for k, spellings in _NAMES if any(name == sp or name.startswith(sp + ' ') for sp in spellings)), None)
            if hit:
                cur = hit
                continue
            cur = 'rest'
        buckets[cur].append(line)
    if fence is not None:   # unterminated fence: keep its lines as text
        buckets[cur].extend(['```' + fence, *fence_lines])
    out = {k: to_html('\n'.join(v).strip()) for k, v in buckets.items()}
    out['flow'] = flow_svg(flow) if flow else ''
    out['arw'] = '\n'.join(arw)   # plain text, for the panel's ACTION / STATUS / WHY reader (it escapes)
    out['has'] = any(out[k] for k in ('changed', 'checked', 'next'))
    return out
