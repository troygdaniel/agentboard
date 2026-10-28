"""Done summary: what was actually done, as one page (and one text block) that can be understood at a glance.

It is about the work, not the management of it. Each project is split into work areas (themes found in the card titles) and each
card is tagged by the kind of change (added, fixed, improved, tested, documented, explored). A card row shows the title and the
outcome in one line; it opens to what was asked, the full result, the timeline and links to the board card and its report.
One stacked bar per project shows the mix of kinds; a search box and a kind filter scope the whole page. Colours come from a
validated categorical palette (light and dark) and every colour sits beside its word. Everything an agent wrote is escaped.
Read-only: it never writes to the board. Served at /summary (?since=1d|7d|30d|all&project=<id>) and printed by `agentboard summary`."""
import html
import json
import re
from datetime import date, timedelta

from . import hud
from .store import BoardError

DEFAULT_SINCE = "7d"
LINE_MAX = 150
TEXT_MAX = 12       # cards per project in the text version; the rest is a count
THEME_SHOWN = 5     # cards per work area shown in the page; the rest opens under "more"
OTHER_SHOWN = 3     # the same for the cards that fit no area
MAX_THEMES = 7
DESC_MAX = 600
LOG_MAX = 12
# Kinds of change, in the order they are tried on the title; the slot is the palette colour (dataviz reference palette, validated)
KINDS = [
    ("Explored", 6, r"\b(investigat|look into|audit|research|propose|brainstorm|ideas?\b|find and|compare|spike|explore|evaluate|assess)"),
    ("Tested", 3, r"\b(tests?\b|testing|qa\b|ci\b|verif|e2e|coverage|dry run|fixtures?|smoke|load test|strict mode)"),
    ("Fixed", 1, r"\b(fix|bug|broken|crash|flak|fail|regress|wrong|collid|overlap|leak|error|stale|missing|glitch|jump|too (tall|small|big|wide|slow|long)|no longer|not (working|showing)|rough edge|follow-?ups?)"),
    ("Documented", 4, r"\b(readme|docs?\b|document|write.?up|guide|changelog|security\.md|notes?\b|decisions?\.md|spec\b)"),
    ("Added", 0, r"\b(add|new|ship|implement|introduc|support|enable|create|build|first|launch|v\d|wire|hook up|integrat)"),
    ("Improved", 2, r"\b(improv|better|polish|clean|tighten|faster|speed|refactor|simplif|less|more|rework|redesign|restyle|consolidat|easier|clearer|nicer|warmth|coheren|obvious|scannable|readable|bigger|smaller|instant|smooth)"),
]
CHANGED = "Changed"
KIND_SLOT = {k: s for k, s, _ in KINDS}
KIND_RE = [(k, re.compile(p, re.I)) for k, _, p in KINDS]
SLOTS = [("blue", "#2a78d6", "#3987e5"), ("orange", "#eb6834", "#d95926"), ("aqua", "#1baf7a", "#199e70"), ("yellow", "#eda100", "#c98500"),
         ("magenta", "#e87ba4", "#d55181"), ("green", "#008300", "#008300"), ("violet", "#6250d6", "#9085e9"), ("red", "#e34948", "#e66767")]
STOP = set("""a an the and or but if so as at by be is are was were has have had do does did can could should would will its it's their our your his
her my we i you they he she this that these those there here than then too very from into onto over under after before out off about like same
still again back up down in on to of for with without within through during between across around via per vs not no yes now when where which who
what why how all any each every some more less most least own new old first last next only just also one two also card cards todo doing done review
agent agents orch troy claude session sessions pass passes plan phase part bug bugs ui ux idea ideas thing things stuff way bit lot fix fixed fixes
add added adds make makes made show shows give gives move moves run runs push pushes rename rewrite propose let keep put get set use open close look
find cut write draft check stop start tighten clean polish turn bring hide group list instead real small big little live main page pages work
today yesterday week ready needs need should must dont don't doesnt doesn't isnt isn't wont won't cant can't got go goes going gone take takes took
try tries tried fail fails failed flake flaky test tests testing not never always once twice""".split())


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


def kind_of(title):
    """The kind of change a card was, from its title: the first KINDS pattern that matches, else Changed."""
    for k, rx in KIND_RE:
        if rx.search(title or ""):
            return k
    return CHANGED


def asked(description, title):
    """What was asked, in one line: the first sentence of the card's description, unless it only repeats the title."""
    d = re.sub(r"\s+", " ", str(description or "")).strip()
    d = re.sub(r"^(Repo|Codebase|Project)\s+~?/?\S+\.?\s*", "", d)   # "Repo ~/dev/x." preamble
    d = re.sub(r"^\([^)]*\)[,.]?\s*(\w+ slice\.\s*)?", "", d)          # "(your worktree), places slice." preamble
    first = ""
    for sent in re.split(r"(?<=[.!?])\s+", d)[:3]:
        sent = sent.strip()
        if len(sent) >= 25 or (sent and not first):
            first = sent
            if len(sent) >= 25:
                break
    if not first or first.lower().rstrip(".") == (title or "").lower().rstrip("."):
        return ""
    return first if len(first) <= LINE_MAX else first[:LINE_MAX - 1].rstrip() + "…"


def _card(t, at):
    log = []
    for entry in (t.get("log") or []):
        if not isinstance(entry, dict):
            continue
        log.append({"at": hud._t(entry.get("at")), "status": str(entry.get("status") or ""), "progress": entry.get("progress"), "text": str(entry.get("text") or "")})
    desc = re.sub(r"[ \t]+\n", "\n", str(t.get("description") or "")).strip()
    if len(desc) > DESC_MAX:
        desc = desc[:DESC_MAX - 1].rstrip() + "…"
    report = t.get("report") if isinstance(t.get("report"), dict) else {}
    title = str(t.get("title") or t["id"])
    ask = asked(t.get("description"), title)
    kind = kind_of(title)
    if kind == CHANGED:     # the title did not say; the first line of what was asked usually does
        kind = kind_of(ask)
    return {"id": t["id"], "title": title, "line": one_line(t.get("result") or t.get("status_text"), title), "kind": kind,
            "asked": ask, "agent": t.get("agent") or "", "at": at,
            "result": str(t.get("result") or t.get("status_text") or "").strip(), "description": desc, "log": log[-LOG_MAX:],
            "report": str(report.get("file") or "")}


def _tokens(title):
    """(key, as written) for each word of a title that could name a work area."""
    out, seen = [], set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9'+./-]*", title or ""):
        k = w.lower().strip(".'-/")
        if len(k) < 3 or k in STOP or any(ch.isdigit() for ch in k):
            continue
        k = re.sub(r"(?<=[a-z])(ies|es|s)$", lambda m: "y" if m.group(1) == "ies" else "", k)   # calls/call, subtasks/subtask
        if len(k) < 3 or k in seen or k in STOP:
            continue
        seen.add(k)
        out.append((k, w.strip(".'-/")))
    return out


def themes(cards, project_name=""):
    """Split a project's cards into work areas: a word that several titles share names an area; the rest is 'Other'."""
    n = len(cards)
    skip = {k for k, _w in _tokens(project_name)} | {re.sub(r"[^a-z0-9]", "", project_name.lower())}
    toks = [[kw for kw in _tokens(c["title"]) if kw[0] not in skip] for c in cards]
    df, casing = {}, {}
    for ts in toks:
        for k, w in ts:
            df[k] = df.get(k, 0) + 1
            casing.setdefault(k, {})
            casing[k][w] = casing[k].get(w, 0) + 1
    min_df = 3 if n >= 8 else 2
    cands = {k for k, v in df.items() if v >= min_df and (n < 4 or v <= 0.6 * n)}
    groups = {}
    for c, ts in zip(cards, toks):
        best = max((k for k, _w in ts if k in cands), key=lambda k: df[k], default=None)
        groups.setdefault(best, []).append(c)
    named = [(k, v) for k, v in groups.items() if k is not None and len(v) >= 2]
    named.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    other = groups.get(None, []) + [c for k, v in groups.items() if k is not None and len(v) < 2 for c in v]
    other += [c for _k, v in named[MAX_THEMES:] for c in v]
    out = []
    for k, v in named[:MAX_THEMES]:
        label = max(casing[k].items(), key=lambda kv: kv[1])[0]
        out.append({"name": label if label[:1].isupper() else label[:1].upper() + label[1:], "cards": sorted(v, key=lambda c: c["at"], reverse=True)})
    if other:
        out.append({"name": "Other" if out else "", "cards": sorted(other, key=lambda c: c["at"], reverse=True)})
    return out


def collect(tasks, projects, since="7d", project=None, today=None):
    """{'projects': [{id, name, count, cards, themes: [{name, cards}], kinds: {kind: n}}], 'kinds': {kind: n}, 'total',
    'prev' (the same-length window before this one, or None), 'facts': [str], 'first', 'today', 'n_days'}"""
    today = today or date.today()
    first = parse_since(since, today)
    names = {p["id"]: p.get("name") or p["id"] for p in projects}
    if project and project not in names and not any(t.get("project_id") == project for t in tasks):
        raise BoardError(f"no such project '{project}'")
    n_days = (today - first).days + 1 if first else None
    prev_lo = first - timedelta(days=n_days) if first else None
    by_proj, prev = {}, 0
    for t in tasks:
        if t.get("status") != "done" or t.get("parent_id"):
            continue
        pid = t.get("project_id") or ""
        if project and pid != project:
            continue
        at = hud._marked_at(t) or hud._t(t.get("updated"))
        if not at or at.date() > today:
            continue
        if first and at.date() < first:
            if prev_lo and at.date() >= prev_lo:
                prev += 1
            continue
        by_proj.setdefault(pid, []).append(_card(t, at))
    out, kinds = [], {}
    for pid, cards in by_proj.items():
        cards.sort(key=lambda c: c["at"], reverse=True)
        pk = {}
        for c in cards:
            pk[c["kind"]] = pk.get(c["kind"], 0) + 1
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        name = names.get(pid) or ("No project" if not pid else pid)
        out.append({"id": pid, "name": name, "cards": cards, "count": len(cards), "themes": themes(cards, name), "kinds": pk})
    out.sort(key=lambda p: (-p["count"], p["name"].lower()))
    data = {"since": since, "first": first, "today": today, "n_days": n_days, "projects": out, "kinds": kinds,
            "total": sum(p["count"] for p in out), "prev": prev if first else None}
    data["facts"] = facts(data)
    return data


def _s(n):
    return "" if n == 1 else "s"


def _pct(n, total):
    return round(100 * n / total) if total else 0


def kind_order(kinds):
    """Kinds by count, Changed last."""
    return sorted(kinds, key=lambda k: (k == CHANGED, -kinds[k], k))


def facts(data):
    """Up to three short plain sentences about the work: where most of it went, what kind it mostly was, the biggest work area."""
    out, total = [], data["total"]
    if not total:
        return out
    if len(data["projects"]) > 1:
        p = data["projects"][0]
        out.append(f"Most of it: {p['name']} ({_pct(p['count'], total)}%).")
    ks = [k for k in kind_order(data["kinds"]) if k != CHANGED]
    if len(ks) > 1:
        a, b = ks[0], ks[1]
        out.append(f"Mostly {a.lower()} ({_pct(data['kinds'][a], total)}%) and {b.lower()} ({_pct(data['kinds'][b], total)}%).")
    areas = [(th, p) for p in data["projects"] for th in p["themes"] if th["name"] and th["name"] != "Other"]
    if areas:
        th, p = max(areas, key=lambda tp: len(tp[0]["cards"]))
        out.append(f"Biggest area: {th['name']} in {p['name']} ({len(th['cards'])}).")
    return out


def _span(data):
    today, first = data["today"], data["first"]
    return "all time" if first is None else "today" if first == today else f"{first.strftime('%d %b')} to {today.strftime('%d %b')}"


def to_text(data):
    """The same summary as plain text (markdown-ish), for a message or a daily log: project, work area, one line per card."""
    lines = [f"# Done: {_span(data)}", ""]
    if not data["total"]:
        return "\n".join(lines + ["Nothing finished in this window.", ""])
    n_pr = len(data["projects"])
    lines.append(f"**{data['total']} card{_s(data['total'])}** finished across {n_pr} project{_s(n_pr)}." + (" " + " ".join(data["facts"]) if data["facts"] else ""))
    lines.append("")
    for p in data["projects"]:
        lines += [f"## {p['name']} ({p['count']})", " · ".join(f"{k} {n}" for k, n in ((k, p["kinds"][k]) for k in kind_order(p["kinds"]))), ""]
        left = TEXT_MAX
        for th in p["themes"]:
            if left <= 0:
                break
            if th["name"]:
                lines.append(f"**{th['name']}**")
            for c in th["cards"][:left]:
                lines.append(f"- {c['title']}" + (f" — {c['line']}" if c["line"] else ""))
            left -= len(th["cards"])
            lines.append("")
        if left < 0:
            lines += [f"...and {-left} more.", ""]
    return "\n".join(lines).rstrip() + "\n"


def _mm(text):
    """Mermaid mindmap node text: brackets and parentheses would change the node shape, so they go."""
    return re.sub(r"\s+", " ", re.sub(r"[()\[\]{}\"`]", " ", str(text))).strip() or "-"


def to_mermaid(data):
    """The shape of the work as a Mermaid mindmap (window, projects, work areas with counts): paste into GitHub, Obsidian or Notion."""
    lines = ["mindmap", f"  root(({_mm('Done ' + _span(data))} {data['total']}))"]
    for p in data["projects"]:
        lines.append(f"    {_mm(p['name'])} {p['count']}")
        for th in p["themes"]:
            if th["name"]:
                lines.append(f"      {_mm(th['name'])} {len(th['cards'])}")
    return "\n".join(lines) + "\n"


def squarify(items, x, y, w, h):
    """Squarified treemap: items are (key, value) largest first; returns {key: (x, y, w, h)} filling the rectangle."""
    items = [(k, v) for k, v in items if v > 0]
    total = sum(v for _k, v in items)
    out = {}
    if not total or w <= 0 or h <= 0:
        return out
    vals = [(k, v * w * h / total) for k, v in items]

    def worst(row, side):
        s = sum(a for _k, a in row)
        return max(side * side * max(a for _k, a in row) / (s * s), s * s / (side * side * min(a for _k, a in row)))

    i = 0
    while i < len(vals):
        row, i = [vals[i]], i + 1
        side = min(w, h)
        while i < len(vals) and worst(row + [vals[i]], side) <= worst(row, side):
            row.append(vals[i])
            i += 1
        s = sum(a for _k, a in row)
        if w >= h:
            rw, yy = s / h, y
            for k, a in row:
                out[k] = (x, yy, rw, a / rw)
                yy += a / rw
            x, w = x + rw, w - rw
        else:
            rh, xx = s / w, x
            for k, a in row:
                out[k] = (xx, y, a / rh, rh)
                xx += a / rh
            y, h = y + rh, h - rh
    return out


MAP_W, MAP_H, PAD, BAND = 760, 300, 3, 18


def _aid(pid, i):
    return f"area-{_pid(pid)[5:]}-{i}"


def _dominant(cards):
    kinds = {}
    for c in cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    return max(kinds.items(), key=lambda kv: (kv[1], kv[0] != CHANGED))[0], kinds


def _map(data):
    """The work map: one tile per project, split into its work areas, each sized by cards and washed with its main kind of change."""
    e = html.escape
    rows = [(p["id"], p["count"]) for p in data["projects"]]
    if data["total"] < 2:
        return ""
    h = MAP_H if len(rows) > 1 else 200
    out = [f'<svg class="map" viewBox="0 0 {MAP_W} {h}" role="img" aria-label="Work map: projects and their work areas, sized by cards finished">']
    for p, (px, py, pw, ph) in ((p, squarify(rows, 0, 0, MAP_W, h)[p["id"]]) for p in data["projects"]):
        out.append(f'<g class="ptile"><rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" rx="6"/>')
        label = p["name"] if pw > 7.5 * len(p["name"]) + 12 else (p["name"][:max(1, int((pw - 12) / 7.5)) - 1] + "…" if pw > 40 else "")
        if label and ph > BAND + 6:
            out.append(f'<text x="{px + 8:.1f}" y="{py + 13:.1f}"><title>{e(p["name"])}: {p["count"]}</title>{e(label)} <tspan class="cnt">{p["count"]}</tspan></text>')
        areas = [(i, len(th["cards"])) for i, th in enumerate(p["themes"])]
        inner = squarify(areas, px + PAD, py + (BAND if label else PAD), pw - 2 * PAD, ph - (BAND if label else PAD) - PAD)
        for i, th in enumerate(p["themes"]):
            if i not in inner:
                continue
            x, y, w, hh = inner[i]
            kind, kinds = _dominant(th["cards"])
            name = th["name"] or "Other"
            n = len(th["cards"])
            tip = f'{name} in {p["name"]}: {n} card{_s(n)} (' + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])) + ")"
            fits = w > 6.6 * len(name) + 10 and hh > 18
            out.append(f'<a class="tile {_slot(kind)}" href="#{_aid(p["id"], i)}" data-kinds="{_attr(kinds)}" data-n="{n}"><rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{hh:.1f}" rx="4"/>'
                       f'<title>{e(tip)}</title>'
                       + (f'<text x="{x + 6:.1f}" y="{y + 14:.1f}">{e(name)}' + (f' <tspan class="cnt">{n}</tspan>' if w > 6.6 * len(name) + 30 else "") + "</text>" if fits else "")
                       + "</a>")
        out.append("</g>")
    return "".join(out) + "</svg>"


def _attr(obj):
    return html.escape(json.dumps(obj, separators=(",", ":")), quote=True)


def _slot_css(prefix, dark):
    return "".join(f"{prefix}.s{i}{{--c:{s[2] if dark else s[1]}}}" for i, s in enumerate(SLOTS))


DARK = "--bg:#0e1116;--fg:#ececf1;--mut:#9aa0ad;--line:#262b36;--card:#151a22;--ok:#4cc38a;--ac:#7aa2ff;--dim:#3a414d;--gr:#6b7280"

CSS = f"""
:root{{color-scheme:light dark;--bg:#fafaf8;--fg:#17171a;--mut:#6b6b73;--line:#e2e2de;--card:#fff;--ok:#1d7a4a;--ac:#2f6fed;--dim:#d6d6d1;--gr:#8a8f9a}}
{_slot_css("", False)}.sg{{--c:var(--gr)}}
@media(prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{DARK}}}{_slot_css(':root:not([data-theme="light"]) ', True)}}}
:root[data-theme="dark"]{{color-scheme:dark;{DARK}}}{_slot_css(':root[data-theme="dark"] ', True)}:root[data-theme="light"]{{color-scheme:light}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:56rem;margin:0 auto;padding:20px 16px 56px}}h1{{font-size:24px;line-height:1.25;margin:0}}.meta{{color:var(--mut);font-size:14px;margin:2px 0 0}}
.top{{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}}.acts{{display:flex;gap:8px;flex-wrap:wrap}}
button,.btn{{font:inherit;font-size:14px;border-radius:10px;border:1px solid var(--line);padding:8px 14px;min-height:44px;background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0 0}}.seg{{display:flex;gap:6px;flex-wrap:wrap}}
.seg a{{padding:6px 14px;border:1px solid var(--line);border-radius:99px;font-size:14px;text-decoration:none;color:var(--mut);background:var(--card);min-height:36px;display:inline-flex;align-items:center}}
.seg a.on{{color:var(--fg);border-color:var(--ac);font-weight:600}}
#q{{font:inherit;font-size:14px;border:1px solid var(--line);border-radius:99px;padding:6px 14px;min-height:36px;background:var(--card);color:var(--fg);flex:1;min-width:10rem}}
#clear{{min-height:36px;padding:6px 12px;border-radius:99px;display:none}}body.filtered #clear{{display:inline-flex}}
.hero{{display:flex;gap:10px 20px;align-items:flex-end;flex-wrap:wrap;margin:20px 0 0}}.hero .big{{font-size:56px;font-weight:600;line-height:1;color:var(--ok)}}
.hero .lab{{font-size:15px;color:var(--mut);padding-bottom:6px}}.hero .lab b{{color:var(--fg);font-weight:600}}
.facts{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}}.fact{{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:14px}}
body.filtered .facts{{opacity:.45}}
h2{{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:0 0 10px}}h2 small{{text-transform:none;letter-spacing:0;font-weight:400;margin-left:8px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin:16px 0 0}}
.kbar{{display:flex;gap:2px;height:14px;border-radius:4px;overflow:hidden;background:var(--bg)}}.kbar i{{display:block;background:var(--c);min-width:2px}}
.kbar i:hover{{filter:brightness(1.12)}}.proj .kbar{{height:8px;flex:1;min-width:8rem;max-width:22rem}}
.legend{{display:flex;gap:4px 6px;flex-wrap:wrap;margin:10px 0 0}}.lg{{display:inline-flex;gap:7px;align-items:center;font:inherit;font-size:14px;min-height:36px;padding:4px 12px 4px 10px;border:1px solid var(--line);border-radius:99px;background:none;color:var(--fg);cursor:pointer}}
.lg:hover{{background:var(--bg)}}.lg.on{{border-color:var(--ac);background:var(--bg);font-weight:600}}.lg i{{display:block;width:10px;height:10px;border-radius:3px;background:var(--c)}}
.lg .n{{color:var(--mut);font-variant-numeric:tabular-nums}}.hint{{font-size:12px;color:var(--mut);margin:8px 0 0}}
.mark.off{{background:var(--dim)!important}}
.proj{{margin:18px 0 0;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;scroll-margin-top:12px}}
.proj header{{display:flex;gap:8px 16px;align-items:center;flex-wrap:wrap}}.proj h3{{margin:0;font-size:19px}}.proj h3 .n{{font-size:14px;color:var(--mut);font-weight:400;margin-left:8px;font-variant-numeric:tabular-nums}}
.proj header .mix{{display:flex;align-items:center;gap:10px;flex:1;min-width:12rem;font-size:12px;color:var(--mut)}}
.mapwrap{{overflow-x:auto}}.map{{width:100%;height:auto;display:block;font-size:12px}}@media(max-width:600px){{.map{{min-width:600px}}}}.ptile>rect{{fill:none;stroke:var(--line);stroke-width:1}}.ptile>text{{fill:var(--fg);font-weight:600;font-size:13px}}
.tile rect{{fill:var(--c);fill-opacity:.3;stroke:var(--card);stroke-width:2}}.tile:hover rect,.tile:focus rect{{fill-opacity:.55}}.tile text{{fill:var(--fg);pointer-events:none}}
.map .cnt{{fill:var(--mut);font-size:11px;font-weight:400}}.tile.off rect{{fill:var(--dim);fill-opacity:.5}}.tile.off text{{fill:var(--mut)}}
details.theme{{margin:10px 0 0;border-top:1px solid var(--line)}}details.theme>summary{{list-style:none;display:grid;grid-template-columns:auto auto 1fr 7rem;gap:12px;align-items:center;min-height:44px;cursor:pointer;padding:4px 0}}
details.theme>summary:hover{{background:var(--bg)}}details.theme>summary::before{{content:"▸";color:var(--mut);font-size:12px;position:absolute;margin-left:-14px}}details.theme[open]>summary::before{{content:"▾"}}
.theme .an{{font-size:14px;font-weight:600}}.theme .n{{color:var(--mut);font-variant-numeric:tabular-nums;font-size:14px}}.theme .tb{{height:6px;border-radius:0 3px 3px 0;background:var(--s0,#2a78d6);opacity:.4;max-width:14rem}}
.theme>summary .kbar{{height:6px}}.proj .theme{{padding-left:14px}}
@media(max-width:600px){{details.theme>summary{{grid-template-columns:auto auto 1fr}}.theme>summary .kbar{{display:none}}}}
details.cd{{border-top:1px solid var(--line)}}details.cd summary{{list-style:none;display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:baseline;padding:7px 0;cursor:pointer;min-height:40px}}
summary::-webkit-details-marker{{display:none}}.cd summary:hover{{background:var(--bg)}}
.tag{{display:inline-flex;gap:5px;align-items:center;font-size:11px;color:var(--mut);width:6.2rem;white-space:nowrap}}.tag i{{width:9px;height:9px;border-radius:3px;background:var(--c);display:block;flex:none}}
.cd .t{{min-width:0}}.cd .t b{{font-weight:600;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}.cd[open] .t b{{display:block}}.cd .t span{{display:block;color:var(--mut);font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.cd .t span b{{font-weight:600;color:var(--fg)}}.cd[open] .t span{{white-space:normal}}.cd .who{{font-size:12px;color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums}}
.cd .body{{padding:2px 0 12px 0;font-size:14px}}.body h4{{margin:8px 0 2px;font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--mut);font-weight:600}}
.body p{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}.body .desc{{color:var(--mut)}}
.tl{{list-style:none;margin:2px 0 0;padding:0;border-left:2px solid var(--line)}}.tl li{{display:grid;grid-template-columns:3.4rem 3rem 1fr;gap:8px;padding:2px 0 2px 10px;font-size:13px;color:var(--mut);align-items:baseline}}
.tl li b{{color:var(--fg);font-weight:500;font-variant-numeric:tabular-nums}}.tl li span{{overflow-wrap:anywhere}}.links{{margin:10px 0 0;display:flex;gap:14px;flex-wrap:wrap}}.links a{{color:var(--ac)}}
details.more summary{{cursor:pointer;color:var(--mut);font-size:14px;min-height:36px;display:flex;align-items:center;list-style:none}}
.none{{color:var(--mut)}}#msg{{color:var(--mut);font-size:14px;margin:8px 0 0}}[hidden]{{display:none!important}}
@media(max-width:600px){{.tag{{width:auto}}.tag span{{display:none}}.cd .who{{display:none}}}}
@media print{{.acts,.filters,#msg,.hint{{display:none}}.cd .t span{{white-space:normal}}}}
"""

JS = """
try { const t = localStorage.getItem('agentboard-theme'); if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t); } catch (e) {}
const $ = s => document.querySelector(s), $$ = s => Array.from(document.querySelectorAll(s));
const msg = $('#msg'), text = $('#txt').content.textContent, total = Number(document.body.dataset.total || 0);
let focus = '', q = '';
function apply() {
  const qq = q.trim().toLowerCase(), on = !!(focus || qq);
  document.body.classList.toggle('filtered', on);
  $$('.lg').forEach(b => { b.classList.toggle('on', b.dataset.kind === focus); b.setAttribute('aria-pressed', b.dataset.kind === focus); });
  $$('.mark').forEach(m => m.classList.toggle('off', !!focus && m.dataset.kind !== focus));
  let shown = 0;
  $$('.cd').forEach(d => { const ok = (!focus || d.dataset.kind === focus) && (!qq || d.dataset.q.includes(qq)); d.hidden = !ok; if (ok) shown++; });
  $$('details.more').forEach(d => { d.open = on; const k = d.querySelectorAll('.cd:not([hidden])').length; d.hidden = !k; d.querySelector('summary').textContent = k + ' more'; });
  $$('.theme').forEach(g => { const k = g.querySelectorAll('.cd:not([hidden])').length; g.hidden = !k; g.querySelector('.n').textContent = k; if (on) g.open = true; else if (!g.dataset.user) g.open = false; });
  $$('.proj').forEach(p => { const k = p.querySelectorAll('.cd:not([hidden])').length; p.hidden = !k; p.querySelector('h3 .n').textContent = k; });
  $$('a.tile').forEach(a => { const k = focus ? (JSON.parse(a.dataset.kinds)[focus] || 0) : Number(a.dataset.n); a.classList.toggle('off', !!focus && !k); const c = a.querySelector('.cnt'); if (c) c.textContent = k; });
  $('#big').textContent = shown; $('#of').textContent = on && shown !== total ? ' of ' + total : '';
}
$$('.lg').forEach(b => b.onclick = () => { focus = focus === b.dataset.kind ? '' : b.dataset.kind; apply(); });
$$('.theme').forEach(g => g.addEventListener('toggle', () => { if (!document.body.classList.contains('filtered')) g.dataset.user = g.open ? '1' : ''; }));
$$('a.tile').forEach(a => a.onclick = e => { e.preventDefault(); const d = document.getElementById(a.getAttribute('href').slice(1)); if (!d) return; d.open = true; d.dataset.user = '1'; d.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
$('#copymm').onclick = async () => {
  try { await navigator.clipboard.writeText($('#mmd').content.textContent); msg.textContent = 'Copied a Mermaid mindmap; paste it where Mermaid renders (GitHub, Obsidian, Notion).'; }
  catch (e) { msg.textContent = 'Could not copy here; use Save as HTML.'; }
};
$('#q').oninput = e => { q = e.target.value; apply(); };
$('#clear').onclick = () => { focus = ''; q = ''; $('#q').value = ''; apply(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape' && (focus || q)) { focus = ''; q = ''; $('#q').value = ''; apply(); } });
$('#copy').onclick = async () => {
  try { await navigator.clipboard.writeText(text); msg.textContent = 'Copied as text.'; }
  catch (e) { msg.textContent = 'Could not copy here; use Save as HTML.'; }
};
$('#save').onclick = () => {
  const doc = document.documentElement.cloneNode(true);
  doc.querySelectorAll('.acts,.filters,script,#msg').forEach(n => n.remove());
  const blob = new Blob(['<!doctype html>' + doc.outerHTML], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'done-summary.html'; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  msg.textContent = 'Saved as done-summary.html.';
};
"""

NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?\s?(?:%|ms\b|s\b|sec\b|min\b|h\b|px\b|[KMG]B\b|of \d+|tests?\b|cards?\b|commits?\b|passes\b|pass\b|fails?\b|errors?\b|files?\b|lines?\b|scenarios?\b|x\b))")


def _hi(escaped):
    """Bold the measurable bits of an (already escaped) outcome line: 42 of 43, p95 1.7 s, 86%."""
    return NUM.sub(r"<b>\1</b>", escaped)


def _slot(kind):
    return f"s{KIND_SLOT[kind]}" if kind in KIND_SLOT else "sg"


def _kbar(kinds, total, label):
    e = html.escape
    segs = "".join(f'<i class="mark {_slot(k)}" data-kind="{e(k)}" style="flex:{n}" title="{e(k)}: {n} ({_pct(n, total)}%)"></i>' for k, n in ((k, kinds[k]) for k in kind_order(kinds)))
    return f'<div class="kbar" role="img" aria-label="{e(label)}">{segs}</div>'


def _legend(kinds):
    e = html.escape
    return '<div class="legend">' + "".join(
        f'<button type="button" class="lg" data-kind="{e(k)}" aria-pressed="false"><i class="{_slot(k)}"></i>{e(k)}<span class="n">{kinds[k]}</span></button>'
        for k in kind_order(kinds)) + '</div><p class="hint">Click a kind to see only those cards. Open a card for what was asked, the full result and its timeline.</p>'


def _pid(pid):
    return "proj-" + (re.sub(r"[^A-Za-z0-9_-]", "-", pid) or "none")


def _row(c, base):
    e = html.escape
    q = e((c["title"] + " " + c["line"] + " " + c["asked"] + " " + c["agent"]).lower(), quote=True)
    body = []
    if c["asked"] or c["description"]:
        body.append(f'<h4>Asked</h4><p class="desc">{e(c["description"] or c["asked"])}</p>')
    if c["result"]:
        body.append(f'<h4>Result</h4><p>{e(c["result"])}</p>')
    if c["log"]:
        items = "".join(f'<li><b>{e(l["at"].strftime("%d %b %H:%M")) if l["at"] else ""}</b><span>{e(l["status"])}{"" if l["progress"] is None else " " + str(l["progress"]) + "%"}</span><span>{e(l["text"])}</span></li>'
                        for l in c["log"])
        body.append(f'<h4>Timeline</h4><ul class="tl">{items}</ul>')
    links = f'<a href="{e(base)}/#{e(c["id"])}">Open on the board</a>' + (f'<a href="{e(base)}/reports/{e(c["report"])}">Report</a>' if c["report"] else "")
    who = c["at"].strftime("%d %b") + (f' · {e(c["agent"])}' if c["agent"] else "")
    return (f'<details class="cd" data-kind="{e(c["kind"])}" data-q="{q}"><summary><span class="tag"><i class="{_slot(c["kind"])}"></i><span>{e(c["kind"])}</span></span>'
            f'<div class="t"><b>{e(c["title"])}</b>' + (f'<span>{_hi(e(c["line"]))}</span>' if c["line"] else "") + f'</div><span class="who">{who}</span></summary>'
            f'<div class="body">{"".join(body)}<div class="links">{links}</div></div></details>')


def _project(p, base):
    e = html.escape
    parts = [f'<section class="proj" id="{_pid(p["id"])}"><header><h3>{e(p["name"])}<span class="n">{p["count"]}</span></h3>'
             f'<div class="mix">{_kbar(p["kinds"], p["count"], "Kinds of change in " + p["name"])}</div></header>']
    for i, th in enumerate(p["themes"]):
        cards, shown = th["cards"], THEME_SHOWN if th["name"] and th["name"] != "Other" else OTHER_SHOWN
        _kind, kinds = _dominant(cards)
        name = th["name"] or "Cards"
        parts.append(f'<details class="theme" id="{_aid(p["id"], i)}"><summary><span class="an">{e(name)}</span><span class="n">{len(cards)}</span>'
                     f'<span class="tb" style="width:{max(6, round(100 * len(cards) / p["count"]))}%"></span>{_kbar(kinds, len(cards), name + ": kinds of change")}</summary>')
        parts.append("".join(_row(c, base) for c in cards[:shown]))
        if len(cards) > shown:
            parts.append(f'<details class="more"><summary>{len(cards) - shown} more</summary>{"".join(_row(c, base) for c in cards[shown:])}</details>')
        parts.append("</details>")
    return "".join(parts) + "</section>"


def build_html(data, base=""):
    e = html.escape
    cur = data["since"] or DEFAULT_SINCE
    proj = data.get("project") or ""
    qp = f"&project={e(proj)}" if proj else ""
    seg = "".join(f'<a href="{e(base)}/summary?since={v}{qp}"{" class=on" if v == cur else ""}>{lab}</a>'
                  for v, lab in (("1d", "Today"), ("7d", "7 days"), ("30d", "30 days"), ("all", "All")))
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">',
             f'<title>Done summary</title><style>{CSS}</style></head><body data-total="{data["total"]}"><main>',
             f'<div class="top"><div><h1>Done summary</h1><p class="meta">{e(_span(data))}</p></div>'
             '<div class="acts"><button id="copy" type="button">Copy text</button><button id="copymm" type="button" title="A Mermaid mindmap of projects and work areas">Copy Mermaid</button><button id="save" type="button">Save as HTML</button>'
             f'<a class="btn" href="{e(base)}/">Board</a></div></div><p id="msg" role="status"></p>'
             f'<div class="filters"><div class="seg">{seg}</div><input id="q" type="search" placeholder="Search the work" aria-label="Search the work"><button id="clear" type="button">Clear</button></div>']
    if not data["total"]:
        parts.append('<p class="none">Nothing finished in this window.</p>')
    else:
        n_pr = len(data["projects"])
        parts.append(f'<div class="hero"><span class="big"><span id="big">{data["total"]}</span><span id="of"></span></span>'
                     f'<span class="lab"><b>cards finished</b> across {n_pr} project{_s(n_pr)}</span></div>')
        if data["facts"]:
            parts.append('<div class="facts">' + "".join(f'<span class="fact">{e(f)}</span>' for f in data["facts"]) + "</div>")
        parts.append(f'<div class="box"><h2>What kind of work</h2>{_kbar(data["kinds"], data["total"], "Kinds of change")}{_legend(data["kinds"])}</div>')
        m = _map(data)
        if m:
            parts.append(f'<div class="box"><h2>Where the work went<small>bigger is more; the colour is the main kind of change; click an area for its cards</small></h2><div class="mapwrap">{m}</div></div>')
        parts += [_project(p, base) for p in data["projects"]]
    parts.append(f'<template id="txt">{e(to_text(data))}</template><template id="mmd">{e(to_mermaid(data))}</template><script>{JS}</script></main></body></html>')
    return "".join(parts)


def build(store, since=DEFAULT_SINCE, project=None, today=None):
    data = collect(store.load(), store.load_projects(), since, project, today)
    data["project"] = project or ""
    return data
