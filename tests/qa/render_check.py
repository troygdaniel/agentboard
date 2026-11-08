"""Render-check every page of a running board in headless Chrome over the DevTools protocol (overnight-qa-cleanroom).

    python3 tests/qa/render_check.py http://127.0.0.1:<port> <out dir> [--devtools-port 9333]   # a throwaway board, never the live one

For each page x width (1440 wide, 390 narrow) x scheme (light, dark): a screenshot, the console errors and uncaught exceptions, failed
network loads, horizontal overflow (an element wider than the viewport), text under 11px, and images or buttons with no accessible
name. Prints one PASS/FAIL line per page+width+scheme and writes results.json. Headless Chrome runs with its own throwaway profile."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pylibs"))   # pip3 install --target tests/qa/pylibs websocket-client
try:
    import websocket  # noqa: E402
except ImportError:
    sys.exit("needs websocket-client: pip3 install --target tests/qa/pylibs websocket-client")

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
DT = int(sys.argv[sys.argv.index("--devtools-port") + 1]) if "--devtools-port" in sys.argv else 9333
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PAGES = [("board", "/"), ("hud", "/hud"), ("byagent", "/"), ("done-summary", "/")]   # the tabs are reached by clicking below (a #hash is a card deep link, so never that)
WIDTHS = [("wide", 1440, 900), ("narrow", 390, 844)]
SCHEMES = ["light", "dark"]
AUDIT_JS = r"""
(() => {
  const de = document.documentElement, cw = de.clientWidth;
  const all = [...document.querySelectorAll('body *')];
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const wide = all.filter(e => vis(e) && e.getBoundingClientRect().right > cw + 1 && getComputedStyle(e).position !== 'fixed')
                  .slice(0, 6).map(e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : '') + ' right=' + Math.round(e.getBoundingClientRect().right));
  const tiny = all.filter(e => vis(e) && e.children.length === 0 && (e.textContent || '').trim() && parseFloat(getComputedStyle(e).fontSize) < 11)
                  .slice(0, 6).map(e => e.tagName.toLowerCase() + ' ' + getComputedStyle(e).fontSize + ' "' + (e.textContent || '').trim().slice(0, 25) + '"');
  const unnamed = [...document.querySelectorAll('button, a, [role=button], input, img')].filter(e => vis(e) && !(e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('alt') || (e.textContent || '').trim() || e.getAttribute('aria-labelledby') || e.getAttribute('placeholder')))
                  .slice(0, 6).map(e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : ''));
  const bg = getComputedStyle(document.body).backgroundColor;
  const tabs = [...document.querySelectorAll('[role=tab], .tab, nav button')].map(b => (b.textContent || '').trim()).filter(Boolean).slice(0, 8);
  return {scrollW: de.scrollWidth, clientW: cw, overflowX: de.scrollWidth > cw + 1, wide, tiny, unnamed, bodyBg: bg, title: document.title, cards: document.querySelectorAll('.card, article, [data-id]').length, tabs};
})()
"""


class Tab:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self.n = 0
        self.events = []

    def send(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                return m.get("result", m)
            self.events.append(m)

    def drain(self, seconds):
        end = time.time() + seconds
        self.ws.settimeout(0.2)
        while time.time() < end:
            try:
                self.events.append(json.loads(self.ws.recv()))
            except websocket.WebSocketTimeoutException:
                pass
        self.ws.settimeout(30)

    def evaluate(self, js):
        r = self.send("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


profile = OUT / "chrome-profile"
chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={DT}", "--remote-allow-origins=*", f"--user-data-dir={profile}",
                           "--no-first-run", "--hide-scrollbars", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{DT}/json/version", timeout=1).read()
            break
        except Exception:   # noqa: BLE001
            time.sleep(0.2)
    results = []
    for pname, path in PAGES:
        for wname, w, h in WIDTHS:
            for scheme in SCHEMES:
                req = urllib.request.Request(f"http://127.0.0.1:{DT}/json/new?about:blank", method="PUT")
                info = json.loads(urllib.request.urlopen(req, timeout=10).read())
                tab = Tab(info["webSocketDebuggerUrl"])
                tab.send("Page.enable")
                tab.send("Runtime.enable")
                tab.send("Log.enable")
                tab.send("Network.enable")
                tab.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(w < 500))
                tab.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
                tab.send("Page.navigate", url=BASE + path)
                tab.drain(2.5)
                if pname == "byagent":
                    tab.evaluate("(() => { const b = [...document.querySelectorAll('button,[role=tab]')].find(x => /by agent/i.test(x.textContent)); if (b) b.click(); return !!b; })()")
                    tab.drain(1.2)
                if pname == "done-summary":
                    tab.evaluate("(() => { const b = [...document.querySelectorAll('button,a')].find(x => /^summary$/i.test(x.textContent.trim())); if (b) b.click(); return !!b; })()")
                    tab.drain(1.2)
                audit = tab.evaluate(AUDIT_JS) or {}
                shot = tab.send("Page.captureScreenshot", format="png", captureBeyondViewport=False)
                png = OUT / f"{pname}-{wname}-{scheme}.png"
                import base64
                png.write_bytes(base64.b64decode(shot.get("data", "")))
                errors = []
                for ev in tab.events:
                    m = ev.get("method")
                    p = ev.get("params", {})
                    if m == "Runtime.exceptionThrown":
                        errors.append("exception: " + str(p.get("exceptionDetails", {}).get("text", ""))[:160] + " " + str((p.get("exceptionDetails", {}).get("exception") or {}).get("description", ""))[:160])
                    elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
                        errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", "")))[:120] for a in p.get("args", [])))
                    elif m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
                        errors.append("log: " + str(p["entry"].get("text", ""))[:160] + " " + str(p["entry"].get("url", ""))[-60:])
                    elif m == "Network.loadingFailed" and not p.get("canceled"):
                        errors.append("load failed: " + str(p.get("errorText", ""))[:80])
                ok = not errors and not audit.get("overflowX") and not audit.get("wide") and not audit.get("unnamed")
                row = {"page": pname, "width": wname, "scheme": scheme, "ok": ok, "errors": errors[:6], "overflowX": audit.get("overflowX"), "wide": audit.get("wide"),
                       "tiny": audit.get("tiny"), "unnamed": audit.get("unnamed"), "bodyBg": audit.get("bodyBg"), "title": audit.get("title"), "cards": audit.get("cards"), "shot": png.name}
                results.append(row)
                notes = []
                if errors:
                    notes.append(f"{len(errors)} console/network errors")
                if audit.get("overflowX") or audit.get("wide"):
                    notes.append("overflow: " + "; ".join(audit.get("wide") or ["page"]))
                if audit.get("unnamed"):
                    notes.append("unnamed controls: " + ", ".join(audit["unnamed"]))
                if audit.get("tiny"):
                    notes.append("text under 11px: " + "; ".join(audit["tiny"][:3]))
                print(("PASS  " if ok else "FAIL  ") + f"{pname:12} {wname:6} {scheme:5} bg={audit.get('bodyBg')}" + ("  [" + " | ".join(notes) + "]" if notes else ""), flush=True)
                tab.ws.close()
                urllib.request.urlopen(f"http://127.0.0.1:{DT}/json/close/{info['id']}", timeout=5).read()
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    bad = [r for r in results if not r["ok"]]
    print(f"\nRENDER: {len(results) - len(bad)} of {len(results)} views clean")
    sys.exit(1 if bad else 0)
finally:
    chrome.terminate()
    try:
        chrome.wait(timeout=5)
    except subprocess.TimeoutExpired:
        chrome.kill()
