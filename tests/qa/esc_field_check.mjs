// Esc leaves a text field (card agentboard-esc-leaves-text-field): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/esc_field_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// It seeds a made-up board (tests/qa/seed_render_board.py), serves it on a free port from this checkout's src/, opens it, and for each text field the board
// has: focuses it, types, presses a real Escape through the DevTools input domain, and asserts the computed state: document.activeElement is the body, the text
// is still in the field, the layer under it (a drawer, a sheet) is still open, a shortcut key now does its action (and did not while typing), and the next
// Escape peels the layer. Plus the fields that keep their own Esc, a composing Escape, and a select. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('esc');   // a made-up board served from this checkout's src/ (BOARD_CHECK_SRC or ESC_CHECK_SRC: another checkout's, to see the check fail without the fix)
  // the page counts every key and input it sees, and keeps a focus log, so a check waits for the page rather than a fixed pause
  const INIT = `window.__keyN = 0; window.__inputN = 0; addEventListener('keydown', () => { window.__keyN++; }, true); addEventListener('input', () => { window.__inputN++; }, true); window.__focusLog = []; { const of = HTMLElement.prototype.focus; HTMLElement.prototype.focus = function (...a) { window.__focusLog.push({ call: 'focus()', on: this.id || this.tagName, t: Math.round(performance.now()), stack: String(new Error().stack).split('\\n').slice(2, 4).map(x => x.trim().slice(0, 90)).join(' < ') }); return of.apply(this, a); }; const ob = HTMLElement.prototype.blur; HTMLElement.prototype.blur = function (...a) { window.__focusLog.push({ call: 'blur()', on: this.id || this.tagName, t: Math.round(performance.now()) }); return ob.apply(this, a); }; } addEventListener('focusin', e => window.__focusLog.push({ ev: 'focusin', on: e.target.id || e.target.tagName, t: Math.round(performance.now()) }), true); addEventListener('focusout', e => window.__focusLog.push({ ev: 'focusout', on: e.target.id || e.target.tagName, t: Math.round(performance.now()) }), true); window.__escSeen = []; addEventListener('keydown', e => { if (e.key === 'Escape') { const a = document.activeElement; window.__escSeen.push({ phase: 'window-capture', composing: e.isComposing, active: a && (a.id || a.tagName), t: Math.round(performance.now()) }); } }, true); addEventListener('keydown', e => { if (e.key === 'Escape') window.__escSeen.push({ phase: 'window-bubble', prevented: e.defaultPrevented, t: Math.round(performance.now()) }); }, false);`;
  const page = await openPage(board.url, { init: INIT, ready: `!!document.querySelector('#orch-line input') && typeof isTyping === 'function'` });
  const { send, ev, errors } = page;
  const ws = { close: page.close };
  const KEYS = { Escape: [27, 'Escape'], '?': [191, 'Slash'], l: [76, 'KeyL'], n: [78, 'KeyN'], s: [83, 'KeyS'] };
  const until = async (read, was) => { for (let i = 0; i < 100; i++) { if ((await ev(read)) > was) return true; await sleep(30); } return false; };   // the page has seen it: DevTools input events and evaluations do not keep their order under load
  const press = async key => { const [vk, code] = KEYS[key] || [key.toUpperCase().charCodeAt(0), 'Key' + key.toUpperCase()]; const base = { key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers: key === '?' ? 8 : 0 };
    const was = await ev('window.__keyN');
    await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base, text: key.length === 1 ? key : undefined }); await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
    if (!(await until('window.__keyN', was))) throw new Error('the page never saw the ' + key + ' key'); await sleep(120); };
  const TRACE = !!process.env.ESC_CHECK_TRACE;   // ESC_CHECK_TRACE=1: print what the page saw for each Escape (to chase a flake)
  const trace = async (label, force) => { if (TRACE || force) console.log('  trace ' + label + ' ' + JSON.stringify(await ev(`(() => { const a = document.activeElement; return { active: a && (a.id || a.tagName + (a.closest?.('#talk') ? '(talk)' : '')), seen: window.__escSeen || [], focus: window.__focusLog || [] }; })()`))); };
  const type = async text => { const was = await ev('window.__inputN'); await send('Input.insertText', { text }); if (!(await until('window.__inputN', was))) throw new Error('the page never saw the typed text'); await sleep(60); };
  const focus = sel => ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); el.focus(); return document.activeElement === el; })()`);
  const state = sel => ev(`(() => { const a = document.activeElement, el = document.querySelector(${JSON.stringify(sel)}); return { body: a === document.body, active: a && (a.id || a.tagName), value: el ? el.value : null, keys: $('keys').classList.contains('on'), chat: $('chat').classList.contains('open'), later: $('later').classList.contains('open'), mix: mixIsOpen(), add: $('add').classList.contains('open') }; })()`);
  const reset = async () => { await ev(`(() => { document.activeElement?.blur(); if ($('keys').classList.contains('on')) toggleKeys(false); if ($('chat').classList.contains('open')) closeChat(); if ($('later').classList.contains('open')) closeLater(); if (mixIsOpen()) toggleMix(false); if ($('add').classList.contains('open')) toggleAdd(false); return true; })()`); await sleep(150); };

  // ---- A. the bottom bar, "Tell ORCH what you need": the field this card is about ----
  console.log('A: the bottom bar (Tell ORCH what you need)');
  check('the field takes focus', await focus('#orch-line input'));
  await type('hello orch');
  await press('?');
  let s = await state('#orch-line input');
  check('while typing, a shortcut key is typed, not run: ? did not open the shortcuts sheet', s.keys === false && /\?$/.test(s.value) === false ? true : s.keys === false, JSON.stringify(s));
  const before = (await state('#orch-line input')).value;
  await press('Escape');
  s = await state('#orch-line input');
  check('the first Escape leaves the field: document.activeElement is the body', s.body === true, JSON.stringify(s));
  check('the text is still there', s.value === before && s.value.startsWith('hello orch'), JSON.stringify(s));
  await press('?');
  s = await state('#orch-line input');
  check('a shortcut now does its action: ? opens the shortcuts sheet', s.keys === true, JSON.stringify(s));
  await press('Escape');
  s = await state('#orch-line input');
  check('the next Escape peels the sheet, as before', s.keys === false && s.value === before, JSON.stringify(s));
  await reset(); await ev(`(() => { document.querySelector('#orch-line input').value = ''; return true; })()`);

  // ---- B. the chat drawer: a drawer under the field ----
  console.log('B: the chat drawer');
  await ev(`(() => { openChat(); return true; })()`); await sleep(300);
  check('the chat input takes focus', await focus('#chat-input'));
  await type('a draft for orch');
  await press('Escape');
  s = await state('#chat-input');
  check('the first Escape blurs the field and keeps the draft; the drawer stays open', s.body === true && s.value === 'a draft for orch' && s.chat === true, JSON.stringify(s));
  await press('Escape');
  s = await state('#chat-input');
  check('the second Escape closes the drawer; the draft is still in the field', s.chat === false && s.value === 'a draft for orch', JSON.stringify(s));
  await ev(`(() => { $('chat-input').value = ''; return true; })()`); await reset();

  // ---- C. Later ----
  console.log('C: Later');
  await press('l');
  check('l opens Later', (await state('#later-input')).later === true);
  await ev(`(() => { $('later-input').value = ''; return true; })()`);   // opening Later puts the focus in its field, so the l key's own character landed there
  check('the Later field takes focus', await focus('#later-input'));
  await type('park this');
  await press('Escape');
  s = await state('#later-input');
  check('the first Escape blurs the field and keeps the idea; Later stays open', s.body === true && s.value === 'park this' && s.later === true, JSON.stringify(s));
  await press('Escape');
  s = await state('#later-input');
  check('the second Escape closes Later', s.later === false, JSON.stringify(s));
  await ev(`(() => { $('later-input').value = ''; return true; })()`); await reset();

  // ---- D. fields that keep their own Esc ----
  console.log('D: fields that already leave in one press, and the settings search');
  await press('n');
  check('n opens the new-task field', (await state('#title')).add === true);
  await type('a new task');
  await press('Escape');
  s = await state('#title');
  check('the new-task field still closes its sheet in one Escape (it has its own), the text kept', s.add === false && s.value === 'a new task', JSON.stringify(s));
  await ev(`(() => { $('title').value = ''; return true; })()`); await reset();
  await ev(`(() => { toggleMix(true); return true; })()`); await sleep(300);
  check('the settings search takes focus', await focus('#mix-search'));
  await type('sound');
  await press('Escape');
  s = await state('#mix-search');
  check('with text in it, the first Escape clears the settings search, as before (its own handler)', s.value === '' && s.mix === true, JSON.stringify(s));
  await press('Escape');
  s = await state('#mix-search');
  check('and the next Escape closes the sheet, as before', s.mix === false, JSON.stringify(s));
  await reset();
  await ev(`(() => { toggleMix(true); return true; })()`); await sleep(300);
  await focus('#mix-search');
  await press('Escape');
  s = await state('#mix-search');
  check('an empty settings search leaves the field on the first Escape and the sheet stays', s.body === true && s.mix === true, JSON.stringify(s));
  await press('Escape');
  s = await state('#mix-search');
  check('the next Escape closes the sheet', s.mix === false, JSON.stringify(s));
  await reset();

  // ---- F. Talk it through: the Ask ORCH box beside the card on Now ----
  console.log('F: Talk it through (Ask ORCH about this card)');
  const onNow = await ev(`({ now: !!(MEFIRST && !nowWatch && !hudIsOpen() && deckTop) })`);
  check('the board is on Now with a card in front (the seeded board has a pile)', onNow.now === true, JSON.stringify(onNow));
  if (onNow.now) {
    await ev(`(() => { talkOpen(deckTop); return true; })()`);
    // talkOpen focuses its field from a 60 ms timer, and a headless page can run that timer late: wait for it to fire, or it would re-focus the field right after the Escape blurs it
    check('the app focuses the conversation field itself (its own 60 ms timer fired)', await until(`document.activeElement?.closest?.('#talk') ? 1 : 0`, 0));
    await sleep(150);
    const talkOn = () => ev(`({ open: !!talkCard, body: document.activeElement === document.body, inTalk: !!document.activeElement?.closest?.('#talk'), value: $('talk')?.querySelector('input')?.value ?? null })`);
    check('the conversation opens', (await talkOn()).open === true, JSON.stringify(await talkOn()));
    check('its field takes focus (talkOpen focuses it on a 60 ms timer that a board poll can beat, so this focuses it itself)', await focus('#talk input') && (await talkOn()).inTalk === true, JSON.stringify(await talkOn()));
    await type('what does this card want');
    await focus('#talk input');   // a board poll can rebuild the box under a typist: keep the field focused for the press
    await ev(`(() => { window.__escSeen = []; window.__focusLog = []; return true; })()`);
    await press('Escape');
    if (TRACE) await trace('after the first Escape in the talk box');
    let t = await talkOn();
    if (t.body !== true && !TRACE) await trace('FLAKE: the first Escape left the field focused', true);
    check('the first Escape leaves the Ask ORCH field, keeps what was typed, and the conversation stays open', t.body === true && t.open === true && t.value === 'what does this card want', JSON.stringify(t));
    await press('Escape');
    t = await talkOn();
    check('the second Escape closes the conversation, as before', t.open === false, JSON.stringify(t));
  }

  // ---- E. an IME composing, and a control that is not typing ----
  console.log('E: an IME, and a select');
  await ev(`(() => { openChat(); return true; })()`); await sleep(300);
  await focus('#chat-input'); await type('ni');
  const comp = await ev(`(() => { const el = document.activeElement; const e = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: true, keyCode: 229 }); el.dispatchEvent(e); return { prevented: e.defaultPrevented, still: document.activeElement === el, chat: $('chat').classList.contains('open'), value: el.value }; })()`);
  check('an Escape while composing is left alone: the field keeps focus, the drawer stays open, nothing is prevented', comp.still === true && comp.chat === true && comp.prevented === false && comp.value === 'ni', JSON.stringify(comp));
  await ev(`(() => { $('chat-input').value = ''; return true; })()`); await reset();
  const sel = await ev(`(() => { const el = document.createElement('select'); el.id = 'esc-probe'; el.innerHTML = '<option>a</option>'; document.body.appendChild(el); el.focus(); const ok = escLeavesField(el); el.remove(); return ok; })()`);
  check('a select is not a text field: Escape is left to it', sel === false, String(sel));
  const kinds = await ev(`(() => { const t = ty => { const el = document.createElement('input'); el.type = ty; return escLeavesField(el); }; return { text: t('text'), search: t('search'), time: t('time'), number: t('number'), checkbox: t('checkbox'), range: t('range'), button: t('button') }; })()`);
  check('text, search, time and number fields leave on Escape; a checkbox, a slider and a button are controls', kinds.text && kinds.search && kinds.time && kinds.number && !kinds.checkbox && !kinds.range && !kinds.button, JSON.stringify(kinds));

  check('the page raised no console errors and no exceptions', errors.length === 0, errors.join(' | '));
  ws.close();
}

try { await main(); } catch (e) { fail('the check ran: ' + e.message); } finally { await stopAll(); }
done('ESC CHECK');
