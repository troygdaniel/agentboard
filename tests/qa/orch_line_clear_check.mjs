// The ORCH line over the Map's columns (sweep2-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/orch_line_clear_check.mjs        (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// The line ("Tell ORCH what you need") floats 18 px above the window's bottom edge and about 49 px tall; the Todo, Doing and Done columns run to about 22 px above it. So the line
// sat over the last 45 px of every column: scrolled to the end, the last Doing card was still 26 px under the glass, and the Done column's "Show N more" button (below its list,
// not inside the scroll) was half under it, and a click on that half landed on the line. This scrolls each list to its end and measures, on a desktop window tall and short.
// Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done } = checker();
const SIZES = [[1600, 1000], [1100, 800], [1280, 720]];

async function main() {
  const board = await startBoard('orchline');
  const page = await openPage(board.url, { width: 1600, height: 1000, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.getElementById('cfg-btn')` });
  const { send, ev, waitFor } = page;
  for (const [w, h] of SIZES) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: board.url });
    await waitFor(`document.readyState === 'complete' && typeof applyTheme === 'function' && !!document.getElementById('tab-board')`, 20000);
    await sleep(900);
    await ev(`(document.getElementById('tab-board').click(), 1)`);
    await sleep(700);
    const m = await ev(`(() => {
      const f = document.getElementById('orch-line'); if (!f) return { err: 'no line' };
      const fr = f.getBoundingClientRect(), lists = [], mores = [];
      const hits = (el, fr) => Math.min(el.right, fr.right) - Math.max(el.left, fr.left) > 0;
      for (const c of document.querySelectorAll('.board .col .cards')) {
        if (c.scrollHeight <= c.clientHeight + 2) continue;
        c.scrollTop = c.scrollHeight;
        const kids = [...c.children].filter(k => k.getBoundingClientRect().height > 0), last = kids[kids.length - 1], lr = last.getBoundingClientRect();
        lists.push({ col: c.parentElement.className, under: hits(lr, fr) ? Math.max(0, Math.round(lr.bottom - fr.top)) : 0 });
      }
      for (const b of document.querySelectorAll('.board .col .more')) {
        const r = b.getBoundingClientRect(); if (!r.width) continue;
        const probe = [r.left + 4, r.left + r.width / 2, r.right - 4].map(x => { const e = document.elementFromPoint(x, r.top + r.height / 2); return !!e && (e === b || b.contains(e)); });
        mores.push({ text: b.textContent.trim(), top: Math.round(r.top), bottom: Math.round(r.bottom), line: [Math.round(fr.top), Math.round(fr.bottom)], reachable: probe.every(Boolean), covered: hits(r, fr) && r.bottom > fr.top && r.top < fr.bottom });
      }
      return { lists, mores, line: [Math.round(fr.top), Math.round(fr.bottom)] };
    })()`);
    console.log(`A: Map at ${w}x${h} (the line covers ${m.line ? m.line.join('-') : '?'})`);
    check('the page has the line', !m.err, m.err);
    check('at least one column list scrolls (the seed has more cards than fit)', m.lists && m.lists.length > 0, JSON.stringify(m));
    for (const l of m.lists || []) check(`${l.col}: scrolled to the end, its last card is clear of the line`, l.under === 0, `${l.under} px of the last card under the line`);
    check('a "Show N more" button is on the Done column (the seed has eight done cards, five show)', (m.mores || []).length > 0, JSON.stringify(m.mores));
    for (const b of m.mores || []) {
      check(`"${b.text}" is clear of the line (button ${b.top}-${b.bottom}, line ${b.line.join('-')})`, !b.covered);
      check(`"${b.text}" takes a click on its left, middle and right`, b.reachable);
    }
  }
  page.close();
  await stopAll();
  done('orch_line_clear_check');
}
main().catch(e => { console.error(e); stopAll().finally(() => process.exit(1)); });
