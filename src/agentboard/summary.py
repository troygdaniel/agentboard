"""Done summary: the finished cards as one page (and one text block) that is pleasant to read and to paste into a message.

Grouped by project, then by day; a plain-words headline per project; one line per card (title plus the agent's one-sentence result);
counts, a small strip of cards closed per day (stacked by agent) and a lane per agent. Everything an agent wrote is escaped.
Read-only: it never writes to the board. Served at /summary (?since=1d|7d|30d|all&project=<id>) and printed by `agentboard summary`."""
import html
import re
import zlib
from datetime import date, datetime, timedelta

from . import hud
from .store import BoardError

DEFAULT_SINCE = "7d"
LINE_MAX = 150
TEXT_MAX = 12      # cards per project in the text version; the rest is a count
DAY_SHOWN = 6      # cards per day shown in the page; the rest opens under "more"
PALETTE = {"green": "#2f9e63", "blue": "#2f6fed", "red": "#d1453b", "orange": "#e08a1e", "yellow": "#c9a227", "purple": "#8b5cf6",
           "pink": "#d6409f", "cyan": "#18a0b5", "gray": "#8a8f9a", "grey": "#8a8f9a", "brown": "#9a6b3f"}
FALLBACK = ["#2f6fed", "#2f9e63", "#e08a1e", "#8b5cf6", "#d6409f", "#18a0b5", "#d1453b", "#c9a227"]


def parse_since(text, today=None):
    """'1d' = today only, '7d' = the last 7 days including today, 'all' = no limit. Returns the first day included, or None."""
    today = today or date.today()
    t = (text or DEFAULT_SINCE).strip().lower()
    if t == "all":
        return None
    m = re.fullmatch(r"(\d{1,4})d", t)
    if not m or int(m.group(1)) < 1:
        raise BoardError(f"invalid --since '{text}'; use 1d, 7d, 30d or all")
    return today - timedelta(days=int(m.group(1)) - 1)


def one_line(result, title=""):
    """The agent's one sentence for a card: the STATUS part of an ACTION/STATUS/WHY report, else its first sentence, never long."""
    r = re.sub(r"\s+", " ", str(result or "")).strip()
    m = re.search(r"\bSTATUS\b[:\s]*(.*?)(?=\s\bWHY\b|$)", r)
    if m and m.group(1).strip():
        r = m.group(1).strip()
    else:
        r = re.sub(r"^ACTION\b[:\s]*(none\b[.:\s]*)?", "", r, flags=re.I).strip()
        r = re.sub(r"^(Troy|ORCH|AGENT-\d+):\s*", "", r)
    r = re.sub(r"^[a-z0-9][a-z0-9-]*\s+(?:done-ready|blocked|\d+%)\s*[:.,;\-]?\s*", "", r)   # "card-id done-ready," prefix
    first = re.split(r"(?<=[.!?])\s+(?=[A-Z])", r, maxsplit=1)[0]
    first = first.strip()
    if len(first) > LINE_MAX:
        first = first[:LINE_MAX - 1].rstrip() + "…"
    return first


def agent_color(name, color, taken=()):
    """The agent's own colour when it is distinct on this page, else the next free one from the palette (lanes must be tellable apart)."""
    own = PALETTE.get(color) or (color if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else None)
    if own and own not in taken:
        return own
    free = [c for c in FALLBACK if c not in taken]
    return (free or FALLBACK)[zlib.crc32((name or "").encode()) % len(free or FALLBACK)]


def collect(tasks, projects, since="7d", project=None, today=None):
    """{'days': [date...], 'projects': [{id, name, cards: {day: [card]}, count}], 'agents': {...}, 'total', 'per_day': {day: {agent: n}}}"""
    today = today or date.today()
    first = parse_since(since, today)
    names = {p["id"]: p.get("name") or p["id"] for p in projects}
    if project and project not in names and not any(t.get("project_id") == project for t in tasks):
        raise BoardError(f"no such project '{project}'")
    by_proj, per_day, agents = {}, {}, {}
    for t in tasks:
        if t.get("status") != "done" or t.get("parent_id"):
            continue
        pid = t.get("project_id") or ""
        if project and pid != project:
            continue
        at = hud._marked_at(t) or hud._t(t.get("updated"))
        if not at or at.date() > today or (first and at.date() < first):
            continue
        agent = t.get("agent") or "Unassigned"
        card = {"id": t["id"], "title": t["title"], "line": one_line(t.get("result") or t.get("status_text"), t["title"]),
                "agent": agent, "at": at}
        agents.setdefault(agent, {"n": 0, "color": agent_color(agent, t.get("color"), {a["color"] for a in agents.values()})})["n"] += 1
        per_day.setdefault(at.date(), {}).setdefault(agent, 0)
        per_day[at.date()][agent] += 1
        by_proj.setdefault(pid, {}).setdefault(at.date(), []).append(card)
    out = []
    for pid, days in by_proj.items():
        for d in days.values():
            d.sort(key=lambda c: c["at"], reverse=True)
        out.append({"id": pid, "name": names.get(pid) or ("No project" if not pid else pid), "days": days,
                    "count": sum(len(v) for v in days.values())})
    out.sort(key=lambda p: (-p["count"], p["name"].lower()))
    span = sorted(per_day)
    lo = first or (span[0] if span else today)
    days = [lo + timedelta(days=i) for i in range((today - lo).days + 1)] if (today - lo).days < 120 else span
    return {"since": since, "first": first, "today": today, "days": days, "projects": out, "agents": agents,
            "per_day": per_day, "total": sum(p["count"] for p in out)}


def _s(n):
    return "" if n == 1 else "s"


def headline(p, today):
    """One plain sentence for a project: how many cards closed, over how many days, and who did them."""
    who = sorted({c["agent"] for d in p["days"].values() for c in d})
    n, nd = p["count"], len(p["days"])
    day0 = next(iter(p["days"]))
    when = "today" if list(p["days"]) == [today] else f"over {nd} days" if nd > 1 else "yesterday" if day0 == today - timedelta(days=1) else f"on {_day_label(day0, today)}"
    by = who[0] if len(who) == 1 else f"{len(who)} agents"
    return f"{n} card{_s(n)} finished {when}, by {by}."


def _day_label(d, today):
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%a %d %b")


def to_text(data):
    """The same summary as plain text (markdown-ish), for a message or a daily log."""
    today = data["today"]
    span = "all time" if data["first"] is None else "today" if data["first"] == today else f"{data['first'].strftime('%d %b')} to {today.strftime('%d %b')}"
    lines = [f"# Done: {span}", ""]
    if not data["total"]:
        return "\n".join(lines + ["Nothing finished in this window.", ""])
    n_agents = len(data["agents"])
    lines += [f"**{data['total']} card{_s(data['total'])}** finished across {len(data['projects'])} project{_s(len(data['projects']))} by {n_agents} agent{_s(n_agents)}.", ""]
    for p in data["projects"]:
        lines += [f"## {p['name']}", headline(p, today), ""]
        left = TEXT_MAX
        for d in sorted(p["days"], reverse=True):
            if left <= 0:
                break
            lines.append(f"**{_day_label(d, today)}**")
            for c in p["days"][d][:left]:
                lines.append(f"- {c['title']}" + (f": {c['line']}" if c["line"] else "") + f" ({c['agent']})")
            left -= len(p["days"][d])
            lines.append("")
        if left < 0:
            lines += [f"...and {-left} more.", ""]
    return "\n".join(lines).rstrip() + "\n"


CSS = """
:root{color-scheme:light dark;--bg:#fafaf8;--fg:#17171a;--mut:#6b6b73;--line:#e2e2de;--card:#fff;--ok:#1d7a4a;--ac:#2f6fed}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1116;--fg:#ececf1;--mut:#9aa0ad;--line:#262b36;--card:#151a22;--ok:#4cc38a;--ac:#7aa2ff}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0e1116;--fg:#ececf1;--mut:#9aa0ad;--line:#262b36;--card:#151a22;--ok:#4cc38a;--ac:#7aa2ff}:root[data-theme="light"]{color-scheme:light}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:52rem;margin:0 auto;padding:20px 16px 56px}h1{font-size:24px;line-height:1.25;margin:0}.meta{color:var(--mut);font-size:14px;margin:2px 0 0}
.top{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}.acts{display:flex;gap:8px;flex-wrap:wrap}
button,.btn{font:inherit;font-size:14px;border-radius:10px;border:1px solid var(--line);padding:8px 14px;min-height:44px;background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}
.seg{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0 0}.seg a{padding:6px 14px;border:1px solid var(--line);border-radius:99px;font-size:14px;text-decoration:none;color:var(--mut);background:var(--card);min-height:36px;display:inline-flex;align-items:center}
.seg a.on{color:var(--fg);border-color:var(--ac);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(7.5rem,1fr));gap:10px;margin:16px 0 0}.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.tile b{display:block;font-size:28px;line-height:1.1;font-variant-numeric:tabular-nums}.tile span{font-size:12px;color:var(--mut)}.tile.good b{color:var(--ok)}
h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:26px 0 8px}
.strip{display:flex;align-items:flex-end;gap:6px;height:96px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px 0}
.col{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:flex-end;align-items:stretch;height:100%}.col .stack{display:flex;flex-direction:column-reverse;border-radius:4px 4px 0 0;overflow:hidden}
.col .stack i{display:block}.col u{display:block;text-decoration:none;text-align:center;font-size:11px;color:var(--mut);padding:3px 0;white-space:nowrap;overflow:hidden}
.col em{font-style:normal;font-size:11px;text-align:center;color:var(--mut);font-variant-numeric:tabular-nums}
.lanes{display:grid;gap:6px;margin:6px 0}.lane{display:grid;grid-template-columns:7rem 1fr 2rem;gap:8px;align-items:center;font-size:14px}.lane i{display:block;height:10px;border-radius:5px}.lane span:last-child{text-align:right;font-variant-numeric:tabular-nums}
.proj{margin:22px 0 0;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}.proj h3{margin:0;font-size:19px;display:flex;gap:8px;align-items:baseline;justify-content:space-between}
.proj h3 .n{font-size:13px;color:var(--mut);font-weight:400}.proj .hl{margin:2px 0 6px;color:var(--mut);font-size:15px}
.day{font-size:12px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--mut);margin:12px 0 4px}
ul{list-style:none;margin:0;padding:0}li{display:flex;gap:10px;align-items:baseline;padding:5px 0;border-top:1px solid var(--line)}li:first-of-type{border-top:0}
.dot{flex:none;width:9px;height:9px;border-radius:50%;margin-top:.45em;position:relative;top:0}.t{min-width:0;overflow-wrap:anywhere}.t b{font-weight:600}.t span{color:var(--mut);font-size:14px}
.day .n{font-weight:400}details summary{cursor:pointer;color:var(--mut);font-size:14px;min-height:36px;display:flex;align-items:center}.none{color:var(--mut)}#msg{color:var(--mut);font-size:14px;margin:8px 0 0}
@media print{.acts,.seg,#msg{display:none}}
"""

JS = """
try { const t = localStorage.getItem('agentboard-theme'); if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t); } catch (e) {}
const msg = document.getElementById('msg');
const text = document.getElementById('txt').content.textContent;
document.getElementById('copy').onclick = async () => {
  try { await navigator.clipboard.writeText(text); msg.textContent = 'Copied as text.'; }
  catch (e) { msg.textContent = 'Could not copy here; use Save as HTML.'; }
};
document.getElementById('save').onclick = () => {
  const doc = document.documentElement.cloneNode(true);
  doc.querySelectorAll('.acts,.seg,script,#msg').forEach(n => n.remove());
  const blob = new Blob(['<!doctype html>' + doc.outerHTML], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'done-summary.html'; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  msg.textContent = 'Saved as done-summary.html.';
};
"""


def _strip(data):
    """Cards closed per day as stacked bars, one stack per day, coloured by agent."""
    days = data["days"]
    if not days:
        return ""
    peak = max([sum(v.values()) for v in data["per_day"].values()] or [1])
    cols = []
    for d in days:
        counts = data["per_day"].get(d, {})
        total = sum(counts.values())
        segs = "".join(f'<i style="height:{round(56 * n / peak)}px;background:{data["agents"][a]["color"]}" title="{html.escape(a)}: {n}"></i>'
                       for a, n in sorted(counts.items()))
        label = d.strftime("%d") if len(days) > 7 else d.strftime("%a")[:2]
        cols.append(f'<div class="col" title="{d.strftime("%d %b")}: {total}"><em>{total or ""}</em><div class="stack">{segs}</div><u>{label}</u></div>')
    return '<div class="strip" role="img" aria-label="Cards closed per day">' + "".join(cols) + "</div>"


def _lanes(data):
    peak = max((a["n"] for a in data["agents"].values()), default=1)
    return '<div class="lanes">' + "".join(
        f'<div class="lane"><span>{html.escape(n)}</span><i style="width:{max(4, round(100 * a["n"] / peak))}%;background:{a["color"]}"></i><span>{a["n"]}</span></div>'
        for n, a in sorted(data["agents"].items(), key=lambda kv: -kv[1]["n"])) + "</div>"


def build_html(data, base=""):
    e = html.escape
    today = data["today"]
    cur = data["since"] or DEFAULT_SINCE
    proj = data.get("project") or ""
    qp = f"&project={e(proj)}" if proj else ""
    seg = "".join(f'<a href="{e(base)}/summary?since={v}{qp}"{" class=on" if v == cur else ""}>{lab}</a>'
                  for v, lab in (("1d", "Today"), ("7d", "7 days"), ("30d", "30 days"), ("all", "All")))
    span = "all time" if data["first"] is None else "today" if data["first"] == today else f"{data['first'].strftime('%d %b')} to {today.strftime('%d %b')}"
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">',
             f"<title>Done summary</title><style>{CSS}</style></head><body><main>",
             f'<div class="top"><div><h1>Done summary</h1><p class="meta">{e(span)}</p></div>'
             '<div class="acts"><button id="copy" type="button">Copy text</button><button id="save" type="button">Save as HTML</button>'
             f'<a class="btn" href="{e(base)}/">Board</a></div></div><p id="msg" role="status"></p><div class="seg">{seg}</div>']
    if not data["total"]:
        parts.append('<p class="none">Nothing finished in this window.</p>')
    else:
        n_ag, n_pr = len(data["agents"]), len(data["projects"])
        parts.append('<div class="tiles">' + f'<div class="tile good"><b>{data["total"]}</b><span>cards finished</span></div>'
                     f'<div class="tile"><b>{n_pr}</b><span>project{_s(n_pr)}</span></div><div class="tile"><b>{n_ag}</b><span>agent{_s(n_ag)}</span></div></div>')
        parts.append("<h2>Closed per day</h2>" + _strip(data))
        parts.append("<h2>By agent</h2>" + _lanes(data))
        for p in data["projects"]:
            parts.append(f'<section class="proj"><h3><span>{e(p["name"])}</span><span class="n">{p["count"]}</span></h3><p class="hl">{e(headline(p, today))}</p>')
            for d in sorted(p["days"], reverse=True):
                cards = p["days"][d]
                parts.append(f'<div class="day">{e(_day_label(d, today))} <span class="n">{len(cards)}</span></div><ul>')
                for i, c in enumerate(cards):
                    if i == DAY_SHOWN:
                        parts.append(f'</ul><details><summary>{len(cards) - DAY_SHOWN} more</summary><ul>')
                    col = data["agents"][c["agent"]]["color"]
                    parts.append(f'<li><span class="dot" style="background:{col}" title="{e(c["agent"])}"></span><div class="t"><b>{e(c["title"])}</b>'
                                 + (f' <span>{e(c["line"])}</span>' if c["line"] else "") + "</div></li>")
                parts.append("</ul></details>" if len(cards) > DAY_SHOWN else "</ul>")
            parts.append("</section>")
    parts.append(f'<template id="txt">{e(to_text(data))}</template><script>{JS}</script></main></body></html>')
    return "".join(parts)


def build(store, since=DEFAULT_SINCE, project=None, today=None):
    data = collect(store.load(), store.load_projects(), since, project, today)
    data["project"] = project or ""
    return data
