"""Insights (card agentboard-insights-v0, docs/insights-design.md): what the board's own records say about how its agents are used.

Off by default: `[insights] enabled = true` in config.toml turns on the three small captures (a card's blockers logged when it is made and an "Unblocked"
line when its last blocker finishes; the name that made a card, in the log entry's `actor`; a closing reason on done, `closed_as`, default "shipped") and
the `agentboard insights` command. With the flag off the board behaves exactly as before and the command says how to turn it on.

An observation is one measured number with its sample size, a threshold, a plain sentence, what the board cannot see, and a suggestion. There are four
rules: blocked cards wait, a few cards hold the hours, the nights are idle, and an agent holds a card only part of its time. A rule with fewer than MIN_N
samples says "not enough data" instead of guessing. The board only suggests: it changes no prompt, role or card, and an agent is named only inside the
sentence that is about it. Counts, timings and card ids only: no title, description, result or chat text is read into an observation.

With agent state history (agentstates.py, `agent-states.jsonl`) a fifth rule reads how long each agent waited for work, and the night gaps and the card-in-hand share
say where the time went (waiting for work, waiting for the owner, away) instead of listing what the board cannot see.

Pure functions over the card list and the state lines: no network, no program is started, nothing is written. This module imports no process or network module (selfcheck)."""
import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from . import tomlread

CLOSE_REASONS = ("shipped", "duplicate", "not-reproduced", "superseded", "not-needed")   # why a card was closed (closed_as); "shipped" is the default
MIN_N = 5                      # fewer samples than this and a rule says "not enough data"
BLOCKED_WAIT_H = 2.0           # blocked cards: fire when the median wait for a blocker is at least this
BIG_CARD_H = 3.0               # a card whose build (claim to first review) takes at least this is big
BIG_SHARE = 0.40               # a few cards hold the hours: fire when the big ones hold at least this share of all build hours
NIGHT_SHARE = 0.50             # the nights are idle: fire when at least this share of between-card gap hours falls between midnight and 08:00
HOLD_SHARE = 0.40              # an agent holds a card under this share of its time between its first claim and last review
GAP_MIN_H, GAP_MAX_H = 0.5, 8.0   # a between-card gap counts from half an hour to eight hours (longer is a day off, not a wait)
NIGHT_END_HOUR = 8
MIN_OBS_H = 8.0                # state history: an agent needs this many observed hours in the window before its split is read
WAIT_WORK_SHARE = 0.25         # waiting for work: fire when an agent was waiting for work at least this share of its observed time
STATE_COVER_S = 30 * 60        # a state line holds for at most this long: the heartbeat is every 15 minutes, so a longer silence is time nobody watched
STATE_WORDS = {"working": "working", "quiet": "quiet", "abandoned": "abandoned", "owner": "waiting for the owner", "listening": "waiting for work", "away": "away"}
THRESHOLDS = {"blocked_wait_h": BLOCKED_WAIT_H, "big_card_h": BIG_CARD_H, "big_share": BIG_SHARE, "night_share": NIGHT_SHARE, "hold_share": HOLD_SHARE, "min_n": MIN_N, "wait_work_share": WAIT_WORK_SHARE, "min_observed_h": MIN_OBS_H}


def enabled(board_dir):
    """Is [insights] enabled = true in the board's config.toml. Read fresh each time, so an edit shows up without a restart."""
    try:
        conf = tomlread.loads((Path(board_dir) / "config.toml").read_text())
    except (OSError, ValueError):
        return False
    sec = conf.get("insights")
    return isinstance(sec, dict) and sec.get("enabled") is True


def parse_since(text, now=None):
    """'7d', '24h', 'all' -> the earliest time a card counts from (None for all). A bad value raises ValueError with the allowed shapes."""
    now = now or datetime.now()
    s = str(text or "7d").strip().lower()
    if s == "all":
        return None
    m = re.fullmatch(r"(\d{1,4})([dh])", s)
    if not m or int(m.group(1)) == 0:
        raise ValueError("--since is 7d, 24h or all")
    n = int(m.group(1))
    return now - (timedelta(days=n) if m.group(2) == "d" else timedelta(hours=n))


def _t(s):
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def _hrs(a, b):
    return (b - a).total_seconds() / 3600


def _text(e):
    return e.get("text") or ""


class Card:
    """What a card's own log says about its timing. Only ids, agents and stamps: the card's words are never read."""

    def __init__(self, t):
        self.id = t["id"]
        self.agent = t.get("agent") or None
        self.status = t.get("status")
        self.created = _t(t.get("created"))
        self.blocked_by = [b for b in (t.get("blocked_by") or []) if isinstance(b, str)]
        log = [e for e in (t.get("log") or []) if isinstance(e, dict)]
        at = lambda pred: [x for x in (_t(e.get("at")) for e in log if pred(_text(e))) if x]   # noqa: E731
        claims = at(lambda s: s.startswith(("Claimed by", "Started by", "Added to doing")))
        reviews = at(lambda s: s.startswith("Ready for review"))
        dones = at(lambda s: s.startswith(("Marked done", "Moved to done")))
        blocked = at(lambda s: s.startswith("Blocked by"))
        unblocked = at(lambda s: s.startswith("Unblocked"))
        self.claim = min(claims) if claims else None
        self.review = min(reviews) if reviews else None
        self.done = max(dones) if dones else None
        self.blocked_at = min(blocked) if blocked else None      # logged since the capture; else the card's creation is the start of the wait
        self.unblocked_at = max(unblocked) if unblocked else None

    @property
    def build_h(self):
        return _hrs(self.claim, self.review) if self.claim and self.review and self.review >= self.claim else None

    @property
    def end(self):
        """When the agent let go of the card: its first review, else its done."""
        return self.review or self.done


def _union(intervals):
    """The total hours covered by (start, end) intervals that may overlap."""
    busy, cur = 0.0, None
    for a, b in sorted(intervals):
        if cur and a <= cur[1]:
            cur = (cur[0], max(cur[1], b))
        else:
            if cur:
                busy += _hrs(*cur)
            cur = (a, b)
    if cur:
        busy += _hrs(*cur)
    return busy


def select(tasks, since=None, agent=None, prefix=None, now=None):
    """The top-level cards a run looks at: with a stamp inside the window (its last event, else its creation), held by `agent` if one is named, an id starting with `prefix`."""
    out = []
    for t in tasks:
        if not isinstance(t, dict) or "id" not in t or t.get("parent_id"):
            continue
        if prefix and not str(t["id"]).startswith(prefix):
            continue
        if agent and (t.get("agent") or "").lower() != agent.lower():
            continue
        c = Card(t)
        last = c.done or c.review or c.claim or c.created
        if since and (last is None or last < since):
            continue
        out.append(c)
    return out


def state_intervals(lines, since, now):
    """{agent: [(start, end, state)]} from the state lines [(agent, state, time)]: a state holds until the agent's next line, for at most STATE_COVER_S, clipped to
    the window [since, now]. The HUD's two owner states (waiting on a question, waiting on a review) are one, "owner"."""
    by = {}
    for ag, st, at in lines:
        by.setdefault(ag, []).append((at, "owner" if st in ("waiting", "review") else st))
    out = {}
    for ag, rows in by.items():
        rows.sort()
        ivs = []
        for i, (at, st) in enumerate(rows):
            end = min(rows[i + 1][0] if i + 1 < len(rows) else now, at + timedelta(seconds=STATE_COVER_S), now)
            start = max(at, since) if since else at
            if end > start:
                ivs.append((start, end, st))
        out[ag] = ivs
    return out


def _state_hours(ivs, a=None, b=None):
    """{state: hours} for the intervals, within [a, b] when given."""
    out = {}
    for s0, e0, st in ivs:
        lo, hi = (max(s0, a) if a else s0), (min(e0, b) if b else e0)
        if hi > lo:
            out[st] = out.get(st, 0.0) + _hrs(lo, hi)
    return out


def _split(hours):
    """'waiting for work 52%, working 30%, ...' from {state: hours}, largest first; '' when there is nothing."""
    total = sum(hours.values())
    if total <= 0:
        return ""
    return ", ".join(f"{STATE_WORDS[k]} {100 * v / total:.0f}%" for k, v in sorted(hours.items(), key=lambda kv: -kv[1]) if v / total >= 0.005)


def _obs(rule, title, state, n, value=None, sentence="", evidence=None, cannot_see="", suggestion="", threshold=None):
    return {"rule": rule, "title": title, "state": state, "n": n, "value": value, "threshold": threshold, "sentence": sentence,
            "evidence": evidence or [], "cannot_see": cannot_see, "suggestion": suggestion}


def _not_enough(rule, title, n, what):
    return _obs(rule, title, "not-enough-data", n, sentence=f"Not enough data: {n} {what}, need {MIN_N}.")


def blocked_wait(cards, by_id):
    title = "Blocked cards wait"
    waits = []
    for c in cards:
        if not c.blocked_by or not c.claim:
            continue   # only cards an agent went on to claim: a card nobody has taken waits for an assignment, not for its blocker
        blockers = [by_id.get(b) for b in c.blocked_by]
        if any(b is None for b in blockers):
            continue   # a blocker that is gone (deleted or in an archive we do not hold): the wait is unknown
        if c.unblocked_at:
            end = c.unblocked_at
        elif all(b.done for b in blockers):
            end = max(b.done for b in blockers)
        else:
            continue   # still blocked: the wait has not ended
        start = c.blocked_at or c.created
        if start and end >= start:
            waits.append((_hrs(start, end), c.id))
    if len(waits) < MIN_N:
        return _not_enough("blocked-wait", title, len(waits), "claimed cards whose wait for a blocker has ended")
    med = statistics.median(w for w, _ in waits)
    longest = sorted(waits, reverse=True)[:3]
    fires = med >= BLOCKED_WAIT_H
    return _obs("blocked-wait", title, "fires" if fires else "quiet", len(waits), round(med, 2), threshold=BLOCKED_WAIT_H,
                sentence=f"Cards that named a blocker and were then claimed waited a median {med:.1f} h for it ({len(waits)} cards)" + (f", at least {BLOCKED_WAIT_H:g} h." if fires else "."),
                evidence=[f"{cid} {w:.1f} h" for w, cid in longest],
                cannot_see="Only waits that have ended on cards an agent claimed; a card still blocked or never taken is not counted. A blocker added before the capture was on counts from the card's creation.",
                suggestion="Cut a blocker into a contract and the rest: the blocker merges its interface first (data shape, stub, test), so dependents start while it finishes." if fires else "")


def big_cards(cards):
    title = "A few cards hold the hours"
    builds = [(c.build_h, c.id) for c in cards if c.build_h is not None]
    if len(builds) < MIN_N:
        return _not_enough("big-cards", title, len(builds), "cards with a build time (claim to first review)")
    total = sum(b for b, _ in builds)
    big = sorted([(b, cid) for b, cid in builds if b >= BIG_CARD_H], reverse=True)
    share = sum(b for b, _ in big) / total if total else 0.0
    fires = share >= BIG_SHARE
    return _obs("big-cards", title, "fires" if fires else "quiet", len(builds), round(share, 2), threshold=BIG_SHARE,
                sentence=f"{len(big)} of {len(builds)} cards took {BIG_CARD_H:g} h or more to build and hold {100 * share:.0f}% of the {total:.0f} build hours.",
                evidence=[f"{cid} {b:.1f} h" for b, cid in big[:5]],
                cannot_see="Build is claim to the first review: waiting for a test lock or for the owner is inside it, and work with no card is not seen.",
                suggestion="Cap a card at about two hours: split it at its first natural seam and let each slice reach main on its own." if fires else "")


def idle_nights(cards, states=None):
    title = "The nights are idle"
    per = {}
    for c in cards:
        if c.agent and c.claim and c.end and c.end >= c.claim:
            per.setdefault(c.agent, []).append((c.claim, c.end))
    gaps = []   # (agent, start, end)
    for ag, ivs in per.items():
        ivs.sort()
        reach = ivs[0][1]
        for a, b in ivs[1:]:   # a gap is time after the agent let go of everything it held and before its next claim
            if a > reach and GAP_MIN_H <= _hrs(reach, a) <= GAP_MAX_H:
                gaps.append((ag, reach, a))
            reach = max(reach, b)
    if len(gaps) < MIN_N:
        return _not_enough("idle-nights", title, len(gaps), "between-card gaps of half an hour to eight hours")
    night = day = 0.0
    for _, a, b in gaps:
        t = a
        while t < b:   # split by the clock in ten-minute steps: midnight to 08:00 is night
            step = min(b, t + timedelta(minutes=10))
            if t.hour < NIGHT_END_HOUR:
                night += _hrs(t, step)
            else:
                day += _hrs(t, step)
            t = step
    share = night / (night + day) if night + day else 0.0
    fires = share >= NIGHT_SHARE
    evidence = [f"{night:.1f} h at night, {day:.1f} h in the day"]
    cannot = "Why an agent was between cards: the owner's night, waiting for an assignment and waiting for a shared test lock look the same until agent state history is captured."
    if states:   # the state history says where those hours went
        cause, covered, total_gap = {}, 0.0, 0.0
        for ag, a, b in gaps:
            total_gap += _hrs(a, b)
            for st, h in _state_hours(states.get(ag, []), a, b).items():
                cause[st] = cause.get(st, 0.0) + h
                covered += h
        if total_gap and covered / total_gap >= 0.5:
            evidence.append(f"in those gaps the state history shows {_split(cause)} ({100 * covered / total_gap:.0f}% of the gap hours are covered)")
            cannot = "The state history covers the hours it was recording; an agent with no card and no wait running is 'away', which also looks like a session that worked without a card."
        else:
            cannot += f" The state history covers only {100 * covered / total_gap if total_gap else 0:.0f}% of these gap hours so far."
    return _obs("idle-nights", title, "fires" if fires else "quiet", len(gaps), round(share, 2), threshold=NIGHT_SHARE,
                sentence=f"{len(gaps)} gaps between an agent's cards add up to {night + day:.1f} h; {night:.1f} h of them ({100 * share:.0f}%) fall between midnight and 08:00.",
                evidence=evidence, cannot_see=cannot,
                suggestion="Queue specified, unblocked cards before the owner leaves, so an agent takes the next one on its own." if fires else "")


def holding(cards, states=None):
    title = "A card in hand"
    per = {}
    for c in cards:
        if c.agent and c.claim and c.end and c.end >= c.claim:
            per.setdefault(c.agent, []).append((c.claim, c.end))
    out, few = [], []
    for ag, ivs in sorted(per.items()):
        if len(ivs) < MIN_N:
            few.append((ag, len(ivs)))
            continue
        span = _hrs(min(a for a, _ in ivs), max(b for _, b in ivs))
        if span <= 0:
            continue
        share = _union(ivs) / span
        fires = share < HOLD_SHARE
        evidence = [f"{ag} {100 * share:.0f}%"]
        cannot = "Work that has no card (design, a playtest, a chat) is invisible: a low share is not idle time."
        hours = _state_hours((states or {}).get(ag, []), min(a for a, _ in ivs), max(b for _, b in ivs))
        if sum(hours.values()) >= MIN_OBS_H:   # the measured split replaces the guess
            evidence.append(f"state history over the same span: {_split(hours)}")
            cannot = "An agent with no card and no wait running is 'away' in the history, which also looks like a session that worked without a card."
        out.append(_obs("holding", title, "fires" if fires else "quiet", len(ivs), round(share, 2), threshold=HOLD_SHARE,
                        sentence=f"{ag} held a card {100 * share:.0f}% of the time between its first claim and its last review ({len(ivs)} cards).",
                        evidence=evidence,
                        cannot_see=cannot,
                        suggestion="Ask whether the agent's other work should have a card, or whether it waited for an assignment." if fires else ""))
    if not out:   # no agent has enough cards (or none holds one): say so rather than leave the rule out
        return [_not_enough("holding", title, max([n for _, n in few] or [0]), "cards for the agent with the most")]
    return out


def waiting_for_work(states):
    """How long each agent waited for work (no open card and a wait running), from the state history: one observation per agent with enough observed hours."""
    title = "Waiting for work"
    if not states:
        return [_not_enough_hours("waiting-for-work", title, 0.0, "no state history yet: it is recorded while the server runs with [insights] on")]
    out, best = [], 0.0
    for ag, ivs in sorted(states.items()):
        hours = _state_hours(ivs)
        obs = sum(hours.values())
        best = max(best, obs)
        if obs < MIN_OBS_H:
            continue
        share = hours.get("listening", 0.0) / obs
        fires = share >= WAIT_WORK_SHARE
        out.append(_obs("waiting-for-work", title, "fires" if fires else "quiet", round(obs), round(share, 2), threshold=WAIT_WORK_SHARE,
                        sentence=f"{ag} waited for work {100 * share:.0f}% of the {obs:.0f} hours the board watched it.",
                        evidence=[f"{ag}: {_split(hours)}"],
                        cannot_see="Waiting for work means no open card and a wait running under the agent's name; it counts nights and the owner's absence as well as a slow queue.",
                        suggestion="Give the agent specified, unblocked cards ahead of time, or hand its share of the queue to an agent that is busy." if fires else ""))
    if not out:
        return [_not_enough_hours("waiting-for-work", title, best, "the agent with the most")]
    return out


def _not_enough_hours(rule, title, hours, what):
    sentence = f"Not enough data: {what}." if not hours and what.startswith("no state") else f"Not enough data: {hours:.1f} observed hours for {what}, need {MIN_OBS_H:g}."
    return _obs(rule, title, "not-enough-data", round(hours), sentence=sentence)


def compute(tasks, since=None, agent=None, prefix=None, now=None, states=None):
    """The observations over the cards in the window: a dict with the card count and the list of observations (JSON-ready)."""
    now = now or datetime.now()
    by_id = {t["id"]: Card(t) for t in tasks if isinstance(t, dict) and "id" in t}
    cards = select(tasks, since, agent, prefix, now)
    lines = [x for x in (states or []) if not agent or x[0].lower() == agent.lower()]
    by_state = state_intervals(lines, since or (min(x[2] for x in lines) if lines else None), now) if lines else None
    obs = [blocked_wait(cards, by_id), big_cards(cards), idle_nights(cards, by_state)] + holding(cards, by_state) + waiting_for_work(by_state)
    return {"since": since.isoformat(timespec="minutes") if since else "all", "agent": agent, "prefix": prefix, "cards": len(cards),
            "thresholds": dict(THRESHOLDS), "observations": obs}


def render(result):
    """The text of a result: one block per observation, the firing ones first. Numbers, ids and templates only."""
    head = f"Insights over {result['cards']} cards" + (f" since {result['since'].replace('T', ' ')}" if result["since"] != "all" else "") \
        + (f", held by {result['agent']}" if result["agent"] else "") + " (counts and timings only; the board suggests, it changes nothing):"
    order = {"fires": 0, "quiet": 1, "not-enough-data": 2}
    lines = [head, ""]
    for o in sorted(result["observations"], key=lambda o: order[o["state"]]):
        lines.append(f"[{o['state']}] {o['title']}: {o['sentence']}")
        if o["evidence"] and o["state"] != "not-enough-data":
            lines.append("  Evidence: " + "; ".join(o["evidence"]))
        if o["cannot_see"] and o["state"] != "not-enough-data":
            lines.append("  The board cannot see: " + o["cannot_see"])
        if o["suggestion"]:
            lines.append("  Suggestion: " + o["suggestion"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def as_json(result):
    return json.dumps(result, indent=2, sort_keys=False) + "\n"


OFF_HINT = ("Insights are off. To turn them on, put this in .agentboard/config.toml:\n\n    [insights]\n    enabled = true\n\n"
            "Turning it on starts three small captures on new cards (blockers logged when a card is made and an Unblocked line when the last one finishes; "
            "who made a card; a closing reason on done). It reads nothing outside the board, starts no program and sends nothing out.")
