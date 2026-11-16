// Phone tap targets (sweep-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/tap_targets_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// At 390 px the controls a finger uses on the Now card and in Settings were 16 to 23 px tall: the "Show only ..." name chips, the card's own links (Talk it through, Simpler,
// Later, Why?), the quick-reply chips (Go ahead), the subtask toggle, the Settings switches and the Settings search. WCAG 2.5.8 asks for 24 px; a card behind the front one is
// drawn at 75%, so each of these asks for 32 and is 24 even there. This measures every one of them in the layout (offsetWidth and offsetHeight, which a card's scale does not
// change) and, for the ones on the stacked cards, in what is drawn. Prints one ok/FAIL line per control; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const CONTROLS = [
  ['the "Show only ..." name chip', '.who'],
  ['the card link (Talk it through, Simpler, Later, Why?)', '.you-h'],
  ['the quick-reply chip (Go ahead)', '.qr-ch'],
  ['the subtask toggle', '.subs-toggle'],
];

async function main() {
  const board = await startBoard('taps');
  const page = await openPage(board.url, { width: 390, height: 844, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.getElementById('cfg-btn')` });
  const { send, ev, waitFor } = page;
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await sleep(1200);
  const measure = sel => ev(`(() => { const els = [...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => { const cs = getComputedStyle(e); return cs.display !== 'none' && cs.visibility !== 'hidden' && e.offsetWidth; }); const small = els.filter(e => Math.min(e.offsetWidth, e.offsetHeight) < 24 || e.offsetHeight < 32).map(e => e.offsetWidth + 'x' + e.offsetHeight + ' "' + (e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 18) + '"'); const drawn = els.filter(e => { const r = e.getBoundingClientRect(); return r.height < 23.5 && r.height > 0; }).map(e => Math.round(e.getBoundingClientRect().height) + ' drawn'); return { n: els.length, small: [...new Set(small)].slice(0, 4), drawn: [...new Set(drawn)].slice(0, 4) }; })()`);

  console.log('A: the Now card, at 390 px');
  for (const [name, sel] of CONTROLS) {
    const m = await measure(sel);
    check(`${name}: at least 32 px tall in the layout (and so 24 when drawn at 75%)`, m.n > 0 && m.small.length === 0, `${m.n} found; too small: ${m.small.join(', ')}`);
  }
  console.log('B: Settings');
  await ev(`(toggleMix(true, 'general'), 1)`); await sleep(700);
  let m = await measure('#mix .mix-row > input[type="checkbox"]');
  check('the Settings switches are 24 px', m.n > 0 && (await ev(`[...document.querySelectorAll('#mix .mix-row > input[type="checkbox"]')].filter(e => e.offsetWidth).every(e => e.offsetWidth >= 24 && e.offsetHeight >= 24)`)), `${m.n} found`);
  check('the Settings search is 32 px tall', await ev(`document.getElementById('mix-search').offsetHeight >= 32`), await ev(`document.getElementById('mix-search').offsetHeight`));
  console.log('C: nothing wider than the screen came of it');
  await ev(`(toggleMix(false), 1)`); await sleep(400);
  check('no sideways scroll on the Now card', await ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`));
  await ev(`(toggleMix(true, 'general'), 1)`); await sleep(500);
  check('no sideways scroll in Settings', await ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`));
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('TAP TARGETS'); });
