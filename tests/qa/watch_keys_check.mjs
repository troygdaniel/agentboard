// Watch with the keyboard only (sweep2-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/watch_keys_check.mjs             (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// A Watch tile can be reached with Tab (it has tabindex 0), but only the arrow keys and a click told the page which tile was "selected", and Enter opens the selected one. So a tile
// reached with Tab did nothing on Enter: the Now pile's own key handler (it runs on Watch too) took the key, called deckDetails(), and threw "Cannot set properties of null
// (setting 'textContent')" on the Watch, which has no Details button, after it had already cancelled the key; it also flipped the pile's saved Details setting. Now a tile that takes focus is
// the selected one, and the pile's handler leaves the Watch alone. Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done } = checker();
const KEYS = { Tab: [9, 'Tab'], Escape: [27, 'Escape'], Enter: [13, 'Enter'] };

async function main() {
  const board = await startBoard('watchkeys');
  const page = await openPage(board.url + 'watch', { width: 1440, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.querySelector('.w-page.cur .w-nav')` });
  const { send, ev, errors } = page;
  const press = async key => { const [vk, code] = KEYS[key]; const base = { key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk }; await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base }); await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base }); await sleep(150); };
  await sleep(1500);
  const setting = () => ev(`(() => { try { return localStorage.getItem('ab-deck-details'); } catch (e) { return 'n/a'; } })()`);
  const onTile = () => ev(`(() => { const e = document.activeElement; return e && e.matches('.w-nav') ? e.dataset.wid : null; })()`);
  const tabToATile = async () => { for (let i = 0; i < 40; i++) { await press('Tab'); const t = await onTile(); if (t) return t; } return null; };

  console.log('A: a tile reached with Tab opens on Enter and closes on Esc');
  const before = await setting();
  const first = await tabToATile();
  check('Tab reaches a Watch tile', !!first, 'no tile in 40 Tabs');
  check('the tile that took focus is the selected one', (await ev(`watchSel`)) === first, `watchSel ${await ev('watchSel')} vs ${first}`);
  await press('Enter'); await sleep(900);
  check('Enter opens that tile\'s details', await ev(`!!document.querySelector('.w-focus')`));
  check('and they are that tile\'s', (await ev(`watchOpenId`)) === first, `${await ev('watchOpenId')} vs ${first}`);
  check('no exception was thrown', errors.length === 0, errors.join(' | '));
  check('the pile\'s saved Details setting is not changed by a key on the Watch', (await setting()) === before, `${before} -> ${await setting()}`);
  await press('Escape'); await sleep(1100);
  check('Esc closes the details', await ev(`!document.querySelector('.w-focus')`));
  check('focus is back on a tile, not lost to the page', !!(await onTile()), 'focus on ' + await ev(`document.activeElement && document.activeElement.tagName`));

  console.log('B: the next tile with Tab, then Enter');
  const second = await tabToATile();
  check('Tab reaches another tile', !!second && second !== first, `${first} then ${second}`);
  await press('Enter'); await sleep(900);
  check('Enter opens the second tile\'s details', !!second && (await ev(`!!document.querySelector('.w-focus')`)) && (await ev(`watchOpenId`)) === second, `${await ev('watchOpenId')} vs ${second}`);
  await press('Escape'); await sleep(1100);
  check('Esc closes them again', await ev(`!document.querySelector('.w-focus')`));
  check('no exception was thrown through all of it', errors.length === 0, errors.join(' | '));

  page.close();
  await stopAll();
  done('watch_keys_check');
}
main().catch(e => { console.error(e); stopAll().finally(() => process.exit(1)); });
