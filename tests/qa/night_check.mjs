// The night queue on the board (card retro-night-queue): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/night_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// Off by default: no header chip, the Settings row says off with a button. ORCH lines up two cards from the terminal (one title carries markup: it must stay text); the
// button turns night mode on, the chip appears with the count and the end time, the row lists the queue in order; an agent takes the first card from the terminal and the
// page follows; the button turns it off and the chip goes. Then 390 px wide. WATCH_CHECK_SHOTS=<dir> also saves screenshots. One ok/FAIL line per check; exit code 1 on a FAIL.
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const SHOTS = process.env.WATCH_CHECK_SHOTS;

async function main() {
  const board = await startBoard('night');
  const orch = (...args) => board.cli(args, { AGENTBOARD_NAME: 'ORCH' });
  const first = board.cli(['add', 'Calm the star field', '--status', 'todo']);
  const second = board.cli(['add', 'Mark <i>unknown</i> galaxies', '--status', 'todo']);
  const idOf = r => (r.out.match(/added (\S+)/) || [])[1];
  const [a, b] = [idOf(first), idOf(second)];
  check('two Todo cards to queue', !!a && !!b, first.out + second.out);
  const page = await openPage(board.url, { width: 1280, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof renderNightPane === 'function' && !!document.getElementById('cfg-night')` });
  const { send, ev, waitFor, errors } = page;
  const shot = async name => { if (!SHOTS) return; mkdirSync(SHOTS, { recursive: true }); const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(SHOTS, name), Buffer.from(r.data, 'base64')); };
  const row = () => ev(`(() => { const r = document.querySelector('#cfg-night .mix-row'); return r ? { state: r.querySelector('.val span').textContent.trim(), button: r.querySelector('button').textContent.trim(), items: [...document.querySelectorAll('#cfg-night .nq-list li')].map(li => li.textContent), markup: document.querySelectorAll('#cfg-night .nq-list i').length } : null; })()`);
  // really on screen, not only in the DOM: the row's own text is cut to two lines, and a list inside it was once there and invisible
  const seen = () => ev(`[...document.querySelectorAll('#cfg-night .nq-list li')].map(li => { const b = li.getBoundingClientRect(), at = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return b.height > 8 && !!at && li.contains(at); })`);
  const chip = () => ev(`(() => { const c = document.getElementById('night-chip'); return { hidden: c.hidden, text: c.textContent.trim() }; })()`);

  console.log('A: off by default');
  await ev(`(toggleMix(true, 'agents'), 1)`);
  check('the Settings row is there', await waitFor(`!!document.querySelector('#cfg-night .mix-row .nq-off')`, 15000));
  let r = await row();
  check('it says off and offers to turn it on until 08:00', r.state === 'off' && r.button === 'Turn on until 08:00', JSON.stringify(r));
  check('no chip in the header, no queue drawn', (await chip()).hidden && r.items.length === 0);

  console.log('B: ORCH lines up the queue, the owner turns it on');
  const q = orch('night', 'queue', 'add', a, b);
  check('ORCH queues both cards', q.status === 0 && /queued/.test(q.out), q.out);
  const worker = board.cli(['night', 'queue', 'add', a], { AGENTBOARD_NAME: 'AGENT-9' });
  check('a worker agent is refused', worker.status !== 0 && /only ORCH or the owner/.test(worker.out), worker.out);
  await ev(`nightLoad()`);
  check('the row counts the cards lined up while it is off', await waitFor(`/2 cards are lined up/.test(document.querySelector('#cfg-night .mix-about').textContent)`, 8000));
  await ev(`document.querySelector('#cfg-night [data-night="on"]').click()`);
  check('the chip appears: Night, the count, the end time', await waitFor(`(() => { const c = document.getElementById('night-chip'); return !c.hidden && /Night/.test(c.textContent) && /2 queued/.test(c.textContent); })()`, 8000), JSON.stringify(await chip()));
  check('the chip ends at 08:00 and names it in its tooltip', await ev(`/until 08:00/.test(document.getElementById('night-chip').textContent) && /until 08:00: 2 cards queued/.test(document.getElementById('night-chip').title)`));
  r = await row();
  check('the row says on until 08:00 and offers Turn off', /^on until 08:00$/.test(r.state) && r.button === 'Turn off', JSON.stringify(r));
  check('the queue is listed in order, each with its id', r.items.length === 2 && r.items[0].startsWith('Calm the star field') && r.items[0].endsWith(a) && r.items[1].endsWith(b), JSON.stringify(r.items));
  check('a title with markup stays text', r.markup === 0 && r.items[1].includes('<i>unknown</i>'), JSON.stringify(r.items));
  check('every queued card is really visible on screen, not clipped', JSON.stringify(await seen()) === '[true,true]', JSON.stringify(await seen()));
  check('the description under the switch is not cut mid-sentence', await ev(`(() => { const a = document.querySelector('#cfg-night .mix-about'); return a.scrollHeight <= a.clientHeight + 1; })()`));
  const posted = board.cli(['chat', 'tail', '--limit', '3']);
  check('turning it on posted one line to the chat', /night mode is on until 08:00: 2 cards queued/.test(posted.out), posted.out);
  await shot('night-on.png');

  console.log('C: an agent takes the first card; the page follows');
  const take = board.cli(['night', 'next', '--name', 'AGENT-9']);
  check('the take claims the first card and states the night rules', take.status === 0 && take.out.includes(`took ${a}`) && /no push, no spend/.test(take.out), take.out);
  await ev(`nightLoad()`);
  check('the chip counts one left', await waitFor(`/1 queued/.test(document.getElementById('night-chip').textContent)`, 8000), JSON.stringify(await chip()));
  check('the row lists only the card still waiting', await waitFor(`document.querySelectorAll('#cfg-night .nq-list li').length === 1`, 8000), JSON.stringify(await row()));
  const again = board.cli(['night', 'next', '--name', 'AGENT-9']);
  check('the same agent is told to hand its card in first', again.status !== 0 && /you hold/.test(again.out), again.out);

  console.log('D: 390 px wide, then off');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 900, deviceScaleFactor: 1, mobile: true });
  await sleep(400);
  const narrow = await ev(`({ page: document.documentElement.scrollWidth - document.documentElement.clientWidth, row: document.querySelector('#cfg-night').scrollWidth - document.querySelector('#cfg-night').clientWidth })`);
  check('the page does not scroll sideways and the row stays inside the screen', narrow.page <= 0 && narrow.row <= 0, JSON.stringify(narrow));
  await shot('night-narrow.png');
  await send('Emulation.clearDeviceMetricsOverride');
  await ev(`document.querySelector('#cfg-night [data-night="off"]').click()`);
  check('Turn off: the chip goes and the row says off', await waitFor(`document.getElementById('night-chip').hidden && !!document.querySelector('#cfg-night .nq-off')`, 8000), JSON.stringify(await chip()));
  const left = board.cli(['night', 'next', '--name', 'AGENT-8']);
  check('an agent that asks now is told night mode is off', left.status !== 0 && /night mode is off/.test(left.out), left.out);
  check('no script errors on the page', errors.length === 0, errors.join(' | '));
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('NIGHT'); });
