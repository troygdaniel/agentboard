"""The sample cards: what `agentboard demo` and the empty board's "Add sample cards" button put on a board so there is something to look at.
Every id starts with demo- (`agentboard rm --demo` removes them). Seeding twice changes nothing: once any sample card is on the board, seed does nothing until `agentboard rm --demo` has cleared them."""
from .store import BoardError


def seed(s):
    """Add the sample work to store `s`. Returns how many cards (subtasks included) the board has with a demo- id afterwards."""
    have = sum(1 for t in s.load() if str(t.get("id", "")).startswith("demo-"))
    if have:
        return have   # already seeded: a second call changes nothing (not even a card's history); `agentboard rm --demo` clears them first

    def once(fn, *args, **kw):
        try:
            fn(*args, **kw)
        except BoardError:
            pass  # already seeded on an earlier run

    once(s.add, "Write release notes", "v2.4 changelog from merged PRs.", "todo", task_id="demo-release-notes")
    once(s.add, "Audit npm dependencies", "Flag anything unmaintained or with open CVEs.", "backlog", task_id="demo-audit")
    # Each card in progress has its steps, as every real card does: the board flags a Doing card that has none, and a sample should not.
    once(s.start, "Refactor billing module", "atlas", "#3b82f6", task_id="demo-billing")
    for sid, title in (("demo-billing-map", "Map the call sites"), ("demo-billing-extract", "Extract BillingService"), ("demo-billing-invoices", "Update the invoices")):
        once(s.add, title, "", None, None, sid, parent_id="demo-billing")
    for sid, pct, text in (("demo-billing-map", 100, "41 files mapped"), ("demo-billing-extract", 100, "Tests green"), ("demo-billing-invoices", 40, "Updating call sites in invoices/")):
        once(s.update, sid, pct, text)
    once(s.update, "demo-billing", text="Updating call sites in invoices/")
    once(s.start, "Draft API docs", "scribe", "#6366f1", task_id="demo-docs")
    for sid, title in (("demo-docs-routes", "Read the route handlers"), ("demo-docs-write", "Write the reference pages")):
        once(s.add, title, "", None, None, sid, parent_id="demo-docs")
    once(s.update, "demo-docs-routes", 60, "Reading route handlers")
    once(s.update, "demo-docs", text="Reading route handlers")
    once(s.start, "Set up CI", "bolt", "#8b5cf6", task_id="demo-ci")
    for sid, title in (("demo-ci-jobs", "Write the lint, test and deploy jobs"), ("demo-ci-run", "Check a green run")):
        once(s.add, title, "", None, None, sid, parent_id="demo-ci")
    for sid in ("demo-ci-jobs", "demo-ci-run"):
        once(s.update, sid, 100, "done")
    once(s.update, "demo-ci", text="GitHub Actions: lint, test, deploy in 3 jobs", status="done")
    return sum(1 for t in s.load() if str(t.get("id", "")).startswith("demo-"))
