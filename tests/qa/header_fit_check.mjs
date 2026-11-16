// The header fits the window (sweep-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/header_fit_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// The header never wraps above the phone width, so everything in it has to fit on one line, or the right-hand controls (the theme, Help and Settings buttons) fall off the
// window and the page scrolls sideways. First a board with no chips, then the busiest header there is (an agent configuration applied, so its chip shows, and night mode on,
// so the Night chip shows): the page is walked from 1600 px down to 760, and at each width there is no sideways scroll and every visible header control is inside the window.
// Prints one ok/FAIL line per width; exit code 1 on a FAIL.
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const WIDTHS = [1600, 1440, 1366, 1280, 1200, 1100, 1024, 960, 901, 850, 760];

async function main() {
  const board = await startBoard('hdrfit');
  appendFileSync(join(board.dir, 'config.toml'), '\n[agents]\nconfigurations = true\n');
  const page = await openPage(board.url, { width: 1440, height: 800, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.getElementById('cfg-btn')` });
  const { send, ev, waitFor } = page;
  const measure = () => ev(`(() => { const de = document.documentElement; const bad = []; for (const e of document.querySelectorAll('header button, header .ab-conn, header a')) { const cs = getComputedStyle(e); if (cs.display === 'none' || e.hidden) continue; const r = e.getBoundingClientRect(); if (r.width && (r.right > innerWidth + 0.5 || r.left < -0.5)) bad.push((e.id || e.className) + ' right=' + Math.round(r.right)); } return { over: de.scrollWidth - de.clientWidth, outside: bad, chips: [...document.querySelectorAll('#cfg-chip, #night-chip')].filter(e => !e.hidden).map(e => e.id).join('+') }; })()`);
  const sweep = async label => {
    for (const w of WIDTHS) {
      await send('Emulation.setDeviceMetricsOverride', { width: w, height: 800, deviceScaleFactor: 1, mobile: false });
      await sleep(300);
      const m = await measure();
      check(`${label}: ${w} px: no sideways scroll and every header control inside the window`, m.over <= 0 && m.outside.length === 0, `scrolls by ${m.over}px; outside: ${m.outside.join(', ')}; chips: ${m.chips}`);
    }
  };
  await sweep('no chips');
  board.cli(['configuration', 'apply', 'build']);
  const on = board.cli(['night', 'on', '--until', '23:59'], { AGENTBOARD_NAME: 'ORCH' });
  check('night mode on, for the chip', on.status === 0, on.out);
  await ev(`(nightLoad(), cfgLoad(), 1)`);
  check('both chips are showing', await waitFor(`!document.getElementById('night-chip').hidden && !document.getElementById('cfg-chip').hidden`, 10000));
  await sweep('config + night chips');
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('HEADER FIT'); });
