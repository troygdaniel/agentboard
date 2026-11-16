// Watch's page arrows and dots on a short desktop window (sweep2-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/watch_pager_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// The Watch draws three rows of 150 px tiles and, when there is more than one page, the arrows and dots 26 px under the last row. The ORCH line floats over the bottom 67 px of the
// window, so on a window under about 810 px tall (a laptop) the pager sat behind it: the second page could not be seen, and a click on the dots landed on the line. The rows now shrink
// (150 px down to 120, from the window's height, in CSS) so the three by three stays; only when even 120 px rows will not fit does a page take two rows, or one. This measures the tiles,
// the pager and the line at laptop and desktop sizes, that no tile's text spills out of a shortened tile, and a resize with no reload. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done } = checker();

// the current page's tiles, the pager's controls, and the ORCH line, in one look
const LOOK = `(() => {
  const f = document.getElementById('orch-line'), pg = document.querySelector('.w-page.cur'); if (!f || !pg) return { err: 'no line or no page' };
  const fr = f.getBoundingClientRect(), tiles = [...pg.children].filter(t => t.getBoundingClientRect().height > 0);
  const under = tiles.filter(t => { const r = t.getBoundingClientRect(); return r.bottom > fr.top + 1 && Math.min(r.right, fr.right) - Math.max(r.left, fr.left) > 0; }).length;
  const ctl = [...document.querySelectorAll('.w-dots button')], hit = ctl.filter(b => { const r = b.getBoundingClientRect(), e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return e === b || b.contains(e); }).length;
  const dots = document.querySelector('.w-dots'), dr = dots ? dots.getBoundingClientRect() : null;
  const spill = []; for (const t of tiles) { const tr = t.getBoundingClientRect(); for (const e of t.querySelectorAll('*')) { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); if (!r.width || !r.height || cs.visibility === 'hidden' || +cs.opacity === 0 || e.closest('svg') || e.matches('.zz')) continue; if (r.bottom > tr.bottom + 1 || r.top < tr.top - 1) { spill.push((e.className && String(e.className).trim().split(/\\s+/)[0] || e.tagName.toLowerCase()) + ' ' + Math.round(r.top - tr.top) + '..' + Math.round(r.bottom - tr.top) + ' of ' + Math.round(tr.height)); break; } } }
  return { tiles: tiles.length, rowH: tiles.length ? Math.round(tiles[0].getBoundingClientRect().height) : 0, under, spill: spill.slice(0, 3), controls: ctl.length, reachable: hit, pagerTop: dr ? Math.round(dr.top) : null, pagerBottom: dr ? Math.round(dr.bottom) : null, lineTop: Math.round(fr.top), inView: dr ? dr.bottom <= innerHeight : null };
})()`;

async function main() {
  const board = await startBoard('watchpager');
  const page = await openPage(board.url + 'watch', { width: 1440, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.getElementById('cfg-btn')` });
  const { send, ev, waitFor } = page;
  const size = (w, h) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  const open = async (w, h) => {
    await size(w, h); await send('Page.navigate', { url: board.url + 'watch' });
    await waitFor(`document.readyState === 'complete' && typeof applyTheme === 'function' && !!document.querySelector('.w-page.cur')`, 20000); await sleep(1200);
    return ev(LOOK);
  };
  const pagerClear = m => m.controls > 0 && m.reachable === m.controls && m.under === 0 && m.inView === true;

  console.log('A: short desktop windows keep three by three, with shorter tiles (the pager must clear the ORCH line)');
  // [width, height, tiles on the first page, tile height]: 200 px to the grid (252 when the header wraps), 127 px under it for the pager and the line, rows of 150 px down to 120
  for (const [w, h, tiles, rowH] of [[1440, 780, 9, 140], [1280, 720, 9, 120], [1100, 800, 6, 130], [1440, 860, 9, 150]]) {
    const m = await open(w, h);
    check(`${w}x${h}: the Watch has more than one page (the seed has 14 tiles)`, m.controls >= 3, JSON.stringify(m));
    check(`${w}x${h}: ${tiles} tiles on the first page, ${rowH} px tall`, m.tiles === tiles && Math.abs(m.rowH - rowH) <= 2, `${m.tiles} tiles, ${m.rowH} px`);
    check(`${w}x${h}: the pager clears the line (no tile under it, every arrow and dot takes a click, all in the window)`, pagerClear(m), JSON.stringify(m));
    check(`${w}x${h}: no tile's text spills out of its tile`, m.spill.length === 0, m.spill.join('; '));
  }

  console.log('B: when even 120 px rows will not fit, two rows, then one');
  for (const [w, h, tiles] of [[1440, 700, 6], [1440, 600, 6], [1440, 540, 3]]) {
    const m = await open(w, h);
    check(`${w}x${h}: ${tiles} tiles on the first page`, m.tiles === tiles, `${m.tiles} tiles, ${m.rowH} px`);
    check(`${w}x${h}: the pager clears the line`, pagerClear(m), JSON.stringify(m));
    check(`${w}x${h}: no tile's text spills out of its tile`, m.spill.length === 0, m.spill.join('; '));
  }

  console.log('C: tall windows are as before');
  for (const [w, h, tiles] of [[1600, 1000, 9], [1440, 900, 9], [1100, 900, 6]]) {
    const m = await open(w, h);
    check(`${w}x${h}: ${tiles} tiles of 150 px on the first page`, m.tiles === tiles && m.rowH === 150, `${m.tiles} tiles, ${m.rowH} px`);
    check(`${w}x${h}: the pager clears the line`, pagerClear(m), JSON.stringify(m));
  }

  console.log('D: a resize re-fits the page, with no reload');
  let m = await open(1440, 900);
  check('start tall: 9 tiles of 150 px', m.tiles === 9 && m.rowH === 150, `${m.tiles}, ${m.rowH}`);
  await size(1440, 780); await sleep(900); m = await ev(LOOK);
  check('resized to 780 tall: still 9 tiles, now 140 px, and the pager clears the line', m.tiles === 9 && Math.abs(m.rowH - 140) <= 2 && pagerClear(m), JSON.stringify(m));
  await size(1440, 700); await sleep(900); m = await ev(LOOK);
  check('resized to 700 tall: two rows (6 tiles) and the pager clears the line', m.tiles === 6 && pagerClear(m), JSON.stringify(m));
  await size(1440, 900); await sleep(900); m = await ev(LOOK);
  check('resized back to 900 tall: 9 tiles of 150 px', m.tiles === 9 && m.rowH === 150, `${m.tiles}, ${m.rowH}`);

  page.close();
  await stopAll();
  done('watch_pager_check');
}
main().catch(e => { console.error(e); stopAll().finally(() => process.exit(1)); });
