"""The end-of-day wrap-up: where every card stands tonight, and what happens to it.

`agentboard wrapup` sorts each Doing card into one of four outcomes and shows them as one page, read-only:
  finish   at 100% but never handed in: its agent should `review` it, with a Learned section
  needs    an ask or a review: it waits on the owner, and stays where it is
  carry    goes back to Todo tonight with its notes, in the order to start them tomorrow
  running  its agent is listening and has worked on it lately: left alone (`--all` releases it too)
`--ask` leaves each agent that owes one a note on its card (a checkpoint, or a review); `--apply` releases the carry cards, best first, so
tomorrow's top card is the one nearest done, and saves the page as `.agentboard/wrapups/<date>.md`; `--last` prints the newest one."""
import json
from datetime import datetime

from . import hud, listeners, prompt, rollup

ASK_MARK = "End of day:"   # every nudge starts with this, so a second `--ask` does not repeat one the agent has not read


def _card(t, now, stale):
    idle = hud.minutes_idle(t, now)
    kids = [k for k in (t.get("_kids") or [])]
    return {"id": t["id"], "title": t["title"], "agent": t.get("agent"), "progress": t.get("progress", 0), "status": t.get("status_text", ""),
            "idle_min": idle, "subs": [sum(1 for k in kids if k["status"] == "done"), len(kids)] if kids else None,
            "checkpointed": bool(t.get("checkpoint_at")) and str(t["checkpoint_at"]) >= str(t.get("updated", "")),
            "ask": t.get("question") if t.get("needs_input") else None, "review": t.get("result") or t.get("status_text") if t.get("review") and not t.get("needs_input") else None,
            "resumes": bool(t.get("learned"))}


def plan(store, now=None, include_running=False):
    """Every Doing card sorted into finish / needs / carry / running, the cards finished today, and the order tomorrow starts in."""
    now = now or datetime.now()
    conf = prompt.load_config(store.dir)
    stale = hud.stale_minutes(conf)
    tasks = store.load()
    listening = {n.lower() for n in listeners.listening(store.dir)}
    by_parent = {}
    for t in tasks:
        if t.get("parent_id"):
            by_parent.setdefault(t["parent_id"], []).append(t)
    out = {"finish": [], "needs": [], "carry": [], "running": [], "done_today": []}
    for t in tasks:
        if t.get("archived") or t.get("parent_id"):
            continue
        if t["status"] == "done":
            at = hud._t(t.get("updated"))
            if at and at.date() == now.date():
                L = rollup.learned_text(t.get("body_md"))
                out["done_today"].append({"id": t["id"], "title": t["title"], "agent": t.get("agent"), "result": t.get("result", ""),
                                          "learned": L[:3] or ([t["learned"]["status"]] if isinstance(t.get("learned"), dict) and t["learned"].get("status") else [])})
            continue
        if t["status"] != "doing":
            continue
        t = dict(t, _kids=by_parent.get(t["id"], []))
        c = _card(t, now, stale)
        idle = c["idle_min"]
        if t.get("needs_input") or t.get("review"):
            out["needs"].append(c)
        elif c["progress"] >= 100:
            out["finish"].append(c)
        elif not include_running and (t.get("agent") or "").lower() in listening and idle is not None and idle < stale:
            out["running"].append(c)
        else:
            out["carry"].append(c)
    # tomorrow starts with the card nearest done; one that has a checkpoint beats one that has not; a recent one beats an old one
    out["carry"].sort(key=lambda c: (-c["progress"], not c["checkpointed"], c["idle_min"] if c["idle_min"] is not None else 1e9, c["id"]))
    out.update(now=now, owner=store.owner, date=now.strftime("%Y-%m-%d"), include_running=include_running)
    return out


def first_move(p):
    """The one sentence that comes first: what the owner (or ORCH) does next, then one fact."""
    n, f, c = len(p["needs"]), len(p["finish"]), len(p["carry"])
    missing = [x for x in p["carry"] if not x["checkpointed"] and x["agent"]]
    who = "you" if p["owner"] == "you" else p["owner"]
    if n:
        return f"Answer or sign off {n} card{'s' if n != 1 else ''} waiting on {who}; {c} more go back to Todo tonight."
    if f:
        return f"Ask the agent{'s' if f != 1 else ''} on {f} finished-looking card{'s' if f != 1 else ''} to review {'them' if f != 1 else 'it'} (`agentboard wrapup --ask`); {c} go back to Todo."
    if missing:
        return f"Run `agentboard wrapup --ask` so {len(missing)} agent{'s' if len(missing) != 1 else ''} leave a checkpoint; {c} card{'s' if c != 1 else ''} go back to Todo tonight."
    if c:
        return f"Say go and ORCH runs `agentboard wrapup --apply`: {c} card{'s' if c != 1 else ''} go back to Todo with their notes."
    return "Nothing left to wrap up tonight." if not p["running"] else f"Nothing to release: {len(p['running'])} agent{'s' if len(p['running']) != 1 else ''} still running overnight."


def _line(c, tail=""):
    subs = f" · {c['subs'][0]}/{c['subs'][1]} subtasks" if c["subs"] else ""
    return f"{c['id']} ({c['agent'] or 'no agent'}) {c['progress']}%{subs}{tail}"


def render(p, applied=None):
    """The page, for ORCH and for tomorrow morning. `applied`: the ids released, in the order they now sit in Todo (None: a plan, nothing moved)."""
    day = p["now"].strftime("%a %d %b")
    out = [f"# End of day · {day}, {p['now'].strftime('%H:%M')}" + (" · wrapped" if applied is not None else ""), ""]
    out.append(f"**{first_move(p)}**" if applied is None else f"**Wrapped up: {len(applied)} card{'s' if len(applied) != 1 else ''} back in Todo, best first.**")
    out += ["", f"## Finished today ({len(p['done_today'])})"]
    for d in p["done_today"]:
        out.append(f"- {d['id']} ({d.get('agent') or 'no agent'}): {rollup._one(d['result'] or d['title'])}")
        out += [f"    learned: {rollup._one(x, 100)}" for x in d["learned"]]
    if not p["done_today"]:
        out.append("- nothing")
    if p["needs"]:
        out += ["", f"## Waiting on {p['owner'] if p['owner'] != 'you' else 'the owner'} ({len(p['needs'])}), stays where it is"]
        out += [f"- {_line(c)}: {'asks ' + rollup._one(c['ask']) if c['ask'] else 'review: ' + rollup._one(c['review'])}" for c in p["needs"]]
    if p["finish"]:
        out += ["", f"## At 100%, never handed in ({len(p['finish'])})"]
        out += [f"- {_line(c)}: the agent runs `agentboard review {c['id']}` with a Learned section" for c in p["finish"]]
    heading = "Back in Todo tonight, start here tomorrow" if applied is None else "Back in Todo, start here tomorrow"
    out += ["", f"## {heading} ({len(p['carry'] if applied is None else applied)})"]
    ids = p["carry"] if applied is None else [c for i in applied for c in p["carry"] if c["id"] == i]
    for n, c in enumerate(ids, 1):
        mark = "checkpoint ✓" if c["checkpointed"] else ("no checkpoint yet" if c["agent"] else "no agent")
        out.append(f"{n}. {_line(c, ' · ' + mark)}: {rollup._one(c['title'], 60)}" + (f" — {rollup._one(c['status'], 80)}" if c["status"] else ""))
    if not ids:
        out.append("- nothing")
    if p["running"]:
        out += ["", f"## Still running ({len(p['running'])}), left alone"]
        out += [f"- {_line(c)}: {rollup._one(c['title'], 60)}" for c in p["running"]]
        out.append("  (`--all` releases these too)")
    if applied is None:
        out += ["", "## Next", "- `agentboard wrapup --ask`: each agent that owes a checkpoint or a review gets a note on its card",
                "- `agentboard wrapup --apply`: on the owner's word, release the Back in Todo cards and save this page"]
    return "\n".join(out)


def ask(store, p, ab=None):
    """Leave each agent that owes something a note on its card (the reply `agentboard answer` prints, which wakes one that is waiting): a
    checkpoint for a card going back to Todo, a review for a card at 100%. One note per card: a card already holding an unread one is skipped.
    Returns [(card id, agent)] nudged."""
    ab = ab or prompt.agentboard_cmd(store.dir)
    sent = []
    cards = {t["id"]: t for t in store.load()}
    for c in p["carry"] + p["finish"]:
        t = cards.get(c["id"])
        if not t or not c["agent"] or c["checkpointed"]:
            continue
        r = t.get("reply") or {}
        if str(r.get("text", "")).startswith(ASK_MARK) and not r.get("read_at"):
            continue
        if c in p["finish"]:
            text = (f"{ASK_MARK} this card is at 100% but not handed in. Run `{ab} review {c['id']} \"<one-line result>\" --body-file <file>`, with a "
                    "`## Learned` section in the body (a decision and why, a trap you hit, where the work lives). Then wait: `answer --wait`.")
        else:
            text = (f"{ASK_MARK} before you stop, leave a hand-off on this card: `{ab} checkpoint {c['id']} \"<done so far · the next step · what you "
                    "learned>\" [--body-file <file>]`. ORCH may send the card back to Todo tonight with your notes, so the next agent can carry on from them. "
                    "Then wait: `answer --wait`.")
        store.reply(c["id"], text, by="ORCH")
        sent.append((c["id"], c["agent"]))
    return sent


def data(p, applied=None):
    """The page as data, for the board's Start of day sheet: the same four outcomes and what finished, every value plain text or a number."""
    carry = p["carry"] if applied is None else [c for i in applied for c in p["carry"] if c["id"] == i]
    return {"date": p["date"], "at": p["now"].strftime("%Y-%m-%d %H:%M"), "owner": p["owner"], "wrapped": applied is not None,
            "headline": first_move(p) if applied is None else f"Wrapped up: {len(carry)} card{'s' if len(carry) != 1 else ''} back in Todo, best first.",
            "finished": p["done_today"], "needs": p["needs"], "finish": p["finish"], "carry": carry, "running": p["running"]}


def apply(store, p):
    """Release the carry cards (and the running ones when the plan was made with include_running), best first on top of Todo: they are moved
    in reverse, each to the front, so the card tomorrow starts with ends up first. Writes the page to `.agentboard/wrapups/<date>.md`.
    Returns (ids in the order they now sit, the path written)."""
    order = [c["id"] for c in p["carry"]]
    for i in reversed(order):
        first = next((t["id"] for t in store.load() if t["status"] == "todo" and not t.get("parent_id") and t["id"] != i), None)
        store.move(i, "todo", first)
    text = render(p, applied=order)
    d = store.dir / "wrapups"
    d.mkdir(exist_ok=True)
    path = d / f"{p['date']}.md"
    path.write_text(text + "\n")
    (d / f"{p['date']}.json").write_text(json.dumps(data(p, applied=order), indent=1, default=str) + "\n")   # what the board's Start of day sheet reads
    return order, path


def last_data(store):
    """The newest saved wrap-up as data (see `data`), or None when none was saved or its file cannot be read."""
    d = store.dir / "wrapups"
    for f in sorted(d.glob("*.json"), reverse=True) if d.is_dir() else []:
        try:
            v = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(v, dict) and v.get("date"):
            return v
    return None


def last(store):
    """The newest saved wrap-up page, or None."""
    d = store.dir / "wrapups"
    files = sorted(d.glob("*.md")) if d.is_dir() else []
    return files[-1] if files else None
