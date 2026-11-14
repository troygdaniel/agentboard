// Insights v0 on a real page (card agentboard-insights-v0): a card added from the board's own page, with [insights] enabled, records the owner as the actor of its
// "Added" entry and the page shows the card and raises no console error; `agentboard insights` then reads that board. Headless Chrome on a throwaway board,
// never the live one:  node tests/qa/insights_check.mjs      (BOARD_CHECK_SRC=<another checkout's src> to run against other code)
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('insights');
  const conf = join(board.dir, 'config.toml');
  if (!existsSync(conf) || !/\[insights\]/.test(readFileSync(conf, 'utf8'))) appendFileSync(conf, '\n[insights]\nenabled = true\n');   // the flag, written the way an owner would
  const page = await openPage(board.url, { ready: `!!document.querySelector('#orch-line') && typeof api === 'function'` });
  const { ev, waitFor, errors } = page;

  // the page's own add: the same POST the Add form sends; the card is then read back from the board's file
  const fromFile = () => JSON.parse(readFileSync(join(board.dir, 'tasks.json'), 'utf8')).tasks.find(t => t.id === 'insights-probe-card');
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const settle = async ok => { for (let i = 0; i < 60; i++) { if (ok(fromFile())) return; await sleep(100); } };   // ev does not await a promise: fire the request, then poll the file
  await ev(`(() => { api('/api/tasks', { title: 'insights probe card', status: 'todo' }); return true; })()`);
  await settle(c => !!c);
  const made = fromFile();
  check('the page adds a card', !!made, 'no card with that id in tasks.json');
  const first = made && made.log && made.log[0];
  check('its Added entry keeps the owner as actor, and the text is the one it always was', !!first && first.text === 'Added to todo' && typeof first.actor === 'string' && first.actor.length > 0, JSON.stringify(first));
  check('the actor is not in `by`, so the card log shows nothing new', !!first && first.by === undefined, JSON.stringify(first));
  check('the page lists the new card', await waitFor(`byId.has('insights-probe-card')`, 8000));

  // a card closed with no reason becomes "shipped" while the flag is on
  await ev(`(() => { api('/api/move', { id: 'insights-probe-card', status: 'done', before: null }); return true; })()`);
  await settle(c => c && c.status === 'done');
  const card = fromFile();
  check('closing it from the page records the default reason', card && card.status === 'done' && card.closed_as === 'shipped', JSON.stringify(card && { status: card.status, closed_as: card.closed_as }));

  const r = board.cli(['insights', '--since', 'all']);
  check('agentboard insights reads that board: the head and four rules', r.status === 0 && /Insights over \d+ cards/.test(r.out) && /Blocked cards wait/.test(r.out) && /The nights are idle/.test(r.out), r.out.slice(0, 300));
  check('and it prints no card title', !/insights probe card/.test(r.out));
  check('the page raised no console errors', errors.length === 0, errors.join(' | '));
  page.close();
}

try { await main(); } catch (e) { fail('the check ran: ' + e.message); } finally { await stopAll(); }
done('INSIGHTS CHECK');
