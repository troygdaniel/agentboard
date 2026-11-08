"""Screenshots of the built Settings tabs on a throwaway board: python3 tabs_shots.py <prefix> <outdir> [url]"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, os.environ.get("QA_PYLIBS", "/tmp/qa_pylibs"))   # pip3 install --target /tmp/qa_pylibs websocket-client
import websocket
PREFIX, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
URL = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8795/"; PORT = 9392
TEXTS = """(() => { const p = AB.settingsTab('texts', 'Texts', { order: 40 }); const h = document.createElement('h3'); h.id = 'x-head'; h.textContent = 'Texts'; const b = document.createElement('div');
  b.innerHTML = '<div class="mix-row"><input type="checkbox" id="x1" checked><label for="x1">Pull my texts every minute</label><span></span><span class="mix-about">Reads the log for texts from your own number and makes a Todo card from each. Nothing else.</span></div><div class="mix-row plain lv"><span></span><label>Text me back</label><span class="seg" role="group"><button class="btn" aria-pressed="false">Off</button><button class="btn" aria-pressed="true">Dry run</button><button class="btn" aria-pressed="false">Send</button></span><span class="mix-about">Dry run: nothing is sent. Latest reply it would have sent, 2m ago.</span></div>'; p.append(h, b); AB.settingsBadge('texts', true); })()"""
prof = tempfile.mkdtemp(prefix="tabs-shots-")
proc = subprocess.Popen(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*", f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1); break
        except Exception: time.sleep(.5)
    tab = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True); n = [0]
    def call(m, **p):
        n[0] += 1; i = n[0]; ws.send(json.dumps({"id": i, "method": m, "params": p}))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == i: return r.get("result", {})
    def js(e): return call("Runtime.evaluate", expression=e, returnByValue=True).get("result", {}).get("value")
    def shot(name): open(os.path.join(OUT, f"{PREFIX}-{name}.png"), "wb").write(base64.b64decode(call("Page.captureScreenshot", format="png")["data"]))
    call("Page.enable")
    for scheme in ("light", "dark"):
        for size, (w, h) in (("wide", (1280, 860)), ("narrow", (390, 844))):
            call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(w < 700))
            call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            call("Page.navigate", url=URL); time.sleep(1.8); js("localStorage.clear()")
            if PREFIX != "before": js(TEXTS)
            js("document.getElementById('cfg-btn').click()"); time.sleep(.6)
            tags = ["general", "sound", "agents", "texts", "security", "backup"] if PREFIX != "before" else ["sheet"]
            for t in tags:
                if PREFIX != "before": js(f"document.getElementById('stab-{t}').click()"); time.sleep(.4)
                shot(f"{t}-{size}-{scheme}")
            if PREFIX != "before":
                js("(() => { const i = document.getElementById('mix-search'); i.value = 'sound'; i.dispatchEvent(new Event('input')); })()"); time.sleep(.3); shot(f"search-{size}-{scheme}")
    ws.close()
finally:
    proc.terminate()
