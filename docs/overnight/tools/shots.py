"""Screenshots of the throwaway board over the DevTools Protocol: python3 shots.py <prefix> <outdir> [port] [views, comma separated]
Wide (1280x860) and narrow (390x844), light and dark: the board, a card's panel, the ORCH chat drawer, an agent thread."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, os.environ.get("QA_PYLIBS", "/tmp/qa_pylibs"))   # pip3 install --target /tmp/qa_pylibs websocket-client
import websocket

PREFIX, OUT = sys.argv[1], sys.argv[2]
BOARD = "http://127.0.0.1:8791/"
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 9333
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
os.makedirs(OUT, exist_ok=True)
ONLY = set(sys.argv[4].split(",")) if len(sys.argv) > 4 else None
_ALL = {
    "board": (BOARD, "", ""),
    "panel": (BOARD, "([...document.querySelectorAll('.card')].find(c => c.textContent.includes('receipts row'))||document.querySelector('.card')).click()", "document.getElementById('p-close')?.click()"),
    "chat": (BOARD, "document.querySelector('.orch-btn')?.click()", "document.getElementById('chat-close')?.click()"),
    "later": (BOARD, "document.getElementById('later-btn').click()", "document.getElementById('later-close')?.click()"),
    "settings": (BOARD, "document.getElementById('cfg-btn').click()", "document.getElementById('cfg-btn').click()"),
    "byagent": (BOARD + "agents", "", ""),
    "load": (BOARD + "hud", "", ""),
    "thread": (BOARD + "agents", "openThread('AGENT-1')", ""),
    "summary": (BOARD + "summary", "", ""),
    "reports": (BOARD + "reports", "", ""),
    "report": (BOARD + "reports", "location.href = document.querySelector('a[href^=\"/reports/\"]').href", ""),
    "shortcuts": (BOARD, "document.dispatchEvent(new KeyboardEvent('keydown', { key: '?', shiftKey: true, bubbles: true }))", ""),
    "error": (BOARD, "showError('Could not send: the board did not answer')", ""),
}
VIEWS = {k: v for k, v in _ALL.items() if not ONLY or k in ONLY}
prof = tempfile.mkdtemp(prefix="polish-chrome-")
proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
                         f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1); break
        except Exception:
            time.sleep(.5)
    tab = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
    n = [0]
    def call(method, **params):
        n[0] += 1; i = n[0]
        ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == i:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
    def js(expr):
        r = call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")
    def shot(name):
        d = call("Page.captureScreenshot", format="png")["data"]
        open(os.path.join(OUT, f"{PREFIX}-{name}.png"), "wb").write(base64.b64decode(d))
    call("Page.enable"); call("Runtime.enable")
    for scheme in ("light", "dark"):
        for size, (w, h) in (("wide", (1280, 860)), ("narrow", (390, 844))):
            call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(size == "narrow"))
            call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            call("Page.navigate", url=BOARD); time.sleep(1.8)
            js("localStorage.clear()")
            tag = f"{size}-{scheme}"
            if not ONLY or "board" in ONLY: shot(f"board-{tag}")
            for view, (url, act, close) in VIEWS.items():
                if url != BOARD: call("Page.navigate", url=url); time.sleep(1.6); js("localStorage.clear()")
                elif view != "board": call("Page.navigate", url=BOARD); time.sleep(1.4)
                if act: js(act); time.sleep(.9)
                shot(f"{view}-{tag}")
                if close: js(close); time.sleep(.5)
    ws.close()
finally:
    proc.terminate()
