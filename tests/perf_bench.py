#!/usr/bin/env python3
"""Performance at scale, measured on a THROWAWAY board (overnight-perf-scale). Not a unit test (the name does not start with test_): the
numbers go into docs/overnight/overnight-perf-scale.md; tests/test_perf_budgets.py holds the budgets.

    python3 tests/perf_bench.py --cards 1000 --chat 2000            # the board side: store, API, HUD, update latency, payload sizes
    python3 tests/perf_bench.py --cards 5000 --chat 10000 --browser  # plus first paint in headless Chrome (needs /tmp/qa_pylibs, CLAUDE.md)
    python3 tests/perf_bench.py --cards 1000 --soak 5 --agents 12    # 12 fake agents posting every second for 5 minutes against a real server

Everything happens in a temp folder with made-up cards; nothing touches a real board, nothing leaves the machine."""
import argparse
import http.client
import json
import os
import random
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.environ.get("AGENTBOARD_SRC") or str(Path(__file__).resolve().parents[1] / "src"))   # AGENTBOARD_SRC: another checkout's src, for a before/after
from agentboard import hud, server  # noqa: E402
from agentboard.store import Store  # noqa: E402

WORDS = "backup restore masker chat listener hook plugin doctor report prompt provider board card agent review ask done todo doing".split()
AGENTS = [f"AGENT-{i}" for i in range(1, 13)]


def words(n, rnd):
    return " ".join(rnd.choice(WORDS) for _ in range(n))


def seed(board, cards, chat, rnd=None):
    """A board with `cards` cards in realistic shapes (statuses, agents, logs, subtasks, bodies) and `chat` lines, written in one transaction."""
    rnd = rnd or random.Random(7)
    s = Store(board)
    board.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 11, 7, 9, 0, 0)
    with s.transaction() as tasks:
        for i in range(cards):
            status = rnd.choices(["backlog", "todo", "doing", "done"], weights=[1, 3, 2, 6])[0]
            agent = rnd.choice(AGENTS) if status in ("doing", "done") else None
            when = now + timedelta(minutes=i)
            t = {"id": f"card-{i:05d}-{words(2, rnd).replace(' ', '-')}", "title": f"{words(5, rnd).capitalize()} {i}", "description": words(40, rnd),
                 "status": status, "progress": 100 if status == "done" else rnd.randint(0, 90) if status == "doing" else 0,
                 "status_text": words(8, rnd) if status in ("doing", "done") else "", "ctx": [], "prompt": "",
                 "created": when.isoformat(timespec="seconds"), "updated": (when + timedelta(minutes=rnd.randint(1, 300))).isoformat(timespec="seconds"),
                 "log": [{"at": (when + timedelta(minutes=k)).isoformat(timespec="seconds"), "status": status, "progress": k * 10, "text": words(6, rnd)} for k in range(rnd.randint(2, 9))]}
            if agent:
                t["agent"] = agent
            if status == "doing" and rnd.random() < 0.3:
                t["review"], t["result"] = True, words(10, rnd)
                t["body_md"] = "## Changed\n" + "\n".join(f"- {words(8, rnd)}" for _ in range(4)) + "\n## Checked\n- 675 tests pass\n"
            if i % 4 == 3 and i > 0:   # every fourth card is a subtask of the one before
                t["parent_id"] = tasks[-1]["id"]
                t.pop("review", None)
            if status == "done" and rnd.random() < 0.5:
                t["archived"] = True
            tasks.append(t)
    with s._lock():
        data = s._read()
        data["chat_agents"] = True   # agents may talk: the soak's fake agents post status lines
        for i in range(chat):
            who = rnd.choice(AGENTS + ["ORCH", "you"])
            data["chat_seq"] += 1
            data["chat"].append({"seq": data["chat_seq"], "at": (now + timedelta(seconds=i * 7)).isoformat(timespec="seconds"), "from": who, "kind": "user" if who == "you" else "agent",
                                 "text": words(12, rnd), "to": rnd.choice([None, "all", "ORCH", rnd.choice(AGENTS)]), "topic": rnd.choice(["status", "learn", "help", None])})
        s._write(data)
    return s


def free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


def run_server(store):
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(store, port))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    t = time.perf_counter()
    c.request("GET", path, headers={"Host": f"localhost:{port}", **(headers or {})})
    r = c.getresponse()
    body = r.read()
    dt = time.perf_counter() - t
    c.close()
    return dt, r.status, body, dict(r.getheaders())


def post(port, path, body):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    raw = json.dumps(body).encode()
    t = time.perf_counter()
    c.request("POST", path, body=raw, headers={"Host": f"localhost:{port}", "Content-Type": "application/json", "Origin": f"http://localhost:{port}"})
    r = c.getresponse()
    out = r.read()
    dt = time.perf_counter() - t
    c.close()
    return dt, r.status, out


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def ms(x):
    return f"{x * 1000:.0f} ms"


def kb(n):
    return f"{n / 1024:.0f} KB"


def board_side(board, s, port, n_cards, n_chat, rounds=20):
    out = {}
    f = board / "tasks.json"
    out["tasks.json"] = kb(f.stat().st_size)
    # the store alone
    ts = [time.perf_counter() for _ in range(1)]
    dts = []
    for _ in range(rounds):
        t = time.perf_counter()
        s.load()
        dts.append(time.perf_counter() - t)
    out["store.load (lock + parse + check)"] = f"median {ms(statistics.median(dts))}"
    # the API
    for path, label in (("/api/tasks", "/api/tasks"), ("/api/hud", "/api/hud"), ("/api/chat", "/api/chat (last 200)"), ("/", "page HTML")):
        dts, size, etag = [], 0, None
        for _ in range(rounds):
            dt, code, body, hdr = get(port, path)
            assert code == 200, (path, code, body[:200])
            dts.append(dt)
            size = len(body)
            etag = hdr.get("ETag")
        out[label] = f"median {ms(statistics.median(dts))}, p95 {ms(pct(dts, 95))}, {kb(size)}"
        if etag:
            dts2 = [get(port, path, {"If-None-Match": etag})[0] for _ in range(rounds)]
            codes = {get(port, path, {"If-None-Match": etag})[1]}
            out[label + " unchanged (If-None-Match)"] = f"median {ms(statistics.median(dts2))}, HTTP {codes}"
    # the first poll after a change: the derived cache is cold, so this is the real build cost of each route
    anyid = next(t["id"] for t in s.load() if not t.get("parent_id") and t["id"] not in {x.get("parent_id") for x in s.load()})
    for path, label in (("/api/tasks", "/api/tasks"), ("/api/hud", "/api/hud"), ("/api/chat", "/api/chat (last 200)")):
        dts = []
        for k in range(5):
            s.update(anyid, 0, f"touch {k}")   # a change: the file's inode moves, every cached view is stale
            if path == "/api/hud":
                time.sleep(0)   # the HUD key also has a 5 s clock bucket; the file key alone already misses
            dts.append(get(port, path)[0])
        out[label + " after a change (cold)"] = f"median {ms(statistics.median(dts))}, max {ms(max(dts))}"
    # write latency: claim, update, review through the store (what the CLI does), each a full rewrite of tasks.json
    all_tasks = s.load()
    parents = {t.get("parent_id") for t in all_tasks if t.get("parent_id")}
    todo = [t["id"] for t in all_tasks if t["status"] == "todo" and not t.get("parent_id") and t["id"] not in parents][:rounds]   # childless: a parent's % is computed
    lat = {"claim": [], "update": [], "review": [], "done": []}
    for i, tid in enumerate(todo):
        name = AGENTS[i % len(AGENTS)]
        for op, fn in (("claim", lambda: s.claim(tid, name)), ("update", lambda: s.update(tid, 50, "half way")), ("review", lambda: s.review(tid, "ready")), ("done", lambda: s.update(tid, status="done"))):
            t = time.perf_counter()
            try:
                fn()
            except Exception as e:   # noqa: BLE001  (a blocked card or a rule: skip it, the timing is the point)
                _ = e
                continue
            lat[op].append(time.perf_counter() - t)
    for op, xs in lat.items():
        if xs:
            out[f"store.{op} (full rewrite)"] = f"median {ms(statistics.median(xs))}, p95 {ms(pct(xs, 95))}, max {ms(max(xs))} over {len(xs)}"
    # a POST through the server (the owner's move)
    dts = []
    for tid in [t["id"] for t in s.load() if t["status"] == "todo" and not t.get("parent_id")][:rounds]:
        dt, code, body = post(port, "/api/move", {"id": tid, "status": "backlog"})
        if code == 200:
            dts.append(dt)
    if dts:
        out["POST /api/move"] = f"median {ms(statistics.median(dts))}, p95 {ms(pct(dts, 95))}"
    return out


def startup_time(board, tries=3):
    """Seconds from `agentboard serve` to the port answering, best of `tries`."""
    best = float("inf")
    for _ in range(tries):
        port = free_port()
        env = {**os.environ, "AGENTBOARD_DIR": str(board), "PYTHONPATH": sys.path[0]}
        env.pop("AGENTBOARD_PLUGINS", None)
        t = time.perf_counter()
        p = subprocess.Popen([sys.executable, "-m", "agentboard", "serve", "--no-open", "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while time.perf_counter() - t < 30:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.02)
            best = min(best, time.perf_counter() - t)
        finally:
            p.terminate()
            p.wait(timeout=10)
    return best


def browser(port, cards):
    """First paint and time to cards in headless Chrome over the DevTools protocol (CLAUDE.md recipe). Returns a dict or a reason."""
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    sys.path.insert(0, os.environ.get("AGENTBOARD_QA_PYLIBS", "/tmp/qa_pylibs"))   # where websocket-client was vendored (CLAUDE.md); AGENTBOARD_QA_PYLIBS moves it
    try:
        import websocket  # noqa: F401
    except ImportError:
        return {"browser": "skipped: pip3 install --target /tmp/qa_pylibs websocket-client"}
    if not Path(chrome).exists():
        return {"browser": "skipped: no Chrome"}
    import urllib.request
    dbg = free_port()
    prof = tempfile.mkdtemp(prefix="ab-perf-chrome-")
    p = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", f"--remote-debugging-port={dbg}", "--remote-allow-origins=*", f"--user-data-dir={prof}",
                          "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json/version", timeout=1).read()
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.1)
        req = urllib.request.Request(f"http://127.0.0.1:{dbg}/json/new?about:blank", method="PUT")
        tab = json.loads(urllib.request.urlopen(req, timeout=5).read())
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
        mid = [0]

        def call(method, **params):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == mid[0]:
                    return m.get("result", {})

        def evaluate(expr):
            return call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True).get("result", {}).get("value")
        call("Page.enable")
        call("Runtime.enable")
        for trial in range(3):
            t0 = time.perf_counter()
            call("Page.navigate", url=f"http://localhost:{port}/")
            # wait until the board has drawn its cards
            while time.perf_counter() - t0 < 60:
                n = evaluate("document.querySelectorAll('.card').length") or 0
                if n and n >= min(cards, 50):
                    break
                time.sleep(0.05)
            t_cards = time.perf_counter() - t0
            paint = evaluate("JSON.stringify(performance.getEntriesByType('paint').map(e => [e.name, Math.round(e.startTime)]))")
            nav = evaluate("JSON.stringify((() => { const n = performance.getEntriesByType('navigation')[0]; return n ? {dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd), transfer: n.transferSize} : null })())")
            heap = evaluate("performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null")
            drawn = evaluate("document.querySelectorAll('.card').length")
            # the cost of one poll's re-render: force a render() and time it
            rerender = evaluate("(() => { const t = performance.now(); render(); return Math.round((performance.now() - t) * 10) / 10 })()")
            # the HUD view
            t1 = time.perf_counter()
            evaluate("location.hash = '#/hud'")
            while time.perf_counter() - t1 < 30:
                if evaluate("!!document.querySelector('#hud, .hud, [data-view=hud]') && document.body.innerText.length > 0"):
                    break
                time.sleep(0.05)
            hud_t = time.perf_counter() - t1
            out[f"trial {trial + 1}"] = {"time to cards drawn": ms(t_cards), "cards drawn": drawn, "paint entries (ms)": paint, "navigation (ms)": nav,
                                        "JS heap MB": heap, "render() re-run": f"{rerender} ms", "switch to HUD": ms(hud_t)}
        ws.close()
    except Exception as e:   # noqa: BLE001
        out["browser"] = f"failed: {e.__class__.__name__}: {e}"
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        shutil.rmtree(prof, ignore_errors=True)
    return out


def soak(board, s, port, minutes, agents):
    """`agents` fake agents, each posting one update a second against the real server's store (the CLI's path), while one fake page polls
    /api/tasks and /api/chat once a second. Reports RSS and CPU of this process (the server runs in it) and the write and poll latencies."""
    stop = time.time() + minutes * 60
    lat_w, lat_r = [], []
    cards = [t["id"] for t in s.load() if t["status"] in ("todo", "doing") and not t.get("parent_id")]

    def agent(name, i):
        rnd = random.Random(i)
        mine = cards[i::agents][:5]
        for tid in mine:
            try:
                s.claim(tid, name, force=True)
            except Exception:   # noqa: BLE001
                pass
        n = 0
        while time.time() < stop:
            tid = mine[n % len(mine)] if mine else None
            n += 1
            t = time.perf_counter()
            try:
                if tid:
                    s.update(tid, min(99, n % 100), f"{name} step {n} {words(4, rnd)}")
                if n % 10 == 0:
                    s.chat_send(name, f"{name}: {words(6, rnd)}", "agent", to="all", topic="status")
            except Exception:   # noqa: BLE001
                pass
            lat_w.append(time.perf_counter() - t)
            time.sleep(max(0.0, 1.0 - (time.perf_counter() - t)))

    def page():
        etag = None
        while time.time() < stop:
            t = time.perf_counter()
            dt, code, body, hdr = get(port, "/api/tasks", {"If-None-Match": etag} if etag else None)
            etag = hdr.get("ETag", etag)
            get(port, "/api/chat")
            lat_r.append(time.perf_counter() - t)
            time.sleep(max(0.0, 1.0 - (time.perf_counter() - t)))

    threads = [threading.Thread(target=agent, args=(AGENTS[i % len(AGENTS)], i), daemon=True) for i in range(agents)] + [threading.Thread(target=page, daemon=True)]
    rss0 = rss_mb()
    cpu0 = os.times()
    t0 = time.time()
    for th in threads:
        th.start()
    samples = []
    while time.time() < stop:
        time.sleep(min(30, max(1, stop - time.time())))
        samples.append(rss_mb())
    for th in threads:
        th.join(timeout=5)
    cpu1 = os.times()
    wall = time.time() - t0
    cpu = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    return {"minutes": minutes, "agents": agents, "writes": len(lat_w), "polls": len(lat_r),
            "write latency": f"median {ms(statistics.median(lat_w))}, p95 {ms(pct(lat_w, 95))}, p99 {ms(pct(lat_w, 99))}, max {ms(max(lat_w))}" if lat_w else "none",
            "poll latency (tasks+chat)": f"median {ms(statistics.median(lat_r))}, p95 {ms(pct(lat_r, 95))}, max {ms(max(lat_r))}" if lat_r else "none",
            "RSS MB start -> end (max)": f"{rss0:.0f} -> {rss_mb():.0f} ({max(samples) if samples else rss_mb():.0f})",
            "CPU of this process": f"{cpu:.0f} s over {wall:.0f} s wall = {100 * cpu / wall:.0f}% of one core",
            "tasks.json after": kb((board / "tasks.json").stat().st_size), "snapshots": len(list((board / "backups").glob("*.gz")))}


def rss_mb():
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout.strip()
    return int(out or 0) / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=1000)
    ap.add_argument("--chat", type=int, default=2000)
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--soak", type=float, default=0, metavar="MINUTES")
    ap.add_argument("--agents", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="ab-perf-"))
    os.environ["AGENTBOARD_DIR"] = str(tmp / ".agentboard")
    os.environ.pop("AGENTBOARD_PLUGINS", None)
    board = tmp / ".agentboard"
    t = time.perf_counter()
    s = seed(board, a.cards, a.chat)
    report = {"seed": f"{a.cards} cards, {a.chat} chat lines in {ms(time.perf_counter() - t)}", "python": sys.version.split()[0]}
    srv, port = run_server(s)
    try:
        report["startup (serve -> port answers, best of 3)"] = ms(startup_time(board))
        report.update(board_side(board, s, port, a.cards, a.chat))
        if a.browser:
            report["browser"] = browser(port, a.cards)
        if a.soak:
            report["soak"] = soak(board, s, port, a.soak, a.agents)
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        for k, v in report.items():
            if isinstance(v, dict):
                print(f"{k}:")
                for k2, v2 in v.items():
                    print(f"  {k2}: {v2}")
            else:
                print(f"{k}: {v}")


if __name__ == "__main__":
    main()
