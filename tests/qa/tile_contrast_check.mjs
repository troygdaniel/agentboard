// Text contrast on the Watch tiles (sweep2-ux): measured from the rendered pixels in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/tile_contrast_check.mjs          (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// A tile's agent name, its state word (Silent, Working, ...), its "You · Answer" line and the digit in its ring were drawn in the agent's or the state's own colour straight onto a tile
// tinted with that colour, which left the pink and purple agents' names at 3.5 and 4.3 to 1, "Silent" at 3.9, "You · Answer" at 4.4 and the pink digit at 2.8 in the light theme (and the
// pink digit at 2.6 in the dark one). Gradients and glass cannot be read from the CSS, so this takes a screenshot, finds each text's background as the commonest colour behind it (the seed
// board has six agents, which is all six palette slots) and works out the WCAG ratio. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done } = checker();
const WHAT = [   // [what, selector, padding around the text for the background sample, ratio asked]
  ['the agent name', '.w-page.cur .w-tile .w-tx > b', 3, 4.5],
  ['the state word', '.w-page.cur .w-tile .w-state', 3, 4.5],
  ['the "You · Answer" line', '.w-page.cur .w-tile .w-verb', 3, 4.5],
  ['the digit in the ring (24 px bold: 3 is asked)', '.w-page.cur .w-tile .orb i', 9, 3],
];
const LIST = sel => `(() => [...document.querySelectorAll(${JSON.stringify(sel)})].filter(el => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el); return r.width > 3 && r.height > 3 && cs.visibility !== 'hidden' && +cs.opacity > 0.9 && !el.closest('.w-idling'); }).map(el => {
  const r = document.createRange(); r.selectNodeContents(el); const b = r.getBoundingClientRect(), cs = getComputedStyle(el).color, m1 = /^rgba?\\(([^)]+)\\)/.exec(cs), m2 = /^color\\(srgb ([^)]+)\\)/.exec(cs);   // a colour made with color-mix() is reported as color(srgb 0.7 0.1 0.4)
  const p = m1 ? m1[1].split(/[ ,\\/]+/).filter(Boolean).map(Number) : (q => [q[0] * 255, q[1] * 255, q[2] * 255, q.length > 3 ? q[3] : 1])(m2[1].split(/[ \\/]+/).filter(Boolean).map(Number));
  return { d: (el.closest('.w-tile').querySelector('.w-tx > b') || {}).textContent + ' / ' + (el.textContent || '').trim().slice(0, 14), x: b.left, y: b.top, w: b.width, h: b.height, rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }; }))()`;
const SAMPLE = `(async (b64, items, pad) => { const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode(); const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0);
  const lum = ([r, gg, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(gg) + 0.0722 * f(b); };
  return items.map(it => { const x = Math.max(0, Math.floor(it.x - pad)), y = Math.max(0, Math.floor(it.y - pad)), w = Math.max(1, Math.min(Math.ceil(it.w + 2 * pad), c.width - x)), h = Math.max(1, Math.min(Math.ceil(it.h + 2 * pad), c.height - y));
    const d = g.getImageData(x, y, w, h).data, buckets = new Map();
    for (let i = 0; i < d.length; i += 4) { const k = (d[i] >> 4) + ',' + (d[i + 1] >> 4) + ',' + (d[i + 2] >> 4); const e = buckets.get(k) || [0, 0, 0, 0]; e[0]++; e[1] += d[i]; e[2] += d[i + 1]; e[3] += d[i + 2]; buckets.set(k, e); }
    let best = null; for (const e of buckets.values()) if (!best || e[0] > best[0]) best = e; const bg = [best[1] / best[0], best[2] / best[0], best[3] / best[0]];
    const fg = it.rgb.map((v, i) => v * it.a + bg[i] * (1 - it.a)); const l1 = lum(fg), l2 = lum(bg);
    return { d: it.d, ratio: +((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2) }; }); })`;

async function main() {
  const board = await startBoard('tilecontrast');
  const page = await openPage(board.url + 'watch', { width: 1440, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.querySelector('.w-page.cur .w-tile')` });
  const { send, ev, waitFor } = page;
  for (const theme of ['light', 'dark']) {
    console.log(`A: the ${theme} theme`);
    await ev(`(setTheme(${JSON.stringify(theme)}), 1)`); await sleep(1500);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    for (const [what, sel, pad, want] of WHAT) {
      const items = await ev(LIST(sel));
      const res = await send('Runtime.evaluate', { expression: `(${SAMPLE})(${JSON.stringify(shot.data)}, ${JSON.stringify(items)}, ${pad})`, awaitPromise: true, returnByValue: true });
      const rows = res.result.value || [];
      const worst = rows.reduce((a, r) => (!a || r.ratio < a.ratio ? r : a), null);
      check(`${theme}: ${what} is at least ${want} to 1 on every tile (${rows.length} measured)`, rows.length > 0 && worst.ratio >= want, worst ? `${worst.ratio} for ${worst.d}` : 'none found');
    }
  }
  page.close();
  await stopAll();
  done('tile_contrast_check');
}
main().catch(e => { console.error(e); stopAll().finally(() => process.exit(1)); });
