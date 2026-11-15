// A throwaway board and a headless Chrome on it, for the DOM checks under tests/qa/ (esc_field_check.mjs, talk_check.mjs). Never the live board.
//
//     const board = await startBoard('esc');              // a made-up board (tests/qa/seed_render_board.py) served on a free port from this checkout's src/
//     const page = await openPage(board.url, { init });   // headless Chrome (muted, its own profile), one DevTools socket; init runs in every new document
//     await page.ev(`document.title`);                    // evaluate and get the JSON value back (a promise is awaited in the page first: fetch(...).then(...) works)
//     board.cli(['chat', 'send', 'a line', '--name', 'ORCH']);   // run agentboard against that board, as the shell of an agent would
//     await board.stopServer(); await board.startServer();   // the board goes away and comes back on the same port (a lost connection)
//     await stopAll();                                    // stops only the processes started here and removes only the directories made here
//
// BOARD_CHECK_SRC=<another checkout's src> runs the check against that code (to see it fail without a fix). Needs Node 22+ (the built-in WebSocket),
// python3 and Google Chrome on this Mac (PYTHON=... and CHROME=... override them).
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SRC = process.env.BOARD_CHECK_SRC || process.env.ESC_CHECK_SRC ? resolve(process.env.BOARD_CHECK_SRC || process.env.ESC_CHECK_SRC) : join(REPO, 'src');
const PY = process.env.PYTHON || 'python3';
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
export const sleep = ms => new Promise(r => setTimeout(r, ms));

const procs = [], dirs = [];
const freePort = () => new Promise((res, rej) => { const s = createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); s.on('error', rej); });
const cleanEnv = () => Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('AGENTBOARD_')));

export async function startBoard(tag = 'check') {
  // the seed script only takes a scratch dir under /tmp, /private/tmp or /var/folders
  const scratch = join(process.platform === 'darwin' ? '/private/tmp' : '/tmp', `agentboard-${tag}-check-${process.pid}`); dirs.push(scratch);
  const seed = spawnSync(PY, [join(REPO, 'tests/qa/seed_render_board.py'), scratch, SRC], { cwd: REPO, encoding: 'utf8' });
  if (seed.status !== 0) throw new Error('seed failed: ' + (seed.stderr || seed.stdout));
  const port = await freePort();
  const env = { ...cleanEnv(), PYTHONPATH: SRC, HOME: join(scratch, 'home'), AGENTBOARD_DIR: join(scratch, 'proj', '.agentboard') };
  const cwd = join(scratch, 'proj');
  let server = null;
  const startServer = async () => {   // also how a check brings the board back after stopServer()
    server = spawn(PY, ['-m', 'agentboard', 'serve', '--no-open', '--port', String(port)], { cwd, env, stdio: 'ignore' }); procs.push(server);
    for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/`)).ok) break; } catch (e) { /* not up yet */ } await sleep(100); }
  };
  const stopServer = async () => {   // the board goes away mid-session (a lost connection); only the server this call started is stopped
    const s = server; if (!s) return; server = null;
    await new Promise(res => { s.once('exit', res); try { s.kill('SIGTERM'); } catch (e) { res(); } setTimeout(res, 3000); });
  };
  await startServer();
  // agentboard as an agent's shell runs it: its own environment, no name unless extraEnv gives one
  const cli = (args, extraEnv = {}) => { const r = spawnSync(PY, ['-m', 'agentboard', ...args], { cwd, env: { ...env, ...extraEnv }, encoding: 'utf8' }); return { status: r.status, out: (r.stdout || '') + (r.stderr || '') }; };
  return { port, url: `http://127.0.0.1:${port}/`, scratch, dir: join(cwd, '.agentboard'), cwd, env, cli, startServer, stopServer };
}

export async function openPage(url, { init = '', ready = 'true', width = 1280, height = 800 } = {}) {
  const profile = mkdtempSync(join(tmpdir(), `agentboard-board-chrome-${process.pid}-`)); dirs.push(profile);
  const chrome = spawn(CHROME, ['--headless=new', '--mute-audio', '--disable-gpu', '--remote-debugging-port=0', '--remote-allow-origins=*', `--user-data-dir=${profile}`,
    `--window-size=${width},${height}`, '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: 'ignore' }); procs.push(chrome);
  const portFile = join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 300 && !existsSync(portFile); i++) await sleep(100);
  if (!existsSync(portFile)) throw new Error('Chrome did not start');
  const dt = readFileSync(portFile, 'utf8').split('\n')[0];
  let tab = null;
  for (let i = 0; i < 50 && !tab; i++) { tab = (await (await fetch(`http://127.0.0.1:${dt}/json/list`)).json()).find(t => t.type === 'page'); if (!tab) await sleep(100); }
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; setTimeout(() => rej(new Error('DevTools socket did not open')), 20000); });
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
    else if (m.method === 'Runtime.exceptionThrown') errors.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push('console.error: ' + m.params.args.map(a => a.value ?? a.description).join(' '));
  };
  const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout: ' + method)); } }, 30000); });
  const ev = async expr => { const r = await send('Runtime.evaluate', { expression: `(async () => JSON.stringify(await (${expr})))()`, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value === undefined ? undefined : JSON.parse(r.result.value); };
  // poll an expression until it is truthy (the board polls once a second, so a line posted from outside shows within a few seconds)
  const waitFor = async (expr, ms = 15000) => { const end = Date.now() + ms; for (;;) { try { if (await ev(expr)) return true; } catch (e) { /* loading */ } if (Date.now() > end) return false; await sleep(150); } };
  await send('Runtime.enable'); await send('Page.enable');
  if (init) await send('Page.addScriptToEvaluateOnNewDocument', { source: init });
  await send('Page.navigate', { url });
  await waitFor(ready, 30000);
  await sleep(600);
  return { send, ev, waitFor, errors, close: () => { try { ws.close(); } catch (e) { /* gone */ } } };
}

export async function stopAll() {
  for (const p of procs) { try { p.kill('SIGTERM'); } catch (e) { /* gone */ } }
  await sleep(300);
  for (const p of procs) { try { p.kill('SIGKILL'); } catch (e) { /* gone */ } }
  for (const d of dirs) { try { if (/agentboard-[a-z]+-check-|agentboard-board-chrome-/.test(d) && (existsSync(join(d, '.agentboard-qa-scratch')) || d.includes('board-chrome'))) rmSync(d, { recursive: true, force: true }); } catch (e) { /* leave it */ } }   // only what this run made: the scratch board (with its marker) and Chrome's profile
}

// one ok/FAIL line per check, a count, and the exit code
export function checker() {
  let failed = 0, n = 0;
  const check = (name, cond, detail = '') => { n++; if (cond) console.log('  ok  ' + name); else { failed++; console.log(`  FAIL ${name}${detail ? '  (' + String(detail).slice(0, 400) + ')' : ''}`); } };
  const done = label => { console.log(failed ? `\n${label} FAIL: ${failed} of ${n} checks failed` : `\n${label} PASS: ${n} checks`); process.exitCode = failed ? 1 : 0; };
  return { check, done, fail: msg => { failed++; n++; console.log('  FAIL ' + msg); } };
}
