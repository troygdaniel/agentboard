// Agent state history in a real server (card agentboard-insights-agent-states): a throwaway board is served, [insights] is turned on while it runs, and within a couple of
// ticks (one a minute) .agentboard/agent-states.jsonl has a line for each agent the made-up board has, each a name, a state word and a time and nothing else;
// `agentboard insights` then prints the waiting-for-work row. No Chrome: the sampler is the server's own thread.     node tests/qa/states_check.mjs   (takes about a minute)
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const STATES = ['working', 'quiet', 'abandoned', 'waiting', 'review', 'listening', 'away'];

async function main() {
  const board = await startBoard('states');
  const file = join(board.dir, 'agent-states.jsonl');
  await sleep(1500);
  check('with the flag off the server writes no state file', !existsSync(file));
  appendFileSync(join(board.dir, 'config.toml'), '\n[insights]\nenabled = true\n');   // turned on while the server runs: the tick reads the flag each time
  let lines = [];
  for (let i = 0; i < 160 && lines.length === 0; i++) { await sleep(500); if (existsSync(file)) lines = readFileSync(file, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)); }   // up to 80 s: one tick is 60 s
  check('a tick after the flag went on writes the agents\' states', lines.length >= 1, `lines: ${lines.length}`);
  check('each line is a time, an agent name and a known state, and nothing else', lines.every(l => Object.keys(l).sort().join() === 'agent,at,state' && STATES.includes(l.state) && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$/.test(l.at)), JSON.stringify(lines[0]));
  const agents = new Set(lines.map(l => l.agent));
  check('there is one line for every agent that holds a card on the made-up board', agents.size >= 4 && [...agents].every(a => /^[A-Za-z0-9_.-]+$/.test(a)), [...agents].join());
  const r = board.cli(['insights', '--since', 'all']);
  check('agentboard insights prints the waiting-for-work row from that history', r.status === 0 && /Waiting for work/.test(r.out) && /observed hours|waited for work/.test(r.out), r.out.slice(-300));
  check('and no card title or agent text is in the state file', !/a made-up|title|result/i.test(readFileSync(file, 'utf8')));
}

try { await main(); } catch (e) { fail('the check ran: ' + e.message); } finally { await stopAll(); }
done('STATES CHECK');
