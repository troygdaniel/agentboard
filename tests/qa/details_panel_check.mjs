// The details panel beside a card on Watch is readable (card details-panel-readable): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/details_panel_check.mjs          (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// It seeds a made-up board with one card whose task is a long single paragraph (the shape that read as a blob) and one with a short task, opens each on the
// Watch tab, and asserts: the long paragraph is one sentence per line, the task is cut with a fade and a working "Show all" (it was missing on Watch), a short
// task shows whole with no button, a paragraph with markup in it is left alone, the section labels have their rule, and light, dark and 390 px wide do not overflow.
// DETAILS_CHECK_SHOTS=<dir> also saves a screenshot of each. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const SHOTS = process.env.DETAILS_CHECK_SHOTS;

const LONG = 'The owner said "yes to all" to the six decisions in docs/design.md (2026-11-14): fold them into the Watch tab, use the eight state words as in the mock-up, never count a sleeping board as silent, and wait on the generic note for queues. '
  + 'Build in slices and STOP after slice 1 so the owner can look, since-you-last-looked and the Ask box come last. '
  + 'BUILD SLICE 1 ONLY: the one look and the agent rows with the eight states on the Watch tab, and the board-asleep rule (the states, the sign-off row and the blocked-by link already exist). '
  + 'Follow the mock-up wording. Light, dark and narrow; render-check; tests; suite green; public repo rules; own worktree off main; no install or restart.\n\n'
  + '## Keep it simple\n\nOne look, eight words, nothing else on the page.\n\n'
  + 'A short note with `code` inside it, e.g. the setting silent_minutes. It has markup, so it stays one paragraph even though it is long enough to be cut into lines otherwise, and nothing about it should change.';
const SHORT = 'Retry a failed upload three times, then say so.';

async function main() {
  const board = await startBoard('details');
  const mk = (name, title) => { const r = board.cli(['start', title, '--name', name], { AGENTBOARD_NAME: name }); const id = (r.out || '').trim().split('\n')[0].trim(); board.cli(['add', 'build it', '--parent', id], { AGENTBOARD_NAME: name }); board.cli(['add', 'check it', '--parent', id], { AGENTBOARD_NAME: name }); return id; };
  const ids = { ada: mk('Ada', 'Status rows on Watch, slice 1'), grace: mk('Grace', 'Retry failed uploads') };
  const f = join(board.dir, 'tasks.json'), j = JSON.parse(readFileSync(f, 'utf8')), ts = Array.isArray(j) ? j : j.tasks;
  ts.find(x => x.id === ids.ada).description = LONG; ts.find(x => x.id === ids.grace).description = SHORT; writeFileSync(f, JSON.stringify(j, null, 1));

  const page = await openPage(board.url + 'watch', { width: 1440, height: 900, ready: `document.querySelectorAll('.w-tile').length > 1`, init: `try { const d = new Date().toDateString(); localStorage.setItem('ab-orch-asked', d); localStorage.setItem('ab-greeted', d); } catch (e) {}` });   // the page greets you once a day, and (ORCH not running on a throwaway board) offers to start it once a day: neither in this check
  const { send, ev, waitFor, errors } = page;
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] }); await sleep(300);
  const shot = async name => { if (!SHOTS) return; mkdirSync(SHOTS, { recursive: true }); const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(SHOTS, name), Buffer.from(r.data, 'base64')); };
  const open = async who => { await ev(`(() => { if (document.querySelector('.w-focus')) document.querySelector('[data-wclose]').click(); })()`); await sleep(250); await ev(`document.querySelector('.w-tile[data-wid="${ids[who]}"]').click()`); await waitFor(`!!document.querySelector('.w-focus .deck-task')`); await sleep(900); };

  console.log('A: a long task reads one sentence to a line');
  await open('ada');
  const a = await ev(`(() => { const sec = document.querySelector('.w-focus .deck-task'), ps = [...sec.querySelectorAll('.rich-body p')], sp = ps[0], s = sp.querySelectorAll('.s');
    const tops = [...s].map(x => Math.round(x.getBoundingClientRect().top));
    return { n: s.length, split: sp.classList.contains('split'), block: s.length && getComputedStyle(s[0]).display === 'block', distinct: new Set(tops).size, first: s[0] && s[0].textContent, abbr: [...s].some(x => /^g\\./.test(x.textContent)), ends: [...s].every(x => /[.)]$/.test(x.textContent)),
      markup: ps.filter(p => p.querySelector('code')).every(p => !p.classList.contains('split')), text: sp.textContent.length }; })()`);
  check('the long plain paragraph is split into its five sentences (one ends in "last.", one in "exist).")', a.split && a.n === 5 && a.ends, JSON.stringify(a));
  check('each sentence starts a new line (every one has its own top)', a.distinct === a.n, JSON.stringify(a));
  check('the sentences are block lines, the first keeps its quote and its date whole', a.block && /^The owner said "yes to all"[^]*\(2026-11-14\): fold/.test(a.first), a.first);
  check('"e.g." does not end a sentence', !a.abbr);
  check('a paragraph with markup in it is left as it was', a.markup);
  check('no words were lost: the sentences add up to the paragraph', a.text > 500 && (await ev(`document.querySelector('.w-focus .deck-task .rich-body p.split').textContent.replace(/\\s+/g, '') === ${JSON.stringify(LONG.split('\n\n')[0].replace(/\s+/g, ''))}`)));

  console.log('B: the task is cut, and Show all works (on Watch too)');
  const b = await ev(`(() => { const sec = document.querySelector('.w-focus .deck-task'), body = sec.querySelector('.rich-body'), more = sec.querySelector('[data-deck-task]'); return { long: sec.classList.contains('long'), hidden: more.hidden, cut: body.scrollHeight > body.clientHeight, h: body.clientHeight, mask: getComputedStyle(body).maskImage || getComputedStyle(body).webkitMaskImage }; })()`);
  check('a long task is cut with the fade and the button shows', b.long && !b.hidden && b.cut && /gradient/.test(b.mask || ''), JSON.stringify(b));
  check('the cut is a few lines, not a screenful', b.h <= 200, String(b.h));
  await shot('watch-cut-light.png');
  await ev(`document.querySelector('.w-focus [data-deck-task]').click()`); await sleep(150);
  const c = await ev(`(() => { const body = document.querySelector('.w-focus .deck-task .rich-body'); return { all: body.scrollHeight <= body.clientHeight + 1, label: document.querySelector('.w-focus [data-deck-task]').textContent, mask: getComputedStyle(body).maskImage }; })()`);
  check('Show all opens the whole task and the button says Show less', c.all && c.label === 'Show less' && !/gradient/.test(c.mask || ''), JSON.stringify(c));
  await shot('watch-all-light.png');
  await ev(`document.querySelector('.w-focus [data-deck-task]').click()`); await sleep(100);
  check('Show less cuts it again', await ev(`document.querySelector('.w-focus .deck-task').classList.contains('long') && !document.querySelector('.w-focus .deck-task').classList.contains('all')`));

  console.log('C: closing and opening it again (drawn from what was kept) keeps the button');
  await open('ada');
  check('the second time the button is there too', await ev(`(() => { const s = document.querySelector('.w-focus .deck-task'); return s.classList.contains('long') && !s.querySelector('[data-deck-task]').hidden; })()`));

  console.log('D: a short task shows whole, with no button');
  await open('grace');
  const d = await ev(`(() => { const s = document.querySelector('.w-focus .deck-task'); return { hidden: s.querySelector('[data-deck-task]').hidden, long: s.classList.contains('long'), split: !!s.querySelector('p.split'), text: s.querySelector('.rich-body').textContent.trim() }; })()`);
  check('no button, no fade, no splitting', d.hidden && !d.long && !d.split && d.text === SHORT, JSON.stringify(d));

  console.log('E: the section labels carry their rule');
  check('"The task" has a line after it', await ev(`getComputedStyle(document.querySelector('.w-focus .deck-task h3'), '::after').height === '1px'`));

  console.log('F: light, dark and 390 px wide');
  check('light: the page is light', await ev(`matchMedia('(prefers-color-scheme: light)').matches`));
  await open('ada');
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] }); await sleep(300);
  const over = () => ev(`(() => { const m = document.querySelector('.w-focus .w-more'); const r = m.getBoundingClientRect(); return { page: document.documentElement.scrollWidth - innerWidth, panel: m.scrollWidth - m.clientWidth, right: Math.round(r.right), vw: innerWidth, fg: getComputedStyle(m.querySelector('.rich-body')).color, bg: getComputedStyle(document.body).backgroundColor }; })()`);
  let o = await over();
  check('dark: the text is not the page colour, and nothing scrolls sideways', o.fg !== o.bg && o.page <= 0 && o.panel <= 0, JSON.stringify(o));
  await shot('watch-cut-dark.png');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 900, deviceScaleFactor: 1, mobile: true }); await sleep(500);
  await open('ada');
  o = await over();
  check('390 px wide: the panel is inside the screen and nothing scrolls sideways', o.right <= o.vw && o.page <= 0 && o.panel <= 0, JSON.stringify(o));
  await shot('watch-cut-narrow.png');
  check('no Start ORCH offer and no greeting over the panel', await ev(`!document.querySelector('.orch-start') && !document.querySelector('.greet, #greet')`));
  check('the page logged no errors', errors.length === 0, errors.join(' | '));
}
main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('DETAILS PANEL'); });
