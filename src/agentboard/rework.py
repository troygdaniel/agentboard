"""One rework event (card agentboard-insights-rework-event, docs/insights-design.md capture 5): every path that sends a card back for changes writes one log
line, `Rework: <code>`, so the board can say how often work comes back and why. Before this the cause was spread over four places: the dedicated send-back (0
uses on 2,878 cards), a reply to a card in review ("Be simpler" included), a card moved out of Done, and a second "Ready for review".

Behind `[insights] enabled = true`; with it off the board writes exactly what it always did. The line carries a code from the closed list below and nothing else:
never the owner's words, never the agent's. `insights.py` reads the lines (and, for cards from before the capture, the older traces: a second review, a "Sent
back" line) and answers "what share of cards came back, and for which reason". Counts only; no program is started and nothing leaves the board.

The codes:
  sent-back      the owner used the dedicated Send back (store.send_back), with a note on the card
  be-simpler     the owner answered a card in review with the Be simpler button
  changes-asked  the owner answered a card in review with any other reply. The board cannot tell "change this" from "one question", so every reply
                 to a card that waits for sign-off counts as the owner asking for something
  reopened       a card left Done by a move (dragged back, the panel's move button)
  re-reviewed    the agent reported "Ready for review" again with no request on the card since its last report (a request made in chat, or the
                 agent's own correction). A report that follows one of the first four lines is that request coming back, so it adds no second line"""

SENT_BACK, BE_SIMPLER, CHANGES_ASKED, REOPENED, RE_REVIEWED = "sent-back", "be-simpler", "changes-asked", "reopened", "re-reviewed"
CODES = (SENT_BACK, BE_SIMPLER, CHANGES_ASKED, REOPENED, RE_REVIEWED)
PREFIX = "Rework: "
BE_SIMPLER_PREFIX = "Be simpler"    # what the Be simpler button sends starts with this (static/index.html, data-simpler)


def line(code):
    """The log text for a code (an unknown code is a bug in the caller, so it raises rather than writing a line nobody can read)."""
    if code not in CODES:
        raise ValueError(f"unknown rework code: {code!r}")
    return PREFIX + code


def code_of(text):
    """The code in a log line, or None when the line is not a Rework line (or names a code this version does not know)."""
    s = str(text or "")
    if not s.startswith(PREFIX):
        return None
    code = s[len(PREFIX):].strip()
    return code if code in CODES else None


def reply_code(text):
    """The code for an owner's reply to a card in review: be-simpler for the button's own words, changes-asked for anything else."""
    return BE_SIMPLER if str(text or "").lstrip().startswith(BE_SIMPLER_PREFIX) else CHANGES_ASKED


def explained(log):
    """True when the log holds a request after the card's last "Ready for review": a Rework line other than re-reviewed (a re-reviewed line is what a bare
    report writes, so it can never explain the next one). The review that follows a request is that rework coming back, so it adds no second line.
    `log` is the card's log list."""
    last = -1
    for i, e in enumerate(log or []):
        if isinstance(e, dict) and str(e.get("text") or "").startswith("Ready for review"):
            last = i
    if last < 0:
        return False
    return any(isinstance(e, dict) and code_of(e.get("text")) not in (None, RE_REVIEWED) for e in (log or [])[last + 1:])


def reviewed_before(log):
    """True when the log shows an earlier "Ready for review" (the card has been reported finished once already)."""
    return any(isinstance(e, dict) and str(e.get("text") or "").startswith("Ready for review") for e in (log or []))
