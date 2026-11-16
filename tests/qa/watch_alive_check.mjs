// Watch feels alive (card watch-alive-pulse): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/watch_alive_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// It seeds a made-up board, adds three agents whose last update is 8 s, 4 min and 12 min old, and asserts on the Watch tab: each tile's state (fresh, ageing,
// silent), the "heard" line, that the percent never moves, that a tile ages in place without a redraw, the connection dot (Live, then Slow, then Reconnecting
// when the server is stopped mid-session, and Live again when it is back), the dimmed and frozen tiles while it is red, reduced motion, dark and 390 px wide.
// WATCH_CHECK_SHOTS=<dir> also saves a screenshot of each. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const SHOTS = process.env.WATCH_CHECK_SHOTS;

async function main() {
  const board = await startBoard('watch');
  const mk = (name, title) => { const r = board.cli(['start', title, '--name', name], { AGENTBOARD_NAME: name }); const id = (r.out || '').trim().split('\n')[0].trim(); board.cli(['add', 'build it', '--parent', id], { AGENTBOARD_NAME: name }); board.cli(['add', 'check it', '--parent', id], { AGENTBOARD_NAME: name }); return id; };
  const ids = { ada: mk('Ada', 'Search box remembers the last query'), grace: mk('Grace', 'Export the weekly report as CSV'), linus: mk('Linus', 'Retry failed uploads three times') };
  const age = { ada: 8, grace: 4 * 60, linus: 12 * 60 };
  const stamp = secs => { const d = new Date(Date.now() - secs * 1000), z = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`; };
  const setAge = (who, secs) => { const f = join(board.dir, 'tasks.json'), j = JSON.parse(readFileSync(f, 'utf8')), ts = Array.isArray(j) ? j : j.tasks; const t = ts.find(x => x.id === ids[who]); t.updated = stamp(secs); t.progress = 40; writeFileSync(f, JSON.stringify(j, null, 1)); };
  for (const who of Object.keys(ids)) setAge(who, age[who]);

  const page = await openPage(board.url + 'watch', { width: 1440, height: 900, ready: `document.querySelectorAll('.w-tile').length > 0 && !!document.getElementById('conn')` });
  const { send, ev, waitFor, errors } = page;
  const shot = async name => { if (!SHOTS) return; mkdirSync(SHOTS, { recursive: true }); const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(SHOTS, name), Buffer.from(r.data, 'base64')); };
  const tile = who => `.w-tile[data-wid="${ids[who]}"]`;
  const info = who => ev(`(() => { const t = document.querySelector('${tile(who)}'); return t && { cls: t.className, heard: (t.querySelector('.w-heard') || {}).textContent, age: !!t.querySelector('.w-age'), p: t.dataset.p, fg: t.querySelector('.fg').getAttribute('stroke-dasharray') }; })()`);
  await waitFor(`!!document.querySelector('${tile('linus')}')`);

  console.log('A: each tile says how long since its agent was heard');
  let a = await info('ada'), g = await info('grace'), l = await info('linus');
  check('under a minute is fresh: heard Ns ago', /\bfresh\b/.test(a.cls) && /^heard \d+s ago$/.test(a.heard), JSON.stringify(a));
  check('a few minutes is ageing: heard 4m ago', /\bageing\b/.test(g.cls) && /^heard 4m ago$/.test(g.heard), JSON.stringify(g));
  check('past the limit (10 min) is silent: last heard, and a QUIET tag', /\bsilent\b/.test(l.cls) && /^last heard 12m agoquiet$/i.test(l.heard), JSON.stringify(l));
  check('the old top-right age is gone from a working tile', !a.age && !g.age && !l.age);
  check('the limit is the setting: /api/config carries silent_minutes (10 by default)', await ev(`fetch('/api/config').then(r => r.json()).then(c => c.silent_minutes === 10)`));
  check('each tile has a state class and only one of them', await ev(`['${tile('ada')}', '${tile('grace')}', '${tile('linus')}'].every(s => ['fresh', 'ageing', 'silent'].filter(c => document.querySelector(s).classList.contains(c)).length === 1)`));
  check('silent is amber, fresh is not (the ring colour)', await ev(`getComputedStyle(document.querySelector('${tile('linus')} .fg')).stroke !== getComputedStyle(document.querySelector('${tile('ada')} .fg')).stroke`));
  await shot('connected-light.png');

  console.log('B: honest: nothing here moves the percent, and a tile ages without a redraw');
  await sleep(2500);
  const a2 = await info('ada');
  check('the percent and the ring did not move while time passed', a2.p === a.p && a2.fg === a.fg, JSON.stringify([a.p, a2.p, a.fg, a2.fg]));
  await ev(`document.querySelector('${tile('ada')}').__same = 1`);
  setAge('ada', 70);   // the agent has now been quiet for 70 s: the board's data changes underneath the page, so the page refetches; that is not what ages the tile
  await ev(`window.__upd = document.querySelector('${tile('ada')}').dataset.upd`);
  await waitFor(`document.querySelector('${tile('ada')}') && document.querySelector('${tile('ada')}').dataset.upd !== window.__upd`);   // the new timestamp arrived
  check('a tile past a minute turns ageing on the poll beat', await waitFor(`document.querySelector('${tile('ada')}').classList.contains('ageing')`, 8000));
  const stamps = await ev(`document.querySelector('${tile('ada')}').dataset.upd`);
  const before = await ev(`document.querySelector('${tile('grace')}').dataset.upd`);
  // Watch's agent status (the state word on a tile) rides the page's 5 s strip beat, not the 1 s poll of the tasks: Ada's new age reaches it a few seconds after the
  // tasks and the page redraws Watch once for it, which landed in the window below and failed this check on a quiet board. Take that beat now so the page has settled.
  await ev(`stripLoad()`);
  await ev(`(() => { window.__grace = document.querySelector('${tile('grace')}'); window.__graceHeard = window.__grace.querySelector('.w-heard').textContent; return 1; })()`);
  await sleep(1500);
  check('the heard line follows the clock in the same element (no redraw)', await ev(`document.querySelector('${tile('grace')}') === window.__grace`));
  const heardNow = await ev(`document.querySelector('${tile('ada')} .w-heard').textContent`);
  check('Ada now reads heard about a minute', /^heard (\d+s|1m) ago$/.test(heardNow), heardNow);

  console.log('C: the connection dot');
  await ev(`(() => { window.__seq = ['ok']; new MutationObserver(() => { const c = document.getElementById('conn').className.replace('ab-conn', '').trim() || 'ok'; if (window.__seq[window.__seq.length - 1] !== c) window.__seq.push(c); }).observe(document.getElementById('conn'), { attributes: true, attributeFilter: ['class'] }); return 1; })()`);
  let dot = await ev(`({ cls: document.getElementById('conn').className, text: document.getElementById('conn').textContent, offline: document.body.classList.contains('offline') })`);
  check('connected: Live · updated Ns ago, green, not offline', dot.cls === 'ab-conn' && /^Live.*updated \d+s ago$/.test(dot.text) && !dot.offline, JSON.stringify(dot));
  check('the dot is in the header, before the old Disconnected chip', await ev(`document.getElementById('conn').nextElementSibling.nextElementSibling === document.getElementById('status') && document.getElementById('status').hidden`));
  await shot('dot-live.png');
  await board.stopServer();
  check('the server going away turns the dot red: Reconnecting… with the last update time', await waitFor(`document.getElementById('conn').classList.contains('down') && /^Reconnecting….*last update \\d\\d:\\d\\d$/.test(document.getElementById('conn').textContent)`, 20000));
  check('it passed through amber (Slow) on the way', await ev(`window.__seq.includes('slow')`), JSON.stringify(await ev('window.__seq')));
  dot = await ev(`({ offline: document.body.classList.contains('offline'), chip: getComputedStyle(document.getElementById('status')).display, sr: document.getElementById('conn-sr').textContent, op: getComputedStyle(document.querySelector('${tile('linus')}')).opacity })`);
  check('red: the page is offline: tiles dim, the old chip steps aside, a screen reader is told once', dot.offline && dot.chip === 'none' && /Disconnected/.test(dot.sr) && Number(dot.op) < 1, JSON.stringify(dot));
  check('the tiles are still there with their heard lines (the last thing the board knew)', await ev(`!!document.querySelector('${tile('linus')} .w-heard')`));
  await shot('connection-lost.png');
  await board.startServer();
  check('the board coming back turns it green again and the tiles come back', await waitFor(`!document.getElementById('conn').classList.contains('down') && !document.body.classList.contains('offline')`, 20000));
  check('Live again: the sequence was ok, slow, down, then back to ok', await ev(`(() => { const s = window.__seq.join(','); return /ok,slow,down,(slow,)?ok$/.test(s) || /ok,slow,down,ok$/.test(s); })()`), JSON.stringify(await ev('window.__seq')));

  console.log('D: reduced motion keeps the colours and drops the animation');
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await sleep(300);
  const rm = await ev(`({ fresh: getComputedStyle(document.querySelector('.w-tile.fresh .w-ring'), '::after').animationName, ageing: getComputedStyle(document.querySelector('${tile('ada')} .w-ring'), '::after').animationName, dot: getComputedStyle(document.querySelector('.w-tile.fresh .w-heard i')).animationName })`);
  check('no animation on the ring or the dot', rm.fresh === 'none' && rm.ageing === 'none' && rm.dot === 'none', JSON.stringify(rm));
  check('a static ring is still drawn on an ageing tile (the state is not lost)', await ev(`Number(getComputedStyle(document.querySelector('${tile('ada')} .w-ring'), '::after').opacity) > 0`));
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });

  console.log('E: dark and narrow');
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
  await sleep(500);
  check('dark: the dot and the amber tile are drawn, and the page does not overflow', await ev(`document.getElementById('conn').getBoundingClientRect().width > 0 && getComputedStyle(document.querySelector('${tile('linus')}')).borderColor !== getComputedStyle(document.querySelector('${tile('grace')}')).borderColor && document.documentElement.scrollWidth <= document.documentElement.clientWidth`));
  await shot('connected-dark.png');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 900, deviceScaleFactor: 1, mobile: true });
  await sleep(700);
  const narrow = await ev(`({ over: document.documentElement.scrollWidth - document.documentElement.clientWidth, dot: (r => [r.left, r.right])(document.getElementById('conn').getBoundingClientRect()), vw: innerWidth, heard: [...document.querySelectorAll('.w-page.cur .w-tile .w-heard')].every(h => h.getBoundingClientRect().right <= innerWidth) })`);   // the current page's tiles: the other pages wait off to the side on purpose
  check('390 px wide: no horizontal overflow, the dot inside the screen, every heard line on screen', narrow.over <= 0 && narrow.dot[0] >= 0 && narrow.dot[1] <= narrow.vw && narrow.heard, JSON.stringify(narrow));
  await shot('connected-narrow.png');

  check('no console errors or exceptions', errors.length === 0, errors.slice(0, 3).join(' | '));
  page.close();
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('WATCH ALIVE'); });
