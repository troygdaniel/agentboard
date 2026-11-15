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

from . import rework, tomlread

CLOSE_REASONS = ("shipped", "duplicate", "not-reproduced", "superseded", "not-needed")   # why a card was closed (closed_as); "shipped" is the default
SIZES = ("S", "M", "L")        # a card's size, as estimated at add (--size) and as it came out at the first report (actual_size)
SIZE_S_H = 1.0                 # actual size: under this many hours from claim to first report is S, under BIG_CARD_H is M, BIG_CARD_H or more is L
MODEL_MAX = 60                 # a model name is a short identifier, never free text
KIND_RATIO = 0.70              # kind against agent or model: fire when one cell's median build is under this share of the other cells' median
ESTIMATE_MISS_SHARE = 0.40     # estimate against actual: fire when at least this share of the sized cards came out bigger than estimated
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
REWORK_SHARE = 0.20            # rework: fire when at least this share of the cards that were reported finished came back
STATE_COVER_S = 30 * 60        # a state line holds for at most this long: the heartbeat is every 15 minutes, so a longer silence is time nobody watched
STATE_WORDS = {"working": "working", "quiet": "quiet", "abandoned": "abandoned", "owner": "waiting for the owner", "listening": "waiting for work", "away": "away"}
THRESHOLDS = {"blocked_wait_h": BLOCKED_WAIT_H, "big_card_h": BIG_CARD_H, "big_share": BIG_SHARE, "night_share": NIGHT_SHARE, "hold_share": HOLD_SHARE, "min_n": MIN_N, "wait_work_share": WAIT_WORK_SHARE, "min_observed_h": MIN_OBS_H, "rework_share": REWORK_SHARE, "kind_ratio": KIND_RATIO, "estimate_miss_share": ESTIMATE_MISS_SHARE, "size_s_h": SIZE_S_H}


def enabled(board_dir):
    """Is [insights] enabled = true in the board's config.toml. Read fresh each time, so an edit shows up without a restart."""
    try:
        conf = tomlread.loads((Path(board_dir) / "config.toml").read_text())
    except (OSError, ValueError):
        return False
    sec = conf.get("insights")
    return isinstance(sec, dict) and sec.get("enabled") is True


_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\- ]*$")


def clean_model(text):
    """A model name for the card: stripped, at most MODEL_MAX characters of letters, digits and . _ : / + - and spaces. Returns None for nothing; raises
    ValueError for anything else, so a note or a secret never lands in the field."""
    text = str(text or "").strip()
    if not text:
        return None
    if len(text) > MODEL_MAX or not _MODEL_RE.match(text):
        raise ValueError(f"a model name is at most {MODEL_MAX} letters, digits and . _ : / + - (for example claude-sonnet-5-5)")
    return " ".join(text.split())


def size_of(hours):
    """S, M or L from the hours a card took (claim to first report): under SIZE_S_H, under BIG_CARD_H, BIG_CARD_H or more."""
    return "S" if hours < SIZE_S_H else "M" if hours < BIG_CARD_H else "L"


def first_claim(log):
    """The time of the card's first claim, start or direct add to Doing, from its log (None when it never had one)."""
    times = [x for x in (_t(e.get("at")) for e in (log or []) if isinstance(e, dict) and _text(e).startswith(("Claimed by", "Started by", "Added to doing"))) if x]
    return min(times) if times else None


def build_size(log, now_text):
    """The size a card has come out as at `now_text`: its first claim to now, as S, M or L (None when the log holds no claim)."""
    began, end = first_claim(log), _t(now_text)
    return size_of(_hrs(began, end)) if began and end and end >= began else None


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


def _kind_of(title):
    """The kind of change a card was (summary.kind_of, a short class word), read from the title once and kept as that word. Imported here, not at the top:
    summary imports the store, and the store imports this module."""
    try:
        from . import summary
        return summary.kind_of(title)
    except Exception:   # a title the classifier cannot read is just "Changed": a label must never stop an insights run
        return "Changed"


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
        self.model = t.get("model") if isinstance(t.get("model"), str) else None               # claim --model / AGENTBOARD_MODEL
        self.size = t.get("size") if t.get("size") in SIZES else None                           # the estimate at add or start
        self.stored_actual = t.get("actual_size") if t.get("actual_size") in SIZES else None    # what the first review recorded
        self.reviews = len(reviews)                                                            # times the agent reported it finished
        self.rework = [c for c in (rework.code_of(_text(e)) for e in log) if c]                # the codes the capture wrote (rework.py)
        self.sent_back = any(_text(e).startswith("Sent back") for e in log)                  # the dedicated send-back, which also wrote this before the capture
        self.title_kind = _kind_of(t.get("title"))                                           # a class label only (summary.KINDS): the title's words are not kept
        dones = at(lambda s: s.startswith(("Marked done", "Moved to done")))
        blocked = at(lambda s: s.startswith("Blocked by"))
        unblocked = at(lambda s: s.startswith("Unblocked"))
        self.claim = min(claims) if claims else None
        self.review = min(reviews) if reviews else None
        self.done = max(dones) if dones else None
        self.blocked_at = min(blocked) if blocked else None      # logged since the capture; else the card's creation is the start of the wait
        self.unblocked_at = max(unblocked) if unblocked else None

    @property
    def came_back(self):
        """Reviewed twice, sent back, or any rework line: the work did not stop at the first report."""
        return self.reviews >= 2 or self.sent_back or bool(self.rework)

    @property
    def actual_size(self):
        """How big the card turned out: the size the first review recorded, else worked out from its build time (so cards from before the capture count)."""
        if self.stored_actual:
            return self.stored_actual
        return size_of(self.build_h) if self.build_h is not None else None

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


REWORK_SAYS = {
    rework.BE_SIMPLER: "Lead every report with the one action the owner must take and keep the rest under Details: Be simpler means the first line said too much.",
    rework.SENT_BACK: "Write what done looks like (the check the owner will make) into the card's description before the work starts, so a send-back is about a change, not the goal.",
    rework.CHANGES_ASKED: "Write what done looks like (the check the owner will make) into the card's description before the work starts, so the first report already answers it.",
    rework.REOPENED: "Close a card only after the merge and the check are confirmed: a reopened card was closed too early.",
    rework.RE_REVIEWED: "Ask for a change on the card (a reply), not in chat: a second report with no request on the card leaves no reason behind.",
}


def work_comes_back(cards):
    title = "Work comes back"
    seen = [c for c in cards if c.reviews or c.came_back]   # the cards the owner was ever asked to look at
    if len(seen) < MIN_N:
        return _not_enough("rework", title, len(seen), "cards reported finished")
    back = [c for c in seen if c.came_back]
    share = len(back) / len(seen)
    fires = share >= REWORK_SHARE
    codes = {}
    for c in back:
        for code in c.rework:
            codes[code] = codes.get(code, 0) + 1
    unknown = sum(1 for c in back if not c.rework)   # came back before the capture was on (or by a path it does not see): no reason on record
    parts = [f"{code} {n}" for code, n in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0]))] + ([f"no reason recorded {unknown}"] if unknown else [])
    evidence = ["Reasons (every rework line): " + ", ".join(parts)] if parts else []
    kinds = {}
    for c in seen:
        k = kinds.setdefault(c.title_kind, [0, 0])
        k[0] += 1
        k[1] += 1 if c.came_back else 0
    cells = sorted(((k, v[1], v[0]) for k, v in kinds.items() if v[0] >= MIN_N), key=lambda x: (-x[1] / x[2], x[0]))
    evidence += [f"{k}: {b} of {n} came back ({100 * b / n:.0f}%)" for k, b, n in cells[:5]]
    top = max(codes.items(), key=lambda kv: (kv[1], kv[0]))[0] if codes else None
    return _obs("rework", title, "fires" if fires else "quiet", len(seen), round(share, 2), threshold=REWORK_SHARE,
                sentence=f"{len(back)} of {len(seen)} cards that were reported finished came back ({100 * share:.0f}%): reviewed twice, sent back, reopened or answered with a change request"
                + (f", at least {100 * REWORK_SHARE:.0f}%." if fires else "."),
                evidence=evidence,
                cannot_see="Reasons are only on rework since the capture was switched on; older cards show as no reason recorded. A change asked for in chat shows only if the agent then reports the card finished again, and any reply to a card in review counts as a request even when it was a question. Kinds come from the title and only show with at least 5 cards.",
                suggestion=(REWORK_SAYS[top] if top else "Cards come back and the board does not know why for these: with insights on, the next ones carry a reason.") if fires else "")


def estimates_miss(cards):
    title = "Estimates miss"
    sized = [(c, c.actual_size) for c in cards if c.size and c.actual_size]
    if len(sized) < MIN_N:
        return _not_enough("estimate-miss", title, len(sized), "cards with an estimated size and a first report")
    rank = {"S": 0, "M": 1, "L": 2}
    bigger = [c for c, a in sized if rank[a] > rank[c.size]]
    share = len(bigger) / len(sized)
    fires = share >= ESTIMATE_MISS_SHARE
    pairs = {}
    for c, a in sized:
        pairs[(c.size, a)] = pairs.get((c.size, a), 0) + 1
    matrix = ", ".join(f"{e}\u2192{a} {pairs[(e, a)]}" for e in SIZES for a in SIZES if (e, a) in pairs)
    worst = sorted(((rank[a] - rank[c.size], c.id) for c, a in sized if rank[a] > rank[c.size]), reverse=True)[:3]
    return _obs("estimate-miss", title, "fires" if fires else "quiet", len(sized), round(share, 2), threshold=ESTIMATE_MISS_SHARE,
                sentence=f"{len(bigger)} of {len(sized)} cards with an estimate came out bigger than estimated ({100 * share:.0f}%)" + (f", at least {100 * ESTIMATE_MISS_SHARE:.0f}%." if fires else "."),
                evidence=["Estimated \u2192 came out: " + matrix] + ([f"{cid} grew by {d} size" + ("s" if d > 1 else "") for d, cid in worst] if fires else []),
                cannot_see=f"Came out is the card's own time from claim to its first report (S under {SIZE_S_H:g} h, M under {BIG_CARD_H:g} h, L more), not lines changed: waiting for a test lock or the owner is inside it. Only cards with an estimate count; most cards have none yet.",
                suggestion="Split a card you expect to pass M before it starts, and re-estimate at its first checkpoint: estimates run small here." if fires else "")


def _cells(cards, key):
    """{kind: {name: [build hours]}} over the cards with a build time and a value for `key` (agent or model)."""
    out = {}
    for c in cards:
        name = getattr(c, key)
        if name and c.build_h is not None:
            out.setdefault(c.title_kind, {}).setdefault(name, []).append(c.build_h)
    return out


def kind_against(cards, key):
    """One kind of card, two or more agents (or models) with at least MIN_N cards each: does one of them take under KIND_RATIO of the others' time?"""
    noun = "agent" if key == "agent" else "model"
    rule, title = f"kind-{noun}", f"Kind of card against {noun}"
    best, biggest = None, 0
    for kind, groups in sorted(_cells(cards, key).items()):
        biggest = max([biggest] + [len(v) for v in groups.values()])
        full = {g: v for g, v in groups.items() if len(v) >= MIN_N}
        if len(full) < 2:
            continue
        for g, v in sorted(full.items()):
            others = [x for og, ov in full.items() if og != g for x in ov]
            med_o = statistics.median(others)
            if med_o <= 0:
                continue
            row = (statistics.median(v) / med_o, kind, g, len(v), statistics.median(v), len(others), med_o, full)
            if best is None or row[:3] < best[:3]:
                best = row
    if best is None:
        return _obs(rule, title, "not-enough-data", biggest,
                    sentence=f"Not enough data: no kind of card has two {noun}s with {MIN_N} or more cards each (the largest cell has {biggest}).")
    ratio, kind, g, n, med, n_o, med_o, full = best
    fires = ratio < KIND_RATIO
    return _obs(rule, title, "fires" if fires else "quiet", n + n_o, round(ratio, 2), threshold=KIND_RATIO,
                sentence=f"{kind} cards: {g} took a median {med:.1f} h to build ({n} cards) against {med_o:.1f} h for the other {noun}s ({n_o} cards), {100 * ratio:.0f}% of their time"
                + (f", under {100 * KIND_RATIO:.0f}%." if fires else "."),
                evidence=[f"{kind} / {name}: {len(v)} cards, median {statistics.median(v):.1f} h" for name, v in sorted(full.items(), key=lambda kv: statistics.median(kv[1]))],
                cannot_see=f"Build is claim to first report, and the kind comes from the title: a {noun} may simply have had the bigger cards, so this is a gap in time, not in quality. Cells under {MIN_N} cards are left out, which is most of the board.",
                suggestion=f"Try {g} on {kind} cards first and see whether the gap holds over the next batch; compare card sizes before reading it as skill." if fires else "")


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
    obs = [blocked_wait(cards, by_id), big_cards(cards), idle_nights(cards, by_state), work_comes_back(cards),
           estimates_miss(cards), kind_against(cards, "agent"), kind_against(cards, "model")] + holding(cards, by_state) + waiting_for_work(by_state)
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
            "Turning it on starts small captures on new cards (blockers logged when a card is made and an Unblocked line when the last one finishes; "
            "who made a card; a closing reason on done; a Rework line with a reason code when a card is sent back, answered with a change request, "
            "reopened or reported finished again; with --model on claim or $AGENTBOARD_MODEL, the model on the card; with --size at add, a size estimate and, "
            "at the first review, the size the card came out as). It reads nothing outside the board, starts no program and sends nothing out.")
