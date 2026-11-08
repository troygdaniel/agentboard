"""The live check of the board chat (card chat-q1): what the receipts say about the REAL board, reading only counts, names, ages and states.

    python3 tests/chat_live_check.py                      # read-only: who is listening, how many sessions, and the state of each recent line to an agent
    python3 tests/chat_live_check.py --send --yes         # also post ONE harmless line to each listening agent and ORCH, then watch their receipts for --wait seconds

It never prints the words of a line, a card or a report: a state, a name, an age in seconds. Without --send it writes nothing at all. --send posts a line
the whole board sees and that wakes every agent it names: run it only when ORCH or the owner says so (card conversation-reliability-verify does).

The board is the one `agentboard` would use here (AGENTBOARD_DIR, --board, or the folder). The receipts are the page's own logic, run in node."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agentboard import cursors, listeners  # noqa: E402
from agentboard.store import Store, find_dir  # noqa: E402

from chat_world import receipt_state  # noqa: E402

PING = "chat check: please ignore this line (no answer needed)"


def payload(store):
    return {"messages": store.chat_list(limit=200), "receipts": listeners.receipts(store.dir), "retired": []}


def age(m):
    try:
        return time.time() - time.mktime(time.strptime(m["at"], "%Y-%m-%dT%H:%M:%S"))
    except (KeyError, ValueError):
        return float("inf")


def report(store, since_s=86400):
    d = payload(store)
    rec = d["receipts"]
    print(f"board: {store.dir.parent.name}/.agentboard   agent chat: {'on' if store.chat_agents() else 'off'}")
    names = sorted({*(k for k in rec["listening"]), *(k for k in rec["delivered"]), *(k for k in rec["read"])}, key=str.lower)
    print("listening now:")
    for n in sorted(rec["listening"], key=str.lower):
        print(f"  {n:12} {listeners.sessions(store.dir, n)} session(s)")
    if not rec["listening"]:
        print("  nobody")
    print("recent lines from the owner to one name (states are the page's own):")
    shown = 0
    for m in d["messages"]:
        if m.get("kind") == "user" and m.get("to") and m["to"] != "all" and not m.get("via") and age(m) < since_s:
            st = receipt_state(d, store.owner, m["seq"])
            late = " late" if st.get("late") else ""
            print(f"  #{m['seq']:<4} to {m['to']:10} {int(age(m)):>6} s ago  {st.get('state', '?')}{late}")
            shown += 1
    if not shown:
        print("  none in the last day")
    return d


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="post one harmless line to each listening agent and ORCH")
    ap.add_argument("--yes", action="store_true", help="really do it (with --send)")
    ap.add_argument("--wait", type=int, default=30, help="seconds to watch the receipts after --send")
    a = ap.parse_args(argv)
    store = Store(find_dir())
    d = report(store)
    if not a.send:
        return 0
    targets = sorted({*d["receipts"]["listening"], "ORCH"}, key=str.lower)
    if not a.yes:
        print(f"\nwould post one line to: {', '.join(targets)}  (add --yes to do it)")
        return 0
    sent = {n: store.chat_send(store.owner, PING, kind="user", to=n) for n in targets}
    t0 = time.time()
    print(f"\nposted {len(sent)} lines; watching {a.wait} s")
    while time.time() - t0 < a.wait:
        time.sleep(2)
        d = payload(store)
        states = {n: receipt_state(d, store.owner, m["seq"]).get("state") for n, m in sent.items()}
        if all(s in ("delivered", "seen", "answered", "wrote back") for s in states.values()):
            break
    print("receipts after", int(time.time() - t0), "s:")
    for n, m in sent.items():
        st = receipt_state(d, store.owner, m["seq"])
        rec = d["receipts"]["delivered"].get(n.lower())
        print(f"  {n:12} {st.get('state'):10} {'delivered after ' + str(int(time.mktime(time.strptime(rec['at'], '%Y-%m-%dT%H:%M:%S')) - time.mktime(time.strptime(m['at'], '%Y-%m-%dT%H:%M:%S')))) + ' s' if rec and rec['seq'] >= m['seq'] else 'not delivered yet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
