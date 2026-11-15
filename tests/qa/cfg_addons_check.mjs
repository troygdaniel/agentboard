// Agent configurations, add-ons (card agent-config-slice-3b): what ORCH suggests with Accept and Ignore, and the Import dialog, in headless Chrome on a throwaway board, narrow then wide.
// The picker panel (card agent-config-slice-3) places `cfgAddons.proposalsHtml(state)` and `cfgAddons.importButton()`; this check mounts them in a plain box so it does not depend on that panel.
//
//     node tests/qa/cfg_addons_check.mjs         (BOARD_CHECK_SRC=<another checkout's src> runs it against that code)
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const GOOD = JSON.stringify({ configuration: 1, name: 'Test team', description: 'a made-up team', roles: [{ role: 'writer', names: ['Writer-1'], purpose: 'writes the drafts', model: 'sonnet', size: 'M', may: ['draft'], may_not: ['send a message'], tools: ['board'] }] });
const BADKEY = JSON.stringify({ configuration: 1, name: 'X', roles: [{ role: 'a', names: ['A-1'], zip: 1 }] });

async function main() {
  const board = await startBoard('cfgx');
  appendFileSync(join(board.dir, 'config.toml'), '\n[agents]\nconfigurations = true\n');
  board.cli(['configuration', 'apply', 'day-to-day']);
  const orch = (...a) => board.cli(['configuration', 'propose', ...a], { AGENTBOARD_NAME: 'ORCH' });
  check('ORCH proposes one more caller', orch('--add-name', 'Caller-2', '--role', 'caller', '--why', '5 of 9 <b>cards</b> waited on a call').status === 0);
  check('ORCH proposes a configuration to switch to', orch('--apply', 'build', '--why', 'the work is mostly code now').status === 0);
  const exported = () => JSON.parse(board.cli(['configuration', 'export']).out);

  for (const [label, width, height] of [['narrow', 390, 800], ['wide', 1280, 800]]) {
    console.log(`${label} (${width}px)`);
    const page = await openPage(board.url, { ready: `typeof cfgAddons === 'object' && typeof api === 'function'`, width, height });
    await page.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 700 });
    await page.ev(`(async () => { window.__ev = []; document.addEventListener('cfg-changed', e => window.__ev.push(e.detail)); const st = await (await fetch('/api/configurations')).json(); window.__st = st;
      const box = document.createElement('div'); box.id = 'cx-test'; box.style.cssText = 'position:fixed;left:8px;right:8px;top:70px;z-index:5;background:var(--bg);padding:8px'; box.innerHTML = cfgAddons.proposalsHtml(st) + cfgAddons.importButton(); document.body.appendChild(box); return true; })()`);
    await page.waitFor(`!!document.querySelector('#cx-test .cx-prop')`, 8000);
    const pr = await page.ev(`({ n: document.querySelectorAll('#cx-test .cx-prop').length, text: [...document.querySelectorAll('#cx-test .cx-prop p')].map(p => p.textContent), btns: [...document.querySelectorAll('#cx-test .cx-prop .btn')].map(b => b.textContent),
      note: document.querySelector('#cx-test .cx-prop small')?.textContent, inj: !!document.querySelector('#cx-test .cx-prop p b'), over: document.documentElement.scrollWidth > document.documentElement.clientWidth })`);
    check(`${label}: both suggestions show, each with its sentence`, pr.n === 2 && pr.text[0].startsWith('Add Caller-2 to the caller role') && pr.text[1].startsWith('Switch to the build configuration'), JSON.stringify(pr.text));
    check(`${label}: the reason is shown as text, never as markup`, pr.text[0].includes('<b>cards</b>') && pr.inj === false);
    check(`${label}: Accept says what it does, Ignore is next to it, and nothing changes until you accept`, pr.btns.join('|') === 'Accept (adds Caller-2 to the roster)|Ignore|Accept (applies build)|Ignore' && /Nothing changes until you accept/.test(pr.note), JSON.stringify(pr.btns));
    check(`${label}: showing a suggestion changed nothing`, exported().roles[0].names.join() === 'Caller-1');

    // the Import dialog
    const load = (name, content) => page.ev(`(() => { const i = document.getElementById('cx-file'); const dt = new DataTransfer(); dt.items.add(new File([${JSON.stringify(content)}], ${JSON.stringify(name)}, { type: 'application/json' })); i.files = dt.files; i.dispatchEvent(new Event('change')); return true; })()`);
    await page.ev(`(() => { document.querySelector('#cx-test [data-cx-import]').click(); return true; })()`);
    check(`${label}: Import a file opens a dialog`, await page.ev(`!!document.getElementById('cx-import')?.open`));
    await load('bad.json', BADKEY); await page.waitFor(`!!document.querySelector('#cx-out .cx-err')`, 6000);
    let d = await page.ev(`({ err: document.querySelector('#cx-out .cx-err')?.textContent || '', apply: document.querySelector('[data-cx-apply]').disabled })`);
    check(`${label}: a file with an unknown key is refused in plain words, Apply stays off`, /unknown key/.test(d.err) && d.apply === true, JSON.stringify(d));
    await load('words.json', 'not json at all');
    check(`${label}: a file that is not JSON is refused`, await page.waitFor(`/not JSON/.test(document.querySelector('#cx-out .cx-err')?.textContent || '')`, 6000));
    await load('huge.json', ' '.repeat(70000));
    check(`${label}: a file over 64 KB is refused without being read`, await page.waitFor(`/over 64 KB/.test(document.querySelector('#cx-out .cx-err')?.textContent || '') && document.querySelector('[data-cx-apply]').disabled`, 6000));
    await load('team.json', GOOD); await page.waitFor(`!!document.querySelector('#cx-out .cx-role')`, 6000);
    d = await page.ev(`({ name: document.querySelector('#cx-out h4')?.textContent, role: document.querySelector('#cx-out .cx-role b')?.textContent, not: document.querySelector('#cx-out .cx-role .not')?.textContent, term: [...document.querySelectorAll('#cx-out .cx-term code')].map(c => c.textContent),
      apply: document.querySelector('[data-cx-apply]').disabled, dlgOver: document.getElementById('cx-import').scrollWidth > document.getElementById('cx-import').clientWidth + 1, over: document.documentElement.scrollWidth > document.documentElement.clientWidth })`);
    check(`${label}: a good file is shown: its roles, what a role may not do and the terminals`, d.name === 'Test team' && d.role === 'writer' && d.not === 'send a message' && d.term.join() === '/rename Writer-1' && d.apply === false, JSON.stringify(d));
    check(`${label}: the dialog and the page do not scroll sideways`, !d.dlgOver && !d.over, JSON.stringify(d));
    check(`${label}: previewing applied nothing`, exported().name === 'Day to day');
    // Esc leaves without applying
    await page.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 }); await page.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await sleep(300);
    check(`${label}: Esc closes the dialog and applies nothing`, (await page.ev(`!document.getElementById('cx-import').open`)) && exported().name === 'Day to day');

    if (label === 'wide') {
      // Ignore one, Accept the other: only a click applies
      await page.ev(`(() => { document.querySelector('#cx-test [data-cx-decide="ignored"][data-id="2"]').click(); return true; })()`);
      await page.waitFor(`document.querySelectorAll('#cx-test .cx-prop').length === 1`, 6000);
      check('wide: Ignore removes the suggestion and changes nothing else', exported().name === 'Day to day' && /#2  ignored/.test(board.cli(['configuration', 'proposals']).out));
      await page.ev(`(() => { document.querySelector('#cx-test [data-cx-decide="accepted"][data-id="1"]').click(); return true; })()`);
      await page.waitFor(`document.querySelectorAll('#cx-test .cx-prop').length === 0`, 6000);
      check('wide: Accept adds the name to the role', exported().roles[0].names.join() === 'Caller-1,Caller-2' && /#1  accepted/.test(board.cli(['configuration', 'proposals']).out));
      check('wide: the page was told (cfg-changed, with the new state)', await page.ev(`window.__ev.length === 2 && window.__ev[1].proposals.length === 0 && window.__ev[1].applied.roles[0].names.length === 2`));
      // Apply the good file
      await page.ev(`(() => { document.querySelector('#cx-test [data-cx-import]').click(); return true; })()`);
      await load('team.json', GOOD); await page.waitFor(`!!document.querySelector('#cx-out .cx-role')`, 6000);
      await page.ev(`(() => { document.querySelector('[data-cx-apply]').click(); return true; })()`);
      await page.waitFor(`!!document.querySelector('#cx-out .cx-ok')`, 8000);
      const ok = await page.ev(`({ ok: document.querySelector('#cx-out .cx-ok')?.textContent || '', close: document.querySelector('[data-cx-close]').textContent, apply: document.querySelector('[data-cx-apply]').hidden })`);
      check('wide: Apply applies the file, says so, and offers Done', /Applied: Test team/.test(ok.ok) && ok.close === 'Done' && ok.apply, JSON.stringify(ok));
      check('wide: the board now has that configuration', exported().name === 'Test team');
      check('wide: the page was told again', await page.ev(`window.__ev.length === 3 && window.__ev[2].applied.name === 'Test team'`));
      // in the picker panel itself (card agent-config-slice-3 places the add-ons in Settings > Agents)
      await page.ev(`(() => { document.getElementById('cx-import').close(); return true; })()`);
      check('wide: ORCH suggests a name on the applied configuration', orch('--add-name', 'Writer-2', '--role', 'writer', '--why', 'one writer waited on another').status === 0);
      await page.ev(`(toggleMix(true, 'agents'), 1)`);
      check('wide: Settings > Agents shows the suggestion with Accept and Ignore, and the Import button', await page.waitFor(`!!document.querySelector('#cfg-config .cx-prop') && !!document.querySelector('#cfg-config [data-cx-import]') && document.querySelectorAll('#cfg-config .cx-prop .btn').length === 2`, 15000));
      await page.ev(`(() => { document.querySelector('#cfg-config [data-cx-decide="accepted"]').click(); return true; })()`);
      check('wide: Accept in the picker applies it, and the pane draws without the suggestion', await page.waitFor(`!document.querySelector('#cfg-config .cx-prop')`, 10000) && exported().roles[0].names.join() === 'Writer-1,Writer-2', JSON.stringify(exported().roles[0].names));
      await page.ev(`(() => { document.querySelector('#cfg-config [data-cx-import]').click(); return true; })()`);
      check('wide: Import a file… in the picker opens the dialog', await page.waitFor(`!!document.getElementById('cx-import')?.open`, 5000));
    }
    check(`${label}: no script errors`, page.errors.length === 0, page.errors.join(' | '));
    page.close();
  }
}

main().catch(e => fail('check crashed: ' + (e.stack || e))).finally(async () => { await stopAll(); done('configuration add-ons check'); });
