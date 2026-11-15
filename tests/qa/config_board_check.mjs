// The configuration picker and the Rename dialog on the board (card agent-config-slice-3): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/config_board_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// Settings > Agents: the three configurations in the board's order, the table of roles with what each may and may not do, Apply (the roster and labels only: no card
// changes), the terminals to type with a Copy button, the header chip with the listening count, Remove, and the "off" line when the setting is off. The Rename dialog:
// the counts before a name is typed, a refused name says why and keeps Rename off, Esc closes only the dialog, Rename changes every card and Undo puts it back.
// Then 390 px wide. WATCH_CHECK_SHOTS=<dir> also saves screenshots. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { appendFileSync } from 'node:fs';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const SHOTS = process.env.WATCH_CHECK_SHOTS;

async function main() {
  const board = await startBoard('cfgboard');
  appendFileSync(join(board.dir, 'config.toml'), '\n[agents]\nconfigurations = true\n');
  const page = await openPage(board.url, { width: 1280, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof renderCfgPane === 'function' && !!document.getElementById('cfg-config')` });
  const { send, ev, waitFor, errors } = page;
  const shot = async name => { if (!SHOTS) return; mkdirSync(SHOTS, { recursive: true }); const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(SHOTS, name), Buffer.from(r.data, 'base64')); };
  const press = async (key, code, vk) => { const base = { key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk }; await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base, text: key.length === 1 ? key : undefined }); await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base }); await sleep(150); };
  const cards = () => ev(`fetch('/api/tasks').then(r => r.json()).then(j => j.tasks.filter(t => !t.parent_id).map(t => [t.id, t.status, t.agent || '']))`);

  console.log('A: Settings > Agents: the picker');
  await ev(`(toggleMix(true, 'agents'), 1)`);
  check('the configuration pane is there and says what is on offer', await waitFor(`document.querySelectorAll('#cfg-config .cfg-opt').length === 3`, 15000));
  const opts = await ev(`[...document.querySelectorAll('#cfg-config .cfg-opt')].map(b => b.querySelector('b').textContent.trim() + ' | ' + b.querySelector('span').textContent.trim())`);
  check('Build, Dream up and Day to day, in that order, each with its agents', opts[0].startsWith('Build or improve an application') && /5 agents · dev ×2, qa, architect, designer/.test(opts[0]) && opts[1].startsWith('Dream up') && opts[2].startsWith('Day to day'), JSON.stringify(opts));
  const table = await ev(`({ rows: document.querySelectorAll('#cfg-config .cfg-role').length, head: document.querySelector('#cfg-config .cfg-detail h4').textContent, not: document.querySelector('#cfg-config .cfg-role .not').textContent, may: document.querySelector('#cfg-config .cfg-role .may').textContent })`);
  check('the first is open: four roles, each with what it may and may not do', table.rows === 4 && /Build/.test(table.head) && /merge/.test(table.not) && /code/.test(table.may), JSON.stringify(table));
  check('the terminals to type are listed, one line each, with a Copy button', await ev(`document.querySelectorAll('#cfg-config .cfg-term').length === 5 && document.querySelector('#cfg-config .cfg-term code').textContent === '/rename Dev-1'`));
  const before = await cards();
  await ev(`document.querySelector('#cfg-config [data-cfg-pick="dream-up"]').click()`);
  check('picking another shows it without applying anything', await ev(`/Dream up/.test(document.querySelector('#cfg-config .cfg-detail h4').textContent) && document.querySelector('#cfg-config .cfg-cur b').textContent === 'none'`));
  await ev(`document.querySelector('#cfg-config [data-cfg-apply]').click()`);
  check('Apply: the pane says what is applied', await waitFor(`document.querySelector('#cfg-config .cfg-cur b').textContent.startsWith('Dream up')`, 8000));
  check('Apply changed no card', JSON.stringify(await cards()) === JSON.stringify(before));
  check('the header chip names it and counts who is listening', await waitFor(`(() => { const c = document.getElementById('cfg-chip'); return !c.hidden && /Dream up/.test(c.textContent) && /0 of 4 listening/.test(c.textContent); })()`, 8000), await ev(`document.getElementById('cfg-chip').textContent`));
  check('the applied one is marked and its button says Applied', await ev(`!!document.querySelector('#cfg-config .cfg-opt[aria-pressed="true"] i') && document.querySelector('#cfg-config .cfg-go button').textContent === 'Applied'`));
  await ev(`document.querySelector('#cfg-config [data-cfg-copy]').click()`);
  check('Copy answers (copied, or a line to select where the browser refuses the clipboard)', await waitFor(`/Copied|Select it/.test(document.querySelector('#cfg-config [data-cfg-copy]').textContent)`, 3000));
  await shot('picker.png');
  await ev(`document.querySelector('#cfg-config [data-cfg-clear]').click()`);
  check('Remove takes it off and the chip goes', await waitFor(`document.querySelector('#cfg-config .cfg-cur b').textContent === 'none' && document.getElementById('cfg-chip').hidden`, 8000));

  console.log('B: the Rename dialog');
  const names = await ev(`[...document.querySelectorAll('#cfg-listen [data-rename]')].map(b => b.dataset.rename)`);
  const all = await cards();
  const who = names.find(n => all.some(c => c[2] === n)) || '';   // an agent that holds cards, so the rename has something to move
  check('an agent row in Settings has Rename…, for an agent that holds cards', !!who, JSON.stringify(names));
  const held = all.filter(c => c[2] === who).length;
  check('the agent holds more than one card', held > 0, String(held));
  await ev(`document.querySelector('#cfg-listen [data-rename="${who}"]').click()`);
  check('the dialog opens with the counts, before a name is typed', await waitFor(`document.getElementById('rename').classList.contains('on') && document.querySelectorAll('#rename-counts li').length >= 3 && document.getElementById('rename-go').disabled`, 8000));
  check('it is titled with the agent and says history stays as written', await ev(`document.getElementById('rename-h').textContent === 'Rename ' + ${JSON.stringify(who)} && /history is history/.test(document.getElementById('rename-counts').textContent)`));
  check('the field has focus', await ev(`document.activeElement === document.getElementById('rename-new')`));
  await ev(`(() => { const i = document.getElementById('rename-new'); i.value = 'ORCH'; i.dispatchEvent(new Event('input')); return 1; })()`);
  check('a name the board keeps is refused with the reason, and Rename stays off', await waitFor(`/keeps for itself/.test(document.getElementById('rename-err').textContent) && document.getElementById('rename-go').disabled`, 6000));
  await ev(`(() => { const i = document.getElementById('rename-new'); i.value = 'Ives-X'; i.dispatchEvent(new Event('input')); return 1; })()`);
  check('a free name clears the error and turns Rename on', await waitFor(`document.getElementById('rename-err').hidden && !document.getElementById('rename-go').disabled`, 6000));
  await shot('rename.png');
  await ev(`document.getElementById('rename-cancel').focus()`);
  await press('n', 'KeyN', 78);
  check('while the dialog is open a board key does nothing behind it (n does not open the new-task sheet)', await ev(`!document.getElementById('add').classList.contains('open')`));
  await press('Escape', 'Escape', 27);
  check('Esc closes the dialog and leaves Settings open', await ev(`!document.getElementById('rename').classList.contains('on') && mixIsOpen()`));
  check('focus goes back to the Rename… link it came from', await ev(`document.activeElement && document.activeElement.dataset.rename === ${JSON.stringify(who)}`));
  check('nothing was renamed by closing it', (await cards()).filter(c => c[2] === who).length === held);
  await ev(`document.querySelector('#cfg-listen [data-rename="${who}"]').click()`);
  await waitFor(`document.getElementById('rename').classList.contains('on')`, 5000);
  await ev(`(() => { const i = document.getElementById('rename-new'); i.value = 'Ives-X'; i.dispatchEvent(new Event('input')); return 1; })()`);
  await waitFor(`!document.getElementById('rename-go').disabled`, 6000);
  await ev(`document.getElementById('rename-go').click()`);
  check('Rename: the result says what changed and where to type it', await waitFor(`!document.getElementById('rename-done').hidden && /Renamed\\./.test(document.getElementById('rename-done').textContent) && /\\/rename Ives-X/.test(document.getElementById('rename-done').textContent)`, 10000));
  const after = await cards();
  check('every card it held now says the new name, none the old', after.filter(c => c[2] === 'Ives-X').length === held && after.filter(c => c[2] === who).length === 0, JSON.stringify([held, after.filter(c => c[2] === 'Ives-X').length]));
  await shot('renamed.png');
  await ev(`document.getElementById('rename-undo').click()`);
  check('Undo: it says so and the cards are back under the old name', await waitFor(`/Undone\\./.test(document.getElementById('rename-done').textContent)`, 10000) && (await cards()).filter(c => c[2] === who).length === held);
  await ev(`document.getElementById('rename-close').click()`);

  console.log('B2: the slots another card fills (proposals, import, export)');
  await ev(`(window.cfgAddons = { proposalsHtml: st => '<div id="stub-prop">a proposal for ' + st.builtin.length + '</div>', importButton: () => '<button class="btn" id="stub-imp" type="button">Import a configuration file…</button>', exportHref: k => '/api/configuration/export?key=' + k }, renderCfgPane(), 1)`);
  check('a proposal draws above the picker, the import button under the list, and Export in the detail heading', await ev(`(() => { const r = document.getElementById('cfg-config'); return !!r.querySelector('.cfg-props #stub-prop') && !!r.querySelector('.cfg-imp #stub-imp') && r.querySelector('.cfg-head a.cfg-exp').getAttribute('href').startsWith('/api/configuration/export?key=') && r.firstElementChild.classList.contains('cfg-props'); })()`));
  await ev(`(window.__loads = 0, window.__f = window.fetch, window.fetch = (u, o) => { if (String(u).includes('/api/configurations')) window.__loads++; return window.__f(u, o); }, document.dispatchEvent(new Event('cfg-changed')), 1)`);
  check('the cfg-changed event makes the pane read the board again', await waitFor(`window.__loads >= 1`, 5000));
  await ev(`(window.fetch = window.__f, delete window.cfgAddons, renderCfgPane(), 1)`);
  check('without the slots the pane draws as before (no proposals, no import, no Export)', await ev(`!document.querySelector('#cfg-config .cfg-props') && !document.querySelector('#cfg-config .cfg-imp') && !document.querySelector('#cfg-config .cfg-exp')`));

  console.log('C: off, and narrow');
  writeFileSync(join(board.dir, 'config.toml'), '[board]\nowner = "you"\n');
  await ev(`(toggleMix(false), toggleMix(true, 'agents'), 1)`);
  check('with the setting off the pane says so and the chip is hidden', await waitFor(`/off/.test(document.querySelector('#cfg-config .val').textContent) && document.getElementById('cfg-chip').hidden && /agents\\] configurations = true/.test(document.getElementById('cfg-config').textContent)`, 8000));
  appendFileSync(join(board.dir, 'config.toml'), '\n[agents]\nconfigurations = true\n');
  await ev(`(toggleMix(false), toggleMix(true, 'agents'), 1)`);
  await waitFor(`document.querySelectorAll('#cfg-config .cfg-opt').length === 3`, 8000);
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 900, deviceScaleFactor: 1, mobile: true });
  await sleep(700);
  const narrow = await ev(`({ page: document.documentElement.scrollWidth - document.documentElement.clientWidth, sheet: document.querySelector('#mix .sheet').getBoundingClientRect().width, detail: document.querySelector('#cfg-config .cfg-detail').getBoundingClientRect().right - innerWidth, list: document.querySelector('#cfg-config .cfg-list').getBoundingClientRect().right - innerWidth })`);
  check('390 px wide: the page does not scroll sideways and the list and the roles stay inside the screen', narrow.page <= 0 && narrow.detail <= 0 && narrow.list <= 0, JSON.stringify(narrow));
  await shot('narrow.png');
  await ev(`(toggleMix(false), document.querySelector('[data-rename]') ? 1 : 1)`);
  check('no console errors or exceptions', errors.length === 0, errors.slice(0, 3).join(' | '));
  page.close();
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('CONFIG BOARD'); });
