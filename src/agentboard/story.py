"""The Story page (/story): a plain-language, scrolling overview of the work, five scenes, built from card data with templates.

No model call, no network, nothing started: it reads the board's own cards and writes sentences from fixed templates, so it works on the
work profile exactly as it does at home. One scene at a time:

  1. The week: one headline sentence and a ring (done this week, in progress, waiting).
  2. The flow: Waiting -> Working -> Done, every card a dot, one colour per theme.
  3. The themes: one card per theme, a one-line sentence and "n of m done".
  4. Needs you: only what is waiting on the owner (or a calm "nothing").
  5. The days: what was finished each day, as a small timeline.

A theme is a work area named by a word that several card titles share (summary.themes, the same rule as the Done summary); when no word is shared
the cards are grouped by who is on them. A subtask is part of its card and is not a card of its own. Backlog ("Later") cards are parked, so they
are not part of the story."""
import html
from datetime import datetime, timedelta

from . import hud, nav, summary
from .store import DEFAULT_OWNER

DAYS = 7            # "this week": the window for finished cards in scenes 1 to 3
TIMELINE_DAYS = 14  # scene 5
MAX_DOTS = 60       # dots drawn per stage in scene 2; the rest is "+N"
MAX_THEMES = 8      # theme cards drawn in scene 3; the rest is a line
TITLE_MAX = 72
STATES = ("waiting", "working", "needs", "done")   # needs = working, but waiting on the owner

SCENES = (("s1", "The week"), ("s2", "The flow"), ("s3", "The themes"), ("s4", "Needs you"), ("s5", "The days"))


def _s(n):
    return "" if n == 1 else "s"


def _short(text, n=TITLE_MAX):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def collect(tasks, now=None, owner=DEFAULT_OWNER, days=DAYS, timeline_days=TIMELINE_DAYS):
    """{'cards': [{id, title, state, agent, at}], 'themes': [{name, slot, cards, counts, n, m, line}], 'counts': {state: n}, 'needs': [row],
    'timeline': [(date, n)], 'days', 'today', 'owner'}. Pure: the same tasks give the same story."""
    now = now or datetime.now()
    today = now.date()
    first = today - timedelta(days=days - 1)
    by_id = {t["id"]: t for t in tasks}
    needs = [a for a in hud.actions(tasks, now=now, owner=owner) if a["who"] == owner]
    needs_ids = {a["id"] for a in needs}
    cards, per_day = [], {}
    for t in tasks:
        if t.get("parent_id") in by_id:   # a subtask is part of its card
            continue
        status = t.get("status")
        at = hud._marked_at(t) or hud._t(t.get("updated"))
        if status == "done":
            if not at or at.date() > today:
                continue
            per_day[at.date()] = per_day.get(at.date(), 0) + 1
            if at.date() < first:
                continue
            state = "done"
        elif t.get("archived"):
            continue
        elif status == "doing":
            state = "needs" if t["id"] in needs_ids else "working"
        elif status == "todo":
            state = "waiting"
        else:
            continue   # backlog is parked
        cards.append({"id": t["id"], "title": str(t.get("title") or t["id"]), "state": state, "agent": t.get("agent") or "", "at": at or datetime.min})
    counts = {s: sum(1 for c in cards if c["state"] == s) for s in STATES}
    themes = _themes(cards, owner)
    timeline = [(today - timedelta(days=i), per_day.get(today - timedelta(days=i), 0)) for i in range(timeline_days - 1, -1, -1)]
    return {"cards": cards, "themes": themes, "counts": counts, "needs": needs, "timeline": timeline, "days": days, "today": today, "owner": owner}


def _themes(cards, owner):
    if not cards:
        return []
    out = summary.themes(cards, "", owner)
    if len(out) == 1 and not out[0]["name"]:   # no word is shared: group by who is on the cards instead
        by = {}
        for c in cards:
            by.setdefault(c["agent"], []).append(c)
        out = [{"name": a or "Queue", "cards": sorted(v, key=lambda c: c["at"], reverse=True)} for a, v in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    for i, th in enumerate(out):
        th["slot"] = "sg" if th["name"] == "Other" else f"s{i % len(summary.SLOTS)}"
        th["counts"] = {s: sum(1 for c in th["cards"] if c["state"] == s) for s in STATES}
        th["m"] = len(th["cards"])
        th["n"] = th["counts"]["done"]
        th["line"] = plain(th, owner)
        for c in th["cards"]:
            c["slot"] = th["slot"]
    return out


def _bare(title, theme_name):
    """The title without a leading 'Theme:' that only repeats the theme the sentence is already about."""
    head = theme_name.lower() + ":"
    return title[len(head):].strip() if theme_name and title.lower().startswith(head) and len(title) > len(head) else title


def plain(theme, owner=DEFAULT_OWNER):
    """One sentence in plain words for a theme, from its newest card of the state that matters most."""
    cards, c = theme["cards"], theme["counts"]
    short = lambda title: _short(_bare(title, theme["name"]))

    def pick(state):
        return next(x for x in cards if x["state"] == state)   # cards are newest first

    if c["needs"]:
        return f"Waiting on {owner}: {short(pick('needs')['title'])}"
    if c["working"]:
        x = pick("working")
        return (f"{x['agent']} is on " if x["agent"] else "Working on ") + short(x["title"])
    if c["waiting"]:
        return f"Next up: {short(pick('waiting')['title'])}"
    return f"All finished; the last was {short(cards[0]['title'])}"


def headline(data):
    c, days, owner = data["counts"], data["days"], data["owner"]
    live = c["working"] + c["needs"] + c["waiting"]
    if not c["done"] and not live:
        return "Quiet right now: nothing in progress or waiting." if any(n for _d, n in data["timeline"]) else "Nothing on the board yet."
    parts = []
    if c["done"]:
        parts.append(f"{c['done']} card{_s(c['done'])} finished in the last {days} days")
    else:
        parts.append(f"Nothing finished in the last {days} days")
    parts.append(f"{c['working'] + c['needs']} in progress")
    parts.append(f"{c['waiting']} waiting to start")
    text = ", ".join(parts[:-1]) + " and " + parts[-1] + "."
    if c["needs"]:
        text += f" {c['needs']} of them {'needs' if c['needs'] == 1 else 'need'} {owner}."
    return text


# -- the page -----------------------------------------------------------------------------------------------------------------------------
DARK = summary.DARK + ";--wait:#f0b429"
CSS = f"""
:root{{color-scheme:light dark;--bg:#fafaf8;--fg:#17171a;--mut:#6b6b73;--line:#e2e2de;--card:#fff;--ok:#1d7a4a;--ac:#1d4ed8;--on-ac:#fff;--dim:#d6d6d1;--gr:#8a8f9a;--wait:#b26a00}}
{summary._slot_css("", False)}.sg{{--c:var(--gr)}}
@media(prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{DARK}}}{summary._slot_css(':root:not([data-theme="light"]) ', True)}}}
:root[data-theme="dark"]{{color-scheme:dark;{DARK}}}{summary._slot_css(':root[data-theme="dark"] ', True)}:root[data-theme="light"]{{color-scheme:light}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-snap-type:y proximity}}.ab-top{{scroll-snap-align:start}}   /* the bar is a snap point too: the page opens at the top, with the tabs, not snapped down to scene 1 */
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:56rem;margin:0 auto;padding:0 16px 40px}}
.scene{{min-height:min(84vh,44rem);display:flex;flex-direction:column;justify-content:center;gap:18px;padding:32px 0;scroll-snap-align:start;scroll-margin-top:8px;border-bottom:1px solid var(--line)}}
.scene:last-child{{border-bottom:0}}
.kicker{{margin:0;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}}
h1,h2{{margin:0;font-weight:600;letter-spacing:-.015em;line-height:1.2}}h1{{font-size:clamp(26px,4.6vw,40px)}}h2{{font-size:clamp(22px,3.6vw,30px)}}
.lede{{margin:0;color:var(--mut);font-size:17px;max-width:40rem}}
.rise{{transition:opacity .6s ease,transform .6s ease}}
.js .scene:not(.in) .rise{{opacity:0;transform:translateY(14px)}}
/* scene 1: the ring */
.week{{display:flex;gap:28px;align-items:center;flex-wrap:wrap}}
.ring{{width:200px;height:200px;flex:0 0 auto}}.ring circle{{fill:none;stroke-width:11}}.ring .track{{stroke:var(--line)}}
.ring .arc{{transition:stroke-dasharray 1s ease .15s}}.js .scene:not(.in) .ring .arc{{stroke-dasharray:0 100!important}}
.ring text{{fill:var(--fg);font:600 26px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-anchor:middle}}.ring .sub{{fill:var(--mut);font-size:9px;font-weight:400}}
.key{{display:flex;flex-direction:column;gap:8px;margin:0;padding:0;list-style:none}}
.key li{{display:flex;gap:10px;align-items:center;font-size:16px}}.key b{{font-variant-numeric:tabular-nums;min-width:1.6em}}
.sw{{width:12px;height:12px;border-radius:4px;flex:0 0 auto;background:var(--c)}}.c-done{{--c:var(--ok)}}.c-working{{--c:var(--ac)}}.c-waiting{{--c:var(--wait)}}
.arc.c-done{{stroke:var(--ok)}}.arc.c-working{{stroke:var(--ac)}}.arc.c-waiting{{stroke:var(--wait)}}
/* scene 2: the flow */
.flow{{display:flex;align-items:stretch;gap:10px}}
.stage{{flex:1 1 0;min-width:0;background:var(--card);border:1px solid var(--line);border-top:4px solid var(--c);border-radius:14px;padding:12px 14px 16px}}
.stage h3{{margin:0 0 12px;font-size:14px;font-weight:600;display:flex;justify-content:space-between;gap:8px}}.stage h3 span{{color:var(--mut);font-weight:400;font-variant-numeric:tabular-nums}}
.dots{{display:flex;flex-wrap:wrap;gap:7px;margin:0;padding:0;list-style:none;min-height:18px}}.dot{{display:block;width:16px;height:16px;border-radius:50%;background:var(--c)}}
.more{{font-size:13px;color:var(--mut);align-self:center}}.empty{{font-size:14px;color:var(--mut);margin:0}}
.arrow{{align-self:center;flex:0 0 auto;color:var(--mut);font-size:22px;line-height:1}}
.legend{{display:flex;gap:6px 14px;flex-wrap:wrap;margin:0;padding:0;list-style:none;font-size:14px;color:var(--mut)}}.legend li{{display:inline-flex;gap:7px;align-items:center}}.legend i{{display:block;width:12px;height:12px;border-radius:50%;background:var(--c)}}
/* scene 3: the themes */
.themes{{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:12px;margin:0;padding:0;list-style:none}}
.theme{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--c);border-radius:14px;padding:12px 14px;display:flex;flex-direction:column;gap:8px}}
.theme h3{{margin:0;font-size:17px}}.theme p{{margin:0;font-size:15px;color:var(--mut);overflow-wrap:anywhere}}
.meter{{display:flex;gap:10px;align-items:center;font-size:14px;font-variant-numeric:tabular-nums}}.bar{{flex:1;height:8px;border-radius:99px;background:var(--line);overflow:hidden}}.bar i{{display:block;height:100%;background:var(--c);border-radius:99px;transition:width .9s ease .2s}}
.js .scene:not(.in) .bar i{{width:0!important}}
.note{{margin:0;font-size:14px;color:var(--mut)}}
/* scene 4: needs you */
.needs{{display:flex;flex-direction:column;gap:10px;margin:0;padding:0;list-style:none}}
.need{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--wait);border-radius:14px;padding:12px 14px}}
.need .tag{{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--wait);font-weight:600}}.need .tag em{{font-style:normal;text-transform:none;letter-spacing:0;font-weight:400;color:var(--mut);font-size:13px}}.need b{{display:block;font-size:17px;font-weight:600}}.need span{{color:var(--mut);font-size:15px;overflow-wrap:anywhere}}
.calm{{display:flex;gap:14px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;font-size:18px}}.calm i{{width:14px;height:14px;border-radius:50%;background:var(--ok);flex:0 0 auto}}
/* scene 5: the days */
.days{{display:flex;align-items:flex-end;gap:6px;height:190px;margin:0 0 16px;padding:0;list-style:none}}
.day{{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:6px;font-size:12px;color:var(--mut)}}
.day .col{{width:100%;max-width:34px;background:var(--ok);border-radius:6px 6px 2px 2px;min-height:3px;opacity:.9;transition:height .8s ease .2s}}.day.zero .col{{background:var(--dim)}}
.js .scene:not(.in) .day .col{{height:3px!important}}
.day .lab{{position:relative}}.day .lab small{{position:absolute;top:100%;left:50%;transform:translateX(-50%);font-size:10px;letter-spacing:.04em;text-transform:uppercase}}
.day b{{color:var(--fg);font-weight:600;font-variant-numeric:tabular-nums;font-size:13px}}.day.today .lab{{color:var(--fg);font-weight:600}}
/* the scene dots */
.pager{{position:fixed;right:14px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:4px;z-index:5}}
.pager a{{display:grid;place-items:center;width:24px;height:24px;border-radius:50%}}.pager a::before{{content:"";width:12px;height:12px;border-radius:50%;background:var(--dim);transition:background .3s}}
.pager a:hover::before{{background:var(--mut)}}.pager a.on::before{{background:var(--ac)}}.pager a:focus-visible{{outline:2px solid var(--ac);outline-offset:1px}}
@media(max-width:760px){{.pager{{display:none}}.flow{{flex-direction:column}}.arrow{{transform:rotate(90deg)}}.ring{{width:170px;height:170px}}.days{{height:150px;gap:3px}}.day .lab{{font-size:10px}}.scene{{min-height:0;padding:28px 0}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto;scroll-snap-type:none}}*,*::before,*::after{{transition:none!important;animation:none!important}}}}
@media print{{.pager{{display:none}}html{{scroll-snap-type:none}}.scene{{min-height:0;break-inside:avoid}}}}
"""

JS = r"""
try { const t = localStorage.getItem('agentboard-theme'); if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t); } catch (e) {}
(() => {
  const scenes = [...document.querySelectorAll('.scene')], dots = [...document.querySelectorAll('.pager a')];
  const still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;   // no entrance: everything is simply there
  if (still || !('IntersectionObserver' in window)) scenes.forEach(s => s.classList.add('in'));
  if (!('IntersectionObserver' in window)) return;
  if (!still) document.documentElement.classList.add('js');
  const seen = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); seen.unobserve(e.target); } }), { threshold: .25 });
  const here = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) dots.forEach(d => d.classList.toggle('on', d.getAttribute('href') === '#' + e.target.id)); }), { threshold: .5 });
  scenes.forEach(s => { seen.observe(s); here.observe(s); });
})();
"""


def _ring(data):
    c = data["counts"]
    total = c["done"] + c["working"] + c["needs"] + c["waiting"]
    if not total:
        return '<svg class="ring" viewBox="0 0 120 120" role="img" aria-label="Nothing on the board yet"><circle class="track" cx="60" cy="60" r="50"/></svg>'
    segs = (("done", c["done"]), ("working", c["working"] + c["needs"]), ("waiting", c["waiting"]))
    arcs, start = [], 0.0
    for key, n in segs:
        if not n:
            continue
        pct = 100.0 * n / total
        arcs.append(f'<circle class="arc c-{key}" cx="60" cy="60" r="50" pathLength="100" transform="rotate(-90 60 60)" '
                    f'style="stroke-dasharray:{max(pct - 0.6, 0.4):.2f} {100 - max(pct - 0.6, 0.4):.2f};stroke-dashoffset:{-start:.2f}"/>')
        start += pct
    pct_done = round(100.0 * c["done"] / total)
    label = f"{c['done']} finished, {c['working'] + c['needs']} in progress, {c['waiting']} waiting, of {total} cards"
    return (f'<svg class="ring" viewBox="0 0 120 120" role="img" aria-label="{html.escape(label)}"><circle class="track" cx="60" cy="60" r="50"/>' + "".join(arcs)
            + f'<text x="60" y="63">{pct_done}%</text><text class="sub" x="60" y="78">finished</text></svg>')


def _dots(cards, name):
    shown = cards[:MAX_DOTS]
    items = "".join(f'<li><i class="dot {c["slot"]}" title="{html.escape(_short(c["title"]))}"></i></li>' for c in shown)
    more = f'<li class="more">+{len(cards) - len(shown)} more</li>' if len(cards) > len(shown) else ""
    return f'<ul class="dots" aria-label="{html.escape(name)} cards">{items}{more}</ul>' if cards else '<p class="empty">No cards here.</p>'


def build_html(data, base=""):
    e = html.escape
    c, owner = data["counts"], data["owner"]
    total = c["done"] + c["working"] + c["needs"] + c["waiting"]
    nav_bar = nav.top_bar(base, "story", _span(data))
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>Story</title><style>{CSS}{nav.CSS}</style></head><body>{nav_bar}')
    pager = '<nav class="pager" aria-label="Scenes">' + "".join(f'<a href="#{sid}" aria-label="Scene {i}: {e(lab)}"></a>' for i, (sid, lab) in enumerate(SCENES, 1)) + "</nav>"
    if not total and not any(n for _d, n in data["timeline"]):
        body = ('<main><section class="scene in" id="s1"><p class="kicker">The story</p><h1>Nothing on the board yet.</h1>'
                '<p class="lede">Add a task, or let an agent report one, and this page tells the story of the work in plain words: what is finished, what is moving, what is waiting on you.</p></section></main>')
        return head + body + f"<script>{JS}</script></body></html>"
    # scene 1
    live = c["working"] + c["needs"]
    key = "".join(f'<li><i class="sw c-{k}"></i><b>{n}</b>{lab}</li>' for k, n, lab in (("done", c["done"], f"finished in {data['days']} days"), ("working", live, "in progress"), ("waiting", c["waiting"], "waiting to start")))
    s1 = (f'<section class="scene" id="s1"><p class="kicker rise">1 · The week</p><h1 class="rise">{e(headline(data))}</h1>'
          f'<div class="week rise">{_ring(data)}<ul class="key">{key}</ul></div></section>')
    # scene 2
    stages = []
    for stage, lab, cards in (("waiting", "Waiting", [x for x in data["cards"] if x["state"] == "waiting"]),
                              ("working", "Working", [x for x in data["cards"] if x["state"] in ("working", "needs")]),
                              ("done", "Done", [x for x in data["cards"] if x["state"] == "done"])):
        stages.append(f'<div class="stage c-{stage}"><h3>{lab}<span>{len(cards)}</span></h3>{_dots(cards, lab)}</div>')
    legend = "".join(f'<li><i class="{th["slot"]}"></i>{e(th["name"])}</li>' for th in data["themes"])
    s2 = ('<section class="scene" id="s2"><p class="kicker rise">2 · The flow</p><h2 class="rise">Work moves left to right.</h2>'
          '<p class="lede rise">Every dot is a card; its colour is its theme. Hover a dot for its title.</p>'
          f'<div class="flow rise">{stages[0]}<span class="arrow" aria-hidden="true">→</span>{stages[1]}<span class="arrow" aria-hidden="true">→</span>{stages[2]}</div>'
          f'<ul class="legend rise" aria-label="Themes">{legend}</ul></section>')
    # scene 3
    cards3 = []
    for th in data["themes"][:MAX_THEMES]:
        pct = round(100.0 * th["n"] / th["m"]) if th["m"] else 0
        cards3.append(f'<li class="theme {th["slot"]}"><h3>{e(th["name"])}</h3><p>{e(th["line"])}</p>'
                      f'<div class="meter"><span class="bar" role="img" aria-label="{th["n"]} of {th["m"]} done"><i style="width:{pct}%"></i></span><span>{th["n"]} of {th["m"]} done</span></div></li>')
    rest = len(data["themes"]) - MAX_THEMES
    s3 = ('<section class="scene" id="s3"><p class="kicker rise">3 · The themes</p><h2 class="rise">What the work is about.</h2>'
          + (f'<ul class="themes rise">{"".join(cards3)}</ul>' if cards3 else '<p class="note rise">Themes appear when cards share a word or an agent.</p>') + (f'<p class="note rise">and {rest} more theme{_s(rest)}</p>' if rest > 0 else "") + "</section>")
    # scene 4
    if data["needs"]:
        kinds = {"ask": "Question", "review": "Ready for you", "stale": "Gone quiet"}
        rows = "".join(f'<li class="need"><span class="tag">{kinds.get(n["kind"], n["kind"])}<em> · {e(n["agent"])}'
                       + (f' · waiting {e(hud.dur(n["age_min"]))}' if n.get("age_min") is not None else "")
                       + f'</em></span><b>{e(_short(n["title"]))}</b><span>{e(_short(n["what"], 140))}</span></li>' for n in data["needs"])
        s4 = (f'<section class="scene" id="s4"><p class="kicker rise">4 · Needs {e(owner)}</p><h2 class="rise">{len(data["needs"])} thing{_s(len(data["needs"]))} waiting on {e(owner)}.</h2>'
              f'<ul class="needs rise">{rows}</ul></section>')
    else:
        s4 = (f'<section class="scene" id="s4"><p class="kicker rise">4 · Needs {e(owner)}</p><h2 class="rise">Nothing is waiting on {e(owner)}.</h2>'
              '<div class="calm rise"><i></i><span>Every question is answered and every finished card is signed off.</span></div></section>')
    # scene 5
    peak = max([n for _d, n in data["timeline"]] + [1])
    day_items = "".join(f'<li class="day{" today" if d == data["today"] else ""}{" zero" if not n else ""}" title="{d.strftime("%a %b %d").replace(" 0", " ")}: {n} finished">'
                        f'<b>{n if n else ""}</b><i class="col" style="height:{max(3, round(100.0 * n / peak * 0.72))}%"></i><span class="lab">{d.day}'
                        + (f'<small>{d.strftime("%b")}</small>' if d.day == 1 or d == data["timeline"][0][0] else "") + '</span></li>' for d, n in data["timeline"])
    total_days = sum(n for _d, n in data["timeline"])
    best = max(data["timeline"], key=lambda dn: dn[1])
    sentence = (f"{total_days} card{_s(total_days)} finished in {len(data['timeline'])} days; the busiest day was {best[0].strftime('%A %b ')}{best[0].day} with {best[1]}."
                if total_days else f"Nothing finished in the last {len(data['timeline'])} days.")
    s5 = ('<section class="scene" id="s5"><p class="kicker rise">5 · The days</p><h2 class="rise">What got finished, day by day.</h2>'
          f'<p class="lede rise">{e(sentence)}</p><ol class="days rise" aria-label="Cards finished per day">{day_items}</ol></section>')
    return head + pager + f"<main>{s1}{s2}{s3}{s4}{s5}</main><script>{JS}</script></body></html>"


def _span(data):
    return f"last {data['days']} days"


def build(store, now=None):
    return collect(store.load_all(), now=now, owner=store.owner)
