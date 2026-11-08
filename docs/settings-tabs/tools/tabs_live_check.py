"""Live check of the Settings tabs. python3 tabs_live_check.py"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, os.environ.get("QA_PYLIBS", "/tmp/qa_pylibs"))   # pip3 install --target /tmp/qa_pylibs websocket-client
import websocket
URL = os.environ.get("AB_URL", "http://127.0.0.1:8795/"); PORT = 9390
prof = tempfile.mkdtemp(prefix="tabs-live-")
proc = subprocess.Popen(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*", f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1); break
        except Exception: time.sleep(.5)
    tab = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True); n = [0]
    errs = []
    def call(m, **p):
        n[0] += 1; i = n[0]; ws.send(json.dumps({"id": i, "method": m, "params": p}))
        while True:
            r = json.loads(ws.recv())
            if r.get("method") == "Runtime.exceptionThrown": errs.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "?")[:200])
            if r.get("method") == "Runtime.consoleAPICalled" and r["params"]["type"] == "error": errs.append("console.error " + str(r["params"]["args"][0].get("value", ""))[:160])
            if r.get("id") == i:
                if "error" in r: raise RuntimeError(f"{m}: {r['error']}")
                return r.get("result", {})
    def js(e): return call("Runtime.evaluate", expression=e, returnByValue=True, awaitPromise=True).get("result", {}).get("value")
    def key(k, **kw): call("Input.dispatchKeyEvent", type="keyDown", key=k, code=kw.get("code", k), windowsVirtualKeyCode=kw.get("vk", 0), text=kw.get("text", "")); call("Input.dispatchKeyEvent", type="keyUp", key=k, code=kw.get("code", k), windowsVirtualKeyCode=kw.get("vk", 0))
    call("Page.enable"); call("Runtime.enable")
    call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    call("Page.navigate", url=URL); time.sleep(2.0); js("localStorage.clear()")
    S = "JSON.stringify((() => { const t = [...document.querySelectorAll('#mix-tabs [role=tab]')]; const sel = t.find(b => b.getAttribute('aria-selected') === 'true'); const pane = document.querySelector('#mix-panes .pane:not([hidden])'); const sh = document.querySelector('#mix .sheet').getBoundingClientRect(); const p = document.getElementById('mix-panes'); return { open: document.getElementById('mix').classList.contains('on'), tabs: t.map(b => b.textContent.trim()), selected: sel && sel.textContent.trim(), tabindex: t.map(b => b.tabIndex), pane: pane && pane.id, hash: location.hash, active: document.activeElement.id || document.activeElement.className || document.activeElement.tagName, sheet: [Math.round(sh.width), Math.round(sh.height)], paneScroll: [p.scrollHeight, p.clientHeight], results: !document.getElementById('mix-results').hidden }; })())"
    print("closed        ", js(S))
    js("document.getElementById('cfg-btn').click()"); time.sleep(.5)
    print("opened        ", js(S))
    for k, vk in (("ArrowDown", 40), ("ArrowDown", 40), ("End", 35), ("Home", 36)):
        key(k, vk=vk); time.sleep(.2); print(f"key {k:10s}", js(S))
    # every pane: does it fit, what does it say
    for tid in ("general", "sound", "agents"):
        js(f"document.querySelector('#stab-{tid}').click()"); time.sleep(.3)
        print(f"pane {tid:8s}", js("(() => { const p = document.getElementById('mix-panes'); return JSON.stringify({scroll: [p.scrollHeight, p.clientHeight], fits: p.scrollHeight <= p.clientHeight + 1, rows: document.querySelectorAll('#mix-panes .pane:not([hidden]) .mix-row').length}); })()"))
    # remembered tab, deep link, hash
    js("document.querySelector('#stab-sound').click()"); js("document.getElementById('mix-close').click()"); time.sleep(.3)
    print("after close   ", js("JSON.stringify({open: document.getElementById('mix').classList.contains('on'), hash: location.hash, remembered: localStorage.getItem('agentboard-settings-tab')})"))
    js("document.getElementById('cfg-btn').click()"); time.sleep(.4); print("reopen        ", js(S))
    js("document.getElementById('mix-close').click()")
    call("Page.navigate", url=URL + "#settings/agents"); time.sleep(1.8); print("deep link     ", js(S))
    js("document.getElementById('mix-close').click()"); call("Page.navigate", url=URL + "#settings"); time.sleep(1.8); print("#settings     ", js(S))
    js("document.getElementById('mix-close').click()"); call("Page.navigate", url=URL + "#settings/nope"); time.sleep(1.8); print("unknown tab   ", js(S))
    # a plugin tab through the API: not drawn while empty, drawn once it has a child, a badge, openSettings
    js("document.getElementById('mix-close').click()")
    js("window.__p = AB.settingsTab('texts', 'Texts', { order: 40 })"); print("empty plugin  ", js("JSON.stringify([...document.querySelectorAll('#mix-tabs [role=tab]')].map(b => b.textContent.trim()))"))
    js("(() => { const h = document.createElement('h3'); h.textContent = 'Texts'; h.id = 'x-head'; const b = document.createElement('div'); b.innerHTML = '<div class=\"mix-row\"><input type=\"checkbox\" id=\"x-t1\"><label for=\"x-t1\">Pull my texts every minute</label><span></span><span class=\"mix-about\">Reads the log for texts from your own number.</span></div>'; __p.append(h, b); })()"); time.sleep(.3)
    print("filled plugin ", js("JSON.stringify([...document.querySelectorAll('#mix-tabs [role=tab]')].map(b => b.textContent.trim()))"))
    js("AB.settingsBadge('texts', true)"); print("badge         ", js("document.querySelector('#stab-texts .dot') ? 'dot' : 'none'"))
    js("AB.openSettings(document.getElementById('x-head'))"); time.sleep(.4); print("openSettings  ", js(S))
    js("(() => { const s = document.createElement('div'); s.className = 'mix-row'; s.innerHTML = '<label>Old plugin row</label>'; AB.settings.append(s); })()"); time.sleep(.2)
    print("AB.settings   ", js("JSON.stringify([...document.querySelectorAll('#mix-tabs [role=tab]')].map(b => b.textContent.trim()))"))
    # search
    js("document.getElementById('mix-close').click()"); js("document.getElementById('cfg-btn').click()"); time.sleep(.3)
    key("/", code="Slash", vk=191, text="/"); time.sleep(.2); print("slash focus   ", js("document.activeElement.id"))
    for ch in "text": key(ch, code="Key" + ch.upper(), vk=ord(ch.upper()), text=ch)
    time.sleep(.3); print("search 'text' ", js("JSON.stringify({results: !document.getElementById('mix-results').hidden, hits: [...document.querySelectorAll('#mix-results .hit')].map(h => h.querySelector('b').textContent + ' @ ' + h.querySelector('.where').textContent), val: document.getElementById('mix-search').value})"))
    key("Enter", vk=13); time.sleep(.5); print("enter         ", js(S), js("document.querySelector('.mix-row.flash')?.textContent.slice(0, 30) || null"))
    for ch in "zzzz": key(ch, code="Key" + ch.upper(), vk=ord(ch.upper()), text=ch)
    js("document.getElementById('mix-search').focus()"); js("(() => { const i = document.getElementById('mix-search'); i.value = 'zzzz'; i.dispatchEvent(new Event('input')); })()"); print("no match      ", js("document.querySelector('#mix-results .none')?.textContent || null"))
    key("Escape", vk=27); time.sleep(.2); print("esc #1        ", js("JSON.stringify({open: document.getElementById('mix').classList.contains('on'), val: document.getElementById('mix-search').value})"))
    key("Escape", vk=27); time.sleep(.3); print("esc #2        ", js("JSON.stringify({open: document.getElementById('mix').classList.contains('on')})"))
    # the theme row and the header switch stay in step
    js("document.getElementById('cfg-btn').click()"); time.sleep(.3); js("document.querySelector('#stab-general').click()")
    js("document.querySelector('[data-theme-set=dark]').click()"); time.sleep(.2)
    print("theme row     ", js("JSON.stringify({attr: document.documentElement.getAttribute('data-theme'), pressed: [...document.querySelectorAll('[data-theme-set]')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.textContent)})"))
    js("document.getElementById('theme').click()"); time.sleep(.2)
    print("header switch ", js("JSON.stringify({attr: document.documentElement.getAttribute('data-theme'), pressed: [...document.querySelectorAll('[data-theme-set]')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.textContent)})"))
    js("document.querySelector('[data-theme-set=auto]').click()")
    # the old controls still work: sound switch, a level, hear it exists
    js("document.querySelector('#stab-sound').click()"); time.sleep(.2)
    print("sound rows    ", js("JSON.stringify({snd: !!document.getElementById('cfg-snd'), amb: !!document.getElementById('cfg-amb'), vol: !!document.getElementById('cfg-vol'), layers: document.querySelectorAll('[id^=lyr-]').length, hear: document.querySelectorAll('[data-hear]').length})"))
    # narrow
    call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True); js("document.getElementById('mix-close').click()"); time.sleep(.3); js("document.getElementById('cfg-btn').click()"); time.sleep(.6)
    print("390 sheet     ", js("JSON.stringify({sheet: [document.querySelector('#mix .sheet').getBoundingClientRect().width, document.querySelector('#mix .sheet').getBoundingClientRect().height], orient: document.getElementById('mix-tabs').getAttribute('aria-orientation'), tabsScrollable: document.getElementById('mix-tabs').scrollWidth > document.getElementById('mix-tabs').clientWidth, overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth})"))
    key("ArrowRight", vk=39); time.sleep(.2); print("390 arrow R   ", js(S))
    print("errors        ", errs[:5])
    ws.close()
finally:
    proc.terminate()
