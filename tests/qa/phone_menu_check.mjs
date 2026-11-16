// A phone can reach New task, Later, Settings and the theme (sweep-ux): a DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/phone_menu_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// At 700 px and under the header steps back to the three tabs, so its buttons are hidden: until now a phone could not open Settings (and so not the Night switch), the Later drawer,
// the new-task sheet or the theme switch. One Menu button now sits in the header at that width and opens a small sheet with the four. At 390 px: the button is visible, a 44 px target,
// inside the window, and the header stays one row; it opens the sheet (focus on the first item, the four items 44 px tall, in the window); the arrow keys move; Esc closes it and focus
// is back on the button; each item does its thing and closes the sheet; a tap outside closes it. At 1280 px the button is not there. Real key events through the DevTools input domain.
// Prints one ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('phonemenu');
  const page = await openPage(board.url, { width: 390, height: 844, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); localStorage.setItem('agentboard-theme', 'light'); } catch (e) {}`, ready: `typeof applyTheme === 'function' && !!document.getElementById('cfg-btn')` });
  const { send, ev, waitFor, errors } = page;
  const KEYS = { Escape: [27, 'Escape'], ArrowDown: [40, 'ArrowDown'], ArrowUp: [38, 'ArrowUp'], Enter: [13, 'Enter'] };
  const press = async key => { const [vk, code] = KEYS[key]; const base = { key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk }; await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base, text: key === 'Enter' ? '\r' : undefined }); await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base }); await sleep(200); };
  const tap = async (x, y) => { await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 }); await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 }); await sleep(250); };
  const where = () => ev(`document.activeElement.id || document.activeElement.dataset.more || document.activeElement.tagName`);
  const menuOpen = () => ev(`(() => { const m = document.getElementById('more-menu'); return !!m && !m.hidden && getComputedStyle(m).display !== 'none'; })()`);
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await sleep(800);

  console.log('A: the button, at 390 px');
  const btn = await ev(`(() => { const b = document.getElementById('more-btn'); if (!b) return null; const r = b.getBoundingClientRect(); return { shown: getComputedStyle(b).display !== 'none', w: Math.round(r.width), h: Math.round(r.height), right: Math.round(r.right), top: Math.round(r.top), name: b.getAttribute('aria-label') || b.textContent.trim(), haspopup: b.getAttribute('aria-haspopup'), expanded: b.getAttribute('aria-expanded'), headerH: Math.round(document.querySelector('header').getBoundingClientRect().height) }; })()`);
  check('a Menu button is in the header and shown', !!btn && btn.shown, JSON.stringify(btn));
  check('a 44 px target inside the window', !!btn && btn.w >= 44 && btn.h >= 44 && btn.right <= 390, JSON.stringify(btn));
  check('named, and says it opens a menu, closed', !!btn && /menu/i.test(btn.name) && btn.haspopup === 'menu' && btn.expanded === 'false', JSON.stringify(btn));
  check('the header is still one row', !!btn && btn.headerH < 90, JSON.stringify(btn));
  check('the sheet is closed to begin with', !(await menuOpen()));

  console.log('B: opening it');
  await ev(`(document.getElementById('more-btn').focus(), 1)`); await press('Enter');
  check('Enter on the button opens the sheet', await waitFor(`!document.getElementById('more-menu').hidden`, 3000));
  check('the button says it is expanded', await ev(`document.getElementById('more-btn').getAttribute('aria-expanded') === 'true'`));
  const items = await ev(`[...document.querySelectorAll('#more-menu [role="menuitem"]')].map(b => { const r = b.getBoundingClientRect(); return { t: b.textContent.trim().replace(/\\s+/g, ' '), h: Math.round(r.height), left: Math.round(r.left), right: Math.round(r.right) }; })`);
  check('four items: New task, Later, Settings, Theme', items.length === 4 && /^New task/.test(items[0].t) && /^Later/.test(items[1].t) && /^Settings/.test(items[2].t) && /^Theme/.test(items[3].t), JSON.stringify(items));
  check('each is 44 px tall and inside the window', items.every(i => i.h >= 44 && i.left >= 0 && i.right <= 390), JSON.stringify(items));
  check('the Later item carries the count the header would have shown', items.length > 1 && /\(\d+\)/.test(items[1].t), items[1] && items[1].t);
  check('the first item has focus', await waitFor(`document.activeElement.dataset.more === 'new'`, 3000), await where());
  await press('ArrowDown');
  check('ArrowDown moves to the next item', await ev(`document.activeElement.dataset.more === 'later'`), await where());
  await press('ArrowUp'); await press('ArrowUp');
  check('ArrowUp from the first goes round to the last', await ev(`document.activeElement.dataset.more === 'theme'`), await where());
  await press('Escape');
  check('Esc closes it and focus is back on the Menu button', await waitFor(`document.getElementById('more-menu').hidden && document.activeElement.id === 'more-btn'`, 3000), await where());

  console.log('C: each item');
  const openMenu = async () => { await ev(`(document.getElementById('more-btn').click(), 1)`); await waitFor(`!document.getElementById('more-menu').hidden`, 3000); };
  await openMenu(); await ev(`(document.querySelector('#more-menu [data-more="new"]').click(), 1)`);
  check('New task opens the sheet with its field focused, and closes the menu', await waitFor(`document.getElementById('add').classList.contains('open') && document.activeElement.id === 'title'`, 3000) && !(await menuOpen()), await where());
  await press('Escape'); await ev(`(document.activeElement.blur(), 1)`);
  await openMenu(); await ev(`(document.querySelector('#more-menu [data-more="later"]').click(), 1)`);
  check('Later opens the drawer, and closes the menu', await waitFor(`document.getElementById('later').classList.contains('open')`, 3000) && !(await menuOpen()));
  await ev(`(document.getElementById('later-close').click(), 1)`); await sleep(400);
  await openMenu(); await ev(`(document.querySelector('#more-menu [data-more="settings"]').click(), 1)`);
  check('Settings opens the sheet (and the Night switch with it), and closes the menu', await waitFor(`document.getElementById('mix').classList.contains('on')`, 3000) && !(await menuOpen()));
  check('and the Night queue row is there to use', await waitFor(`!!document.querySelector('#cfg-night .mix-row')`, 8000) || await ev(`(toggleMix(true, 'agents'), 1)`) && await waitFor(`!!document.querySelector('#cfg-night .mix-row')`, 8000));
  await ev(`(toggleMix(false), 1)`); await sleep(300);
  const before = await ev(`document.documentElement.getAttribute('data-theme') || 'auto'`);
  await openMenu(); await ev(`(document.querySelector('#more-menu [data-more="theme"]').click(), 1)`);
  check('Theme switches the theme, and closes the menu', await waitFor(`(document.documentElement.getAttribute('data-theme') || 'auto') !== ${JSON.stringify(before)}`, 3000) && !(await menuOpen()), before + ' -> ' + await ev(`document.documentElement.getAttribute('data-theme') || 'auto'`));

  console.log('D: a tap outside, and the wide window');
  await openMenu(); await tap(40, 600);
  check('a tap outside the sheet closes it', !(await menuOpen()));
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await sleep(500);
  check('at 1280 px there is no Menu button', await ev(`getComputedStyle(document.getElementById('more-btn')).display === 'none' && document.getElementById('more-menu').hidden`));
  check('no script errors on the page', errors.length === 0, errors.join(' | '));
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('PHONE MENU'); });
