"""Focus stays in the Settings sheet, and a deep link to a tab a plugin registers late: python3 tabs_focus_and_deeplink_check.py (AB_URL=... for another board)."""
import json, os, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, os.environ.get("QA_PYLIBS", "/tmp/qa_pylibs"))   # pip3 install --target /tmp/qa_pylibs websocket-client
import websocket
PORT = 9394; URL = os.environ.get("AB_URL", "http://127.0.0.1:8795/")
prof = tempfile.mkdtemp(prefix="tabs-fix-")
proc = subprocess.Popen(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*", f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1); break
        except Exception: time.sleep(.5)
    tab = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True); n = [0]; errs = []
    def call(m, **p):
        n[0] += 1; i = n[0]; ws.send(json.dumps({"id": i, "method": m, "params": p}))
        while True:
            r = json.loads(ws.recv())
            if r.get("method") == "Runtime.exceptionThrown": errs.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "?")[:200])
            if r.get("id") == i: return r.get("result", {})
    def js(e): return call("Runtime.evaluate", expression=e, returnByValue=True).get("result", {}).get("value")
    def key(k, vk, shift=False): 
        mod = 8 if shift else 0
        call("Input.dispatchKeyEvent", type="keyDown", key=k, code=k, windowsVirtualKeyCode=vk, modifiers=mod); call("Input.dispatchKeyEvent", type="keyUp", key=k, code=k, windowsVirtualKeyCode=vk, modifiers=mod)
    call("Page.enable"); call("Runtime.enable"); call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    INSIDE = "(() => { const a = document.activeElement; return JSON.stringify({inside: !!a.closest('#mix .sheet'), id: a.id || a.className || a.tagName, text: (a.textContent || a.getAttribute('aria-label') || '').trim().slice(0, 24)}); })()"
    # --- the focus trap
    call("Page.navigate", url=URL); time.sleep(2); js("localStorage.clear()")
    js("document.getElementById('cfg-btn').click()"); time.sleep(.4)
    js("document.getElementById('stab-agents').click()"); time.sleep(.2)   # a short pane: few controls
    outside = 0; seen = []
    for i in range(14):
        key("Tab", 9); time.sleep(.05); r = json.loads(js(INSIDE)); seen.append(r["id"][:14]); outside += 0 if r["inside"] else 1
    print("Tab x14      outside the sheet:", outside, seen)
    js("document.getElementById('mix-close').focus()"); outside = 0; seen = []
    for i in range(6):
        key("Tab", 9, shift=True); time.sleep(.05); r = json.loads(js(INSIDE)); seen.append(r["id"][:14]); outside += 0 if r["inside"] else 1
    print("Shift+Tab x6 outside the sheet:", outside, seen)
    js("document.getElementById('mix-close').focus()"); key("Tab", 9, shift=True); time.sleep(.05); print("Shift+Tab from close ->", js(INSIDE))
    # --- the cold-load deep link: the plugin registers its tab late
    call("Page.navigate", url="about:blank"); call("Page.navigate", url=URL + "#settings/texts"); time.sleep(1.2)
    S = "JSON.stringify({open: document.getElementById('mix').classList.contains('on'), selected: document.querySelector('#mix-tabs [aria-selected=true]')?.textContent.trim(), hash: location.hash, tabs: [...document.querySelectorAll('#mix-tabs [role=tab]')].map(b => b.textContent.trim())})"
    print("before plugin:", js(S))
    js("(() => { const p = AB.settingsTab('texts', 'Texts', { order: 40 }); const h = document.createElement('h3'); h.textContent = 'Texts'; const d = document.createElement('div'); d.innerHTML = '<div class=\"mix-row\"><input type=\"checkbox\" id=\"x1\"><label for=\"x1\">Pull my texts</label></div>'; p.append(h, d); })()"); time.sleep(.4)
    print("plugin arrived:", js(S))
    # a person's own choice before the plugin arrives cancels the wait
    call("Page.navigate", url="about:blank"); call("Page.navigate", url=URL + "#settings/facts"); time.sleep(1.2)
    js("document.getElementById('stab-sound').click()"); time.sleep(.2)
    js("(() => { const p = AB.settingsTab('facts', 'Facts', { order: 50 }); const d = document.createElement('div'); d.innerHTML = '<div class=\"mix-row\"><label>Facts row</label></div>'; p.append(d); })()"); time.sleep(.4)
    print("chose Sound first, then Facts arrives:", js(S))
    # openSettings before the pane has anything
    js("document.getElementById('mix-close').click()"); time.sleep(.2)
    js("window.__q = AB.settingsTab('later', 'Later tab', { order: 60 })"); js("AB.openSettings(__q)"); time.sleep(.2)
    print("openSettings(empty pane):", js(S))
    js("(() => { const d = document.createElement('div'); d.innerHTML = '<div class=\"mix-row\"><label>A row</label></div>'; __q.append(d); })()"); time.sleep(.3)
    print("then it gets a row     :", js(S))
    # search hit focuses the row's control
    js("document.getElementById('mix-close').click()"); js("document.getElementById('cfg-btn').click()"); time.sleep(.3)
    js("(() => { const i = document.getElementById('mix-search'); i.focus(); i.value = 'rain'; i.dispatchEvent(new Event('input')); })()"); time.sleep(.2)
    key("Enter", 13); time.sleep(.4); print("search hit focus:", js("document.activeElement.id || document.activeElement.tagName"))
    print("errors:", errs[:3])
    ws.close()
finally:
    proc.terminate()
