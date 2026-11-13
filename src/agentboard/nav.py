"""One top bar for every page: the board, the by-agent view, the HUD, the Done summary, the reports list and each card report share
the same brand and the same three tabs, so moving between them never feels like leaving the product. The board draws the same markup in index.html;
the server-rendered pages take it from here. Links are same-origin only, prefixed with the board's base path."""
import html

TABS = (("need", "Now", "/need"), ("watch", "Watch", "/watch"), ("board", "Map", "/"))

LOGO = ('<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><rect x="1.5" y="2" width="3.5" height="12" rx="1.2" fill="currentColor" opacity=".35"/>'
        '<rect x="6.25" y="2" width="3.5" height="8" rx="1.2" fill="currentColor"/><rect x="11" y="2" width="3.5" height="5" rx="1.2" fill="currentColor" opacity=".6"/></svg>')

# the same look on the summary and report pages (their tokens: --bg --fg --mut --line --card --ac), 44px targets, wraps on a phone
# One geometry on all four pages (the board's header and the HUD bar use the same numbers in index.html): the bar is 28px in from the
# left and 21px down to a 44px row, the brand takes a fixed 106px slot, so the tab row starts at 148px across and 24px down, the same size
# and the same widths whichever tab is lit (the lit one changes colour and ring, never weight).
CSS = (".ab-top{display:flex;align-items:center;gap:8px 14px;flex-wrap:wrap;padding:21px 28px 14px;min-height:44px;box-sizing:content-box;border-bottom:1px solid var(--line);background:var(--bg)}"
       ".ab-brand{display:inline-flex;align-items:center;gap:9px;flex:0 0 106px;min-height:24px;font-weight:600;font-size:15px;line-height:1.5;color:var(--fg);text-decoration:none;letter-spacing:-.015em}"
       ".ab-tabs{display:inline-flex;gap:2px;margin:3px 0;padding:3px;border:1px solid var(--line);border-radius:10px;background:var(--card)}"
       ".ab-tabs .tab{display:inline-flex;align-items:center;min-height:30px;padding:0 12px;border-radius:7px;font-size:14px;font-weight:400;color:var(--mut);text-decoration:none;white-space:nowrap}"
       ".ab-tabs .tab:hover{color:var(--fg);background:var(--bg)}.ab-tabs .tab.on{color:var(--fg);background:var(--bg);box-shadow:inset 0 0 0 1px var(--line)}"
       ".ab-tabs .tab:focus-visible{outline:2px solid var(--ac);outline-offset:1px}.ab-ctx{color:var(--mut);font-size:13px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
       "@media(max-width:600px){.ab-top{padding:21px 16px 14px}.ab-tabs .tab{padding:0 9px;font-size:13px}}@media print{.ab-top{display:none}}")


def tabs(base="", active=""):
    """The tabs, the active one marked (none on the summary and reports pages: their links live in the board's Done column), every link under `base` ('' or '/b/<name>')."""
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
