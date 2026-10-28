// Mic buttons for the board's text boxes. The clip is recorded in this browser and sent only to this machine's /api/transcribe,
// where whisper.cpp turns it into text. Nothing leaves the Mac. Hidden when the machine cannot transcribe.
(() => {
  const BASE = window.AB_BASE || '';
  const FIELDS = '#title, #chat-input, .card-reply input[name="text"], #p-reply-text';
  const MAX_MS = 90000;
  let ready = false, active = null;   // active: { rec, chunks, key, btn, timer }
  const MIC = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><rect x="5.5" y="1.5" width="5" height="8" rx="2.5" stroke="currentColor" stroke-width="1.5"/><path d="M3 7.5a5 5 0 0 0 10 0M8 12.5V15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';

  const css = document.createElement('style');
  css.textContent = `.mic { flex: none; width: 34px; height: 34px; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; border: 1px solid var(--line); background: var(--surface, var(--bg)); color: var(--muted); cursor: pointer; }
  .mic:hover { color: var(--text); }
  .mic.rec { color: #fff; background: #d1453b; border-color: #d1453b; animation: micpulse 1.2s ease-in-out infinite; }
  .mic.busy { opacity: .6; cursor: progress; }
  .reply > .mic { justify-self: end; }
  @keyframes micpulse { 50% { box-shadow: 0 0 0 6px rgba(209,69,59,.25); } }
  @media (prefers-reduced-motion: reduce) { .mic.rec { animation: none; } }`;
  document.head.appendChild(css);

  const keyOf = el => el.id ? '#' + el.id : el.closest('[data-reply]') ? '[data-reply="' + el.closest('[data-reply]').dataset.reply + '"] input[name="text"]' : '';
  const say = (btn, text) => { btn.title = text; btn.setAttribute('aria-label', text); };

  function attach(el) {
    if (el.dataset.mic) return;
    el.dataset.mic = '1';
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'mic'; b.innerHTML = MIC; b.dataset.micFor = keyOf(el);
    say(b, 'Speak instead of typing (on this Mac only)');
    el.after(b);
  }
  function scan() { if (ready) document.querySelectorAll(FIELDS).forEach(attach); }

  function insert(el, text) {
    const v = el.value, s = el.selectionStart ?? v.length, e = el.selectionEnd ?? v.length;
    const pre = v.slice(0, s), post = v.slice(e);
    const t = (pre && !/\s$/.test(pre) ? ' ' : '') + text;
    el.value = pre + t + post;
    el.selectionStart = el.selectionEnd = (pre + t).length;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.focus();
  }

  function setBusy(btn, label) { btn.classList.remove('rec'); btn.classList.toggle('busy', !!label); if (label) say(btn, label); else say(btn, 'Speak instead of typing (on this Mac only)'); }
  function btnFor(key) { return [...document.querySelectorAll('.mic')].find(b => b.dataset.micFor === key); }

  async function start(btn) {
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) { say(btn, 'Microphone blocked: allow it for this site in the browser'); return; }
    const chunks = [], rec = new MediaRecorder(stream);
    rec.ondataavailable = ev => { if (ev.data.size) chunks.push(ev.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const a = active; active = null;
      const key = a.key;
      let b = btnFor(key) || btn;
      setBusy(b, 'Transcribing on this Mac…'); b.classList.add('busy');
      try {
        const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
        const buf = new Uint8Array(await blob.arrayBuffer());
        let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        const r = await fetch(BASE + '/api/transcribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audio: btoa(bin) }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || 'could not transcribe');
        b = btnFor(key) || b;
        const field = key ? document.querySelector(key) : null;
        if (field && d.text) insert(field, d.text);
        setBusy(b, '');
        if (!d.text) say(b, 'Heard nothing; try again');
      } catch (e) { setBusy(btnFor(key) || b, ''); say(btnFor(key) || b, 'Voice failed: ' + e.message); }
    };
    rec.start();
    active = { rec, key: btn.dataset.micFor, timer: setTimeout(() => { if (active && active.rec.state === 'recording') active.rec.stop(); }, MAX_MS) };
    btn.classList.add('rec'); say(btn, 'Listening: click again to stop');
  }

  document.addEventListener('mousedown', e => { if (e.target.closest('.mic')) e.preventDefault(); });   // keep the text box focused and its caret
  document.addEventListener('click', e => {
    const btn = e.target.closest('.mic');
    if (!btn || btn.classList.contains('busy')) return;
    if (active) { if (btn.classList.contains('rec')) { clearTimeout(active.timer); active.rec.stop(); } return; }
    start(btn);
  });

  fetch(BASE + '/api/voice').then(r => r.json()).then(s => { ready = !!s.ready; scan(); }).catch(() => {});
  new MutationObserver(() => { if (ready) scan(); }).observe(document.documentElement, { childList: true, subtree: true });
})();
