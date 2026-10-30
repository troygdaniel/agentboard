"""One top bar for every page: the board, the HUD, the Done summary, the reports list and each card report share the same brand and
the same four tabs, so moving between them never feels like leaving the product. The board draws the same markup in index.html;
the server-rendered pages take it from here. Links are same-origin only, prefixed with the board's base path."""
import html

TABS = (("board", "Board", "/"), ("hud", "HUD", "/hud"), ("summary", "Summary", "/summary"), ("reports", "Reports", "/reports"))

LOGO = ('<svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><rect x="1.5" y="2" width="3.5" height="12" rx="1.2" fill="currentColor" opacity=".35"/>'
        '<rect x="6.25" y="2" width="3.5" height="8" rx="1.2" fill="currentColor"/><rect x="11" y="2" width="3.5" height="5" rx="1.2" fill="currentColor" opacity=".6"/></svg>')

# the same look on the summary and report pages (their tokens: --bg --fg --mut --line --card --ac), 44px targets, wraps on a phone
CSS = (".ab-top{display:flex;align-items:center;gap:6px 14px;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--bg)}"
       ".ab-brand{display:inline-flex;align-items:center;gap:8px;font-weight:600;font-size:15px;color:var(--fg);text-decoration:none;letter-spacing:-.01em;margin-right:4px}"
       ".ab-tabs{display:inline-flex;gap:2px;padding:3px;border:1px solid var(--line);border-radius:10px;background:var(--card)}"
       ".ab-tabs .tab{display:inline-flex;align-items:center;min-height:30px;padding:0 12px;border-radius:7px;font-size:14px;color:var(--mut);text-decoration:none;white-space:nowrap}"
       ".ab-tabs .tab:hover{color:var(--fg);background:var(--bg)}.ab-tabs .tab.on{color:var(--fg);background:var(--bg);font-weight:600;box-shadow:inset 0 0 0 1px var(--line)}"
       ".ab-tabs .tab:focus-visible{outline:2px solid var(--ac);outline-offset:1px}.ab-ctx{color:var(--mut);font-size:13px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
       "@media(max-width:600px){.ab-top{padding:8px 12px}.ab-tabs .tab{padding:0 9px;font-size:13px}}@media print{.ab-top{display:none}}")


def tabs(base="", active=""):
    """The four tabs, the active one marked, every link under `base` ('' or '/b/<name>')."""
    e = html.escape
    out = []
    for key, label, path in TABS:
        href = e(base) + ("/" if path == "/" and base else path if not (path == "/" and not base) else "/")
        out.append(f'<a class="tab{" on" if key == active else ""}" href="{href}"{" aria-current=page" if key == active else ""}>{label}</a>')
    return '<nav class="ab-tabs" aria-label="Pages">' + "".join(out) + "</nav>"


def top_bar(base="", active="", context=""):
    """The whole bar: brand (a link to the board), the tabs, and an optional line of context (the window, the card) on the right."""
    e = html.escape
    ctx = f'<span class="ab-ctx">{e(context)}</span>' if context else ""
    return f'<header class="ab-top"><a class="ab-brand" href="{e(base)}/">{LOGO}agentboard</a>{tabs(base, active)}{ctx}</header>'
