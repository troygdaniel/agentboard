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
