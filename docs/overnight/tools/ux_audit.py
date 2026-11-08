"""Measured UX audit of the throwaway board over the DevTools Protocol: python3 ux_audit.py [port] [board url] > out.json
For each theme x width x view: text contrast (computed, alpha-composited), tap targets, missing accessible names, horizontal overflow,
header height; plus, once per theme: keyboard focus rings through a Tab walk, reduced-motion coverage, layout shift while opening drawers."""
import json, os, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, os.environ.get("QA_PYLIBS", "/tmp/qa_pylibs"))   # pip3 install --target /tmp/qa_pylibs websocket-client
import websocket

BOARD = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8791/"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9334
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
prof = tempfile.mkdtemp(prefix="audit-chrome-")
proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
                         f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

PAGE_JS = r"""
(() => {
  const parse = c => {
    let m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = c.match(/^color\(srgb ([^)]+)\)$/);
    if (m) { const p = m[1].split(/[ \/]+/).filter(Boolean).map(Number); return { r: p[0] * 255, g: p[1] * 255, b: p[2] * 255, a: p.length > 3 ? p[3] : 1 }; }
    return null;
  };
  const over = (f, b) => { const a = f.a + b.a * (1 - f.a); return a ? { r: (f.r * f.a + b.r * b.a * (1 - f.a)) / a, g: (f.g * f.a + b.g * b.a * (1 - f.a)) / a, b: (f.b * f.a + b.b * b.a * (1 - f.a)) / a, a } : b; };
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  const visible = e => { const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none') return false; const r = e.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false;
    for (let n = e; n && n !== document.body; n = n.parentElement) { const c = getComputedStyle(n); if (c.visibility === 'hidden' || c.display === 'none' || +c.opacity === 0) return false; }
    // the whole page, not the first screenful (an earlier version of this audit only looked inside the viewport and missed everything below
    // the fold: the Summary page's links and badges); a closed drawer is `visibility: hidden`, so it is still skipped above
    return r.right > 0 && r.left < document.documentElement.scrollWidth; };
  const sel = e => { let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id; const c = [...e.classList].slice(0, 2).join('.'); if (c) s += '.' + c; return s; };
  const backdrop = e => {
    let layers = [], grad = false;
    for (let n = e; n; n = n.parentElement) {
      const cs = getComputedStyle(n); const c = parse(cs.backgroundColor);
      if (cs.backgroundImage !== 'none') grad = true;
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let base = layers.length && layers[layers.length - 1].a >= 1 ? layers.pop() : { r: 255, g: 255, b: 255, a: 1 };
    while (layers.length) base = over(layers.pop(), base);
    return { c: base, grad };
  };
  const out = { contrast: [], small: [], noname: [], overflow: null, header: null };
  const seen = new Set();
  for (const e of document.body.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'SVG', 'PATH'].includes(e.tagName.toUpperCase())) continue;
    const own = [...e.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(' ');
    if (!own || !visible(e) || e.closest('[disabled],[aria-disabled=true]')) continue;
    const cs = getComputedStyle(e); const fg = parse(cs.color); if (!fg) continue;
    let op = 1; for (let n = e; n; n = n.parentElement) op *= +getComputedStyle(n).opacity;
    const { c: bg, grad } = backdrop(e);
    const f = { ...fg, a: fg.a * op }; const eff = over(f, bg);
    const size = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700, large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5, r = ratio(eff, bg);
    if (r < need) { const k = sel(e) + '|' + own.slice(0, 24); if (!seen.has(k)) { seen.add(k); out.contrast.push({ el: sel(e), text: own.slice(0, 40), ratio: +r.toFixed(2), need, size, grad }); } }
  }
  const act = 'button,a[href],input,select,textarea,[role=button],[role=tab],[tabindex]:not([tabindex="-1"]),summary';
  for (const e of document.querySelectorAll(act)) {
    if (!visible(e) || e.disabled) continue;
    const r = e.getBoundingClientRect();
    const ps = getComputedStyle(e, '::after'); const pw = ps.content !== 'none' && ps.position === 'absolute' ? parseFloat(ps.width) || 0 : 0, ph = ps.content !== 'none' && ps.position === 'absolute' ? parseFloat(ps.height) || 0 : 0;
    if (Math.max(r.width, pw) < 24 || Math.max(r.height, ph) < 24) out.small.push({ el: sel(e), w: Math.round(Math.max(r.width, pw)), h: Math.round(Math.max(r.height, ph)), text: (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 24) });
    const name = (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.textContent || e.getAttribute('title') || (e.labels && e.labels.length ? 'label' : '') || '').trim();
    const hasImgAlt = e.querySelector && e.querySelector('img[alt]:not([alt=""])');
    if (!name && !hasImgAlt) out.noname.push({ el: sel(e), placeholder: e.getAttribute('placeholder') || '' });
    else if (e.tagName === 'INPUT' && !e.getAttribute('aria-label') && !(e.labels && e.labels.length) && !e.getAttribute('aria-labelledby')) out.noname.push({ el: sel(e), placeholder: e.getAttribute('placeholder') || '', note: 'placeholder only' });
  }
  out.overflow = { scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth };
  const h = document.querySelector('header, .top'); if (h) out.header = Math.round(h.getBoundingClientRect().height);
  return JSON.stringify(out);
})()
"""

try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1); break
        except Exception: time.sleep(.5)
    tab = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")))
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=40, suppress_origin=True)
    n = [0]
    def call(method, **params):
        n[0] += 1; i = n[0]
        ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == i:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
    def js(expr): return call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True).get("result", {}).get("value")
    call("Page.enable"); call("Runtime.enable")
    res = {"views": {}, "focus": {}, "motion": {}, "shift": {}}
    # view -> (path under the board, what to run once it has loaded, seconds to wait after); "0" runs nothing
    ALL_VIEWS = {
        "board": ("", "0", 0),
        "panel": ("", "([...document.querySelectorAll('.card')].find(c => c.textContent.includes('receipts row')) || document.querySelector('.card')).click()", .9),
        "chat": ("", "document.querySelector('.orch-btn')?.click()", .9),
        "later": ("", "document.getElementById('later-btn')?.click()", .9),
        "settings": ("", "document.getElementById('cfg-btn')?.click()", .9),
        # the views round 2 skipped
        "byagent": ("agents", "0", 0),
        "thread": ("agents", "openThread('AGENT-1')", 1.2),
        "load": ("hud", "0", 3.0),
        "summary": ("summary", "0", .5),
        "reports": ("reports", "0", .5),
        "report": ("reports", "location.href = document.querySelector('a[href^=\"/reports/\"]').href", 1.5),
        "shortcuts": ("", "document.dispatchEvent(new KeyboardEvent('keydown', { key: '?', shiftKey: true, bubbles: true }))", .6),
        "error": ("", "showError('Could not send: the board did not answer')", .6),
        "panelconv": ("", "([...document.querySelectorAll('.card')].find(c => c.textContent.includes('receipts row')) || document.querySelector('.card')).click(); setTimeout(() => [...document.querySelectorAll('#panel [role=tab], #panel button')].find(t => /^Conversation/.test(t.textContent.trim()))?.click(), 500)", 1.4),
    }
    ONLY = sys.argv[3].split(",") if len(sys.argv) > 3 else None   # a list of views: audit just those (no focus walk, motion or shift)
    VIEWS = {k: v for k, v in ALL_VIEWS.items() if (k in ONLY if ONLY else k in ("board", "panel", "chat", "later", "settings"))}
    for scheme in ("light", "dark"):
        call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}, {"name": "prefers-reduced-motion", "value": "no-preference"}])
        for size, (w, h) in (("wide", (1280, 860)), ("narrow", (390, 844))):
            call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(size == "narrow"))
            for view, (path, act, wait) in VIEWS.items():
                call("Page.navigate", url=BOARD.rstrip("/") + "/" + path); time.sleep(1.6); js("localStorage.clear()")
                if act != "0": js(act); time.sleep(wait)
                res["views"][f"{scheme}-{size}-{view}"] = json.loads(js(PAGE_JS))
        if ONLY: continue
        # keyboard focus rings: Tab through the board at wide
        call("Emulation.setDeviceMetricsOverride", width=1280, height=860, deviceScaleFactor=1, mobile=False)
        call("Page.navigate", url=BOARD); time.sleep(1.6); js("document.body.focus()")
        rows = []
        for _ in range(70):
            call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9); call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
            r = js("""(() => { const e = document.activeElement; if (!e || e === document.body) return null; const cs = getComputedStyle(e); const b = e.getBoundingClientRect();
              return JSON.stringify({ el: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.classList[0] ? '.' + e.classList[0] : ''), text: (e.getAttribute('aria-label') || e.textContent || e.placeholder || '').trim().slice(0, 28),
              outline: cs.outlineStyle + ' ' + cs.outlineWidth, shadow: cs.boxShadow === 'none' ? 'none' : 'yes', ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0, inview: b.top >= 0 && b.bottom <= innerHeight, x: Math.round(b.left), y: Math.round(b.top) }); })()""")
            if r: rows.append(json.loads(r))
        res["focus"][scheme] = rows
        # reduced motion: animations and long transitions still running
        for rm in ("no-preference", "reduce"):
            call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}, {"name": "prefers-reduced-motion", "value": rm}])
            call("Page.navigate", url=BOARD); time.sleep(1.6)
            js("document.querySelector('.orch-btn')?.click()"); time.sleep(.2)
            res["motion"][f"{scheme}-{rm}"] = js("""JSON.stringify(document.getAnimations().map(a => ({ n: a.animationName || a.transitionProperty || '?', el: (a.effect && a.effect.target ? a.effect.target.tagName.toLowerCase() + '.' + [...a.effect.target.classList].slice(0,1).join('') : ''), dur: a.effect ? a.effect.getComputedTiming().duration : 0, iter: a.effect ? a.effect.getComputedTiming().iterations : 0 })).filter(a => a.dur > 1))""")
    # layout shift while the page loads, a drawer opens and one poll passes
    if ONLY: ws.close(); print(json.dumps(res)); sys.exit(0)
    call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}, {"name": "prefers-reduced-motion", "value": "no-preference"}])
    for size, (w, h) in (("wide", (1280, 860)), ("narrow", (390, 844))):
        call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(size == "narrow"))
        call("Page.addScriptToEvaluateOnNewDocument", source="window.__cls=[];new PerformanceObserver(l=>{for(const e of l.getEntries()) if(!e.hadRecentInput) window.__cls.push({v:e.value,t:Math.round(e.startTime),n:(e.sources&&e.sources[0]&&e.sources[0].node?(e.sources[0].node.tagName||'').toLowerCase()+'.'+((e.sources[0].node.classList||[])[0]||''):'')})}).observe({type:'layout-shift',buffered:true})")
        call("Page.navigate", url=BOARD); time.sleep(2.0)
        js("document.querySelector('.orch-btn')?.click()"); time.sleep(1.0)
        js("document.getElementById('chat-close')?.click()"); time.sleep(.6)
        js("(document.querySelector('.card[data-id=\"build-the-receipts-row-for-the-chat\"]')||document.querySelector('.card')).click()"); time.sleep(1.0)
        res["shift"][size] = json.loads(js("JSON.stringify(window.__cls||[])"))
    ws.close()
    print(json.dumps(res))
finally:
    proc.terminate()
