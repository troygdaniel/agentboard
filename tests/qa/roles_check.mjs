// Role chips (card agent-config-slice-2): with an agent configuration applied, the role sits beside the agent's name on the cards (Map and Now), the Watch tiles
// and the Load strip; an agent with no role, or a board with no configuration, shows no chip; a phone-width page does not scroll sideways. A DOM check in
// headless Chrome on a throwaway board (made-up names), wide and narrow.
//
//     node tests/qa/roles_check.mjs         (BOARD_CHECK_SRC=<another checkout's src> runs it against that code)
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('roles');
  appendFileSync(join(board.dir, 'config.toml'), '\n[agents]\nconfigurations = true\n');
  const ap = board.cli(['configuration', 'apply', 'day-to-day']);
  check('the Day to day configuration applies', ap.status === 0 && /Applied: Day to day/.test(ap.out), ap.out.slice(0, 200));
  const st = board.cli(['start', 'Book a table for Friday', '--name', 'Caller-1']);
  check('a configured agent holds a card', st.status === 0, st.out.slice(0, 200));
  board.cli(['update', 'book-a-table-for-friday', '40', 'drafting the script'], { AGENTBOARD_NAME: 'Caller-1' });
  const other = board.cli(['start', 'Unrelated work', '--name', 'Someone-Else']);
  check('an agent outside the configuration holds a card', other.status === 0, other.out.slice(0, 200));

  const api = await (await fetch(board.url + 'api/config')).json();
  check('/api/config carries the configuration name and the roles', api.configuration === 'Day to day' && api.roles['caller-1']?.role === 'caller' && !('someone-else' in api.roles), JSON.stringify(api).slice(0, 300));

  // Now shows the cards that wait on the owner: Caller-1 asks, so its card is in the pile
  board.cli(['ask', 'book-a-table-for-friday', 'Which restaurant?'], { AGENTBOARD_NAME: 'Caller-1' });

  for (const [label, width, height] of [['wide', 1280, 800], ['narrow', 390, 800]]) {
    console.log(`${label} (${width}px)`);
    const phone = width < 700;
    const metrics = p => p.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: phone });
    const where = `(() => { const hit = (sel, n) => [...document.querySelectorAll(sel)].filter(w => w.dataset.agent === n).map(w => { const c = w.querySelector('.rolechip'); return c ? { text: c.textContent, shown: getComputedStyle(c).display !== 'none' } : null; });
      return hit })()`;

    // Now: the card in front names its agent
    let page = await openPage(board.url + 'need', { ready: `typeof roleChip === 'function' && !!cfg.configuration && !!document.querySelector('.deck .card .who')`, width, height });
    await metrics(page); await sleep(400);
    const now = await page.ev(`(() => { const w = [...document.querySelectorAll('.deck .card .who')].filter(w => w.dataset.agent === 'Caller-1'); const c = w[0]?.querySelector('.rolechip');
      return { n: w.length, front: !!w[0]?.closest('.deck-slot.front'), chip: c ? { text: c.textContent, shown: getComputedStyle(c).display !== 'none' } : null, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()`);
    check(`${label}: Now, the card of a configured agent carries the role chip`, now.n > 0 && now.chip && now.chip.text === 'caller', JSON.stringify(now));
    // a card behind the front one is a strip ("a face and a sentence"): it shows no name, so no chip either
    check(`${label}: Now, the chip is ${phone ? 'hidden on a phone (the name stays)' : now.front ? 'visible on the card in front' : 'hidden on a card behind the front one, as its name is'}`, !!now.chip && now.chip.shown === (now.front && !phone), JSON.stringify(now));
    check(`${label}: Now does not scroll sideways`, !now.overflow);
    check(`${label}: no script errors on Now`, page.errors.length === 0, page.errors.join(' | '));
    page.close();

    // the Map: the holder pill on a card in the board's columns
    page = await openPage(board.url + 'need', { ready: `typeof roleChip === 'function' && !!cfg.configuration && !!document.querySelector('#tab-board')`, width, height });
    await metrics(page);
    await page.ev(`(() => { document.getElementById('tab-board').click(); return true; })()`);
    await page.waitFor(`location.pathname === '/' && !!document.querySelector('.col .card .who')`, 8000);
    await sleep(400);
    const map = await page.ev(`(() => { const chip = n => [...document.querySelectorAll('.col .card .who')].filter(w => w.dataset.agent === n).map(w => { const c = w.querySelector('.rolechip'); return c ? { text: c.textContent, shown: getComputedStyle(c).display !== 'none' } : null; });
      return { caller: chip('Caller-1'), other: chip('Someone-Else'), overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()`);
    check(`${label}: Map cards of a configured agent carry the role chip`, map.caller.length > 0 && map.caller.every(c => c && c.text === 'caller' && c.shown === !phone), JSON.stringify(map.caller));
    check(`${label}: Map cards of an agent with no role have no chip`, map.other.length > 0 && map.other.every(c => c === null), JSON.stringify(map.other));
    check(`${label}: the Map does not scroll sideways`, !map.overflow);
    check(`${label}: no script errors on the Map`, page.errors.length === 0, page.errors.join(' | '));
    page.close();

    // Watch: a tile per agent, and the Load strip above it
    page = await openPage(board.url + 'watch', { ready: `typeof roleChip === 'function' && !!cfg.configuration && !!document.querySelector('.w-tile')`, width, height });
    await metrics(page);
    await page.waitFor(`/\\(caller\\)/.test((document.querySelector('.ls-g[data-agent="Caller-1"]') || {}).title || '') && !!document.querySelector('.w-tile .w-tx b .rolechip')`, 10000);   // the strip and the tiles fill in once the HUD answers
    await sleep(300);
    const watch = await page.ev(`(() => { const tile = n => [...document.querySelectorAll('.w-tile .w-tx b')].find(b => b.firstChild && b.firstChild.textContent === n);
      const c = n => tile(n)?.querySelector('.rolechip');
      const g = n => document.querySelector('.ls-g[data-agent="' + n + '"]');
      return { tiles: document.querySelectorAll('.w-tile').length, caller: c('Caller-1') ? { text: c('Caller-1').textContent, shown: getComputedStyle(c('Caller-1')).display !== 'none' } : (tile('Caller-1') ? null : 'no tile'),
               resting: [...document.querySelectorAll('.w-tile.w-idling .w-tx b')].find(b => b.firstChild && b.firstChild.textContent === 'Bills-1')?.querySelector('.rolechip')?.textContent || null,
               other: tile('Someone-Else') ? !!c('Someone-Else') : 'no tile',
               strip: g('Caller-1') ? { title: g('Caller-1').title, chip: !!g('Caller-1').querySelector('.rolechip') } : 'no strip entry', stripOther: g('Someone-Else') ? g('Someone-Else').title : 'no strip entry',
               overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()`);
    check(`${label}: a Watch tile carries the role chip`, watch.caller && watch.caller.text === 'caller' && watch.caller.shown, JSON.stringify(watch.caller));
    check(`${label}: a resting tile (a configured agent with nothing in hand) carries its role too`, watch.resting === 'bills', JSON.stringify(watch.resting));
    check(`${label}: a Watch tile of an agent with no role has none`, watch.other === false || watch.other === 'no tile', JSON.stringify(watch.other));
    // the compact Load strip is a ring and a name (its own rule hides every span in it): the role is in the tooltip, the rows of the Load page carry the chip
    check(`${label}: the Load strip names the role in its tooltip, and stays a ring and a name`, !!watch.strip && /Caller-1 \(caller\)/.test(watch.strip.title) && watch.strip.chip === false, JSON.stringify(watch.strip));
    check(`${label}: the Load strip tooltip of an agent with no role has no role`, typeof watch.stripOther !== 'string' || !/\(/.test(watch.stripOther.split('·')[0]) , JSON.stringify(watch.stripOther));
    check(`${label}: Watch does not scroll sideways`, !watch.overflow);
    check(`${label}: no script errors on Watch`, page.errors.length === 0, page.errors.join(' | '));
    page.close();
  }

  // no configuration applied: no chips, nothing else changes
  board.cli(['configuration', 'clear']);
  const page = await openPage(board.url + 'watch', { ready: `typeof roleChip === 'function' && !!document.querySelector('.w-tile')` });
  await sleep(500);
  const bare = await page.ev(`({ chips: document.querySelectorAll('.rolechip').length, configuration: cfg.configuration || '', roles: Object.keys(cfg.roles || {}).length })`);
  check('with no configuration applied there is no chip anywhere', bare.chips === 0 && bare.configuration === '' && bare.roles === 0, JSON.stringify(bare));
  page.close();
}

main().catch(e => fail('check crashed: ' + (e.stack || e))).finally(async () => { await stopAll(); done('roles check'); });
