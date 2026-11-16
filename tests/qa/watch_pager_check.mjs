// Watch's page arrows and dots on a short desktop window (sweep2-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/watch_pager_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// The Watch draws three rows of tiles and, when there is more than one page, the arrows and dots 26 px under the last row. The ORCH line floats over the bottom 67 px of the window,
// so on a window under about 810 px tall (a laptop) the pager sat behind it: the second page could not be seen, and a click on the dots landed on the line. The page now takes as many
// rows as fit above the line (one to three), and re-splits when the window is resized. This measures it at laptop and desktop sizes, and after a resize with no reload.
// Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done } = checker();

// the current page's tiles, the pager's controls, and the ORCH line, in one look
const LOOK = `(() => {
  const f = document.getElementById('orch-line'), pg = document.querySelector('.w-page.cur'); if (!f || !pg) return { err: 'no line or no page' };
  const fr = f.getBoundingClientRect(), tiles = [...pg.children].filter(t => t.getBoundingClientRect().height > 0);
  const under = tiles.filter(t => { const r = t.getBoundingClientRect(); return r.bottom > fr.top + 1 && Math.min(r.right, fr.right) - Math.max(r.left, fr.left) > 0; }).length;
  const ctl = [...document.querySelectorAll('.w-dots button')], hit = ctl.filter(b => { const r = b.getBoundingClientRect(), e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return e === b || b.contains(e); }).length;
  const dots = document.querySelector('.w-dots'), dr = dots ? dots.getBoundingClientRect() : null;
  return { tiles: tiles.length, under, controls: ctl.length, reachable: hit, pagerTop: dr ? Math.round(dr.top) : null, pagerBottom: dr ? Math.round(dr.bottom) : null, lineTop: Math.round(fr.top), inView: dr ? dr.bottom <= innerHeight : null };
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

  console.log('A: short desktop windows (the pager must clear the ORCH line)');
  for (const [w, h] of [[1440, 780], [1100, 800], [1280, 720], [1440, 700]]) {
    const m = await open(w, h);
    check(`${w}x${h}: the Watch has more than one page (the seed has 14 tiles)`, m.controls >= 3, JSON.stringify(m));
    check(`${w}x${h}: no tile on the page is under the line`, m.under === 0, `${m.under} tile(s) under the line ${m.lineTop}`);
    check(`${w}x${h}: every arrow and dot takes a click (not the line)`, m.controls > 0 && m.reachable === m.controls, `${m.reachable} of ${m.controls}; pager ${m.pagerTop}-${m.pagerBottom}, line from ${m.lineTop}`);
    check(`${w}x${h}: the pager is inside the window`, m.inView === true, `pager bottom ${m.pagerBottom}`);
  }

  console.log('B: tall windows keep three rows');
  for (const [w, h, want] of [[1600, 1000, 9], [1440, 900, 9], [1100, 900, 6]]) {
    const m = await open(w, h);
    check(`${w}x${h}: ${want} tiles on the first page`, m.tiles === want, `${m.tiles} tiles`);
    check(`${w}x${h}: the pager is clear of the line`, m.controls > 0 && m.reachable === m.controls && m.under === 0, JSON.stringify(m));
  }

  console.log('C: a resize re-splits the pages, with no reload');
  let m = await open(1440, 900);
  check('start tall: 9 tiles', m.tiles === 9, `${m.tiles}`);
  await size(1440, 780); await sleep(900); m = await ev(LOOK);
  check('resized to 780 tall: the pager is clear of the line', m.controls > 0 && m.reachable === m.controls && m.under === 0, JSON.stringify(m));
  check('resized to 780 tall: fewer than 9 tiles', m.tiles < 9, `${m.tiles}`);
  await size(1440, 900); await sleep(900); m = await ev(LOOK);
  check('resized back to 900 tall: 9 tiles again', m.tiles === 9, `${m.tiles}`);

  page.close();
  await stopAll();
  done('watch_pager_check');
}
main().catch(e => { console.error(e); stopAll().finally(() => process.exit(1)); });
