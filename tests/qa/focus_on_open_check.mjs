// Focus moves into a layer when it opens, and back to what opened it when it closes (sweep-ux): a DOM check in headless Chrome against a throwaway board.
//
//     node tests/qa/focus_on_open_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// The Later drawer (its "Park an idea" field), Settings (the selected tab, still there after the Security and Backup tabs have been read in) and the Keys sheet (its
// Close button): after each opens, document.activeElement is inside it; Esc closes it and focus is back on the button that opened it. A keyboard user used to
// land on the page behind the layer (the Later field was asked for while the drawer was still hidden, Settings lost its tab when the tab list was redrawn, Keys
// never asked). Real key events through the DevTools input domain. One ok/FAIL line per check; exit code 1 on a FAIL.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('focus');
  const page = await openPage(board.url, { width: 1280, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`, ready: `typeof toggleMix === 'function' && !!document.getElementById('later-btn')` });
  const { send, ev, waitFor, errors } = page;
  const KEYS = { Escape: [27, 'Escape'], '?': [191, 'Slash'], l: [76, 'KeyL'], Enter: [13, 'Enter'] };
  // Enter carries its character ('\r'), or the browser does not activate a focused button
  const press = async key => { const [vk, code] = KEYS[key] || [key.toUpperCase().charCodeAt(0), 'Key' + key.toUpperCase()]; const base = { key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk }; await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base, text: key === 'Enter' ? '\r' : key.length === 1 ? key : undefined }); await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base }); await sleep(150); };
  const where = () => ev(`(() => { const a = document.activeElement; return (a.id || a.tagName.toLowerCase()) + (a.getAttribute('aria-selected') ? '[selected=' + a.getAttribute('aria-selected') + ']' : ''); })()`);
  const blur = () => ev(`(document.activeElement.blur(), 1)`);

  console.log('A: the Later drawer');
  await blur();
  await ev(`(document.getElementById('later-btn').focus(), 1)`); await press('Enter');
  check('opened with the button: focus is in the "Park an idea" field', await waitFor(`document.activeElement.id === 'later-input'`, 3000), await where());
  await press('Escape');
  check('the first Esc leaves the field and keeps the drawer open', await ev(`document.getElementById('later').classList.contains('open') && document.activeElement.id !== 'later-input'`), await where());
  await press('Escape');
  check('the next Esc closes it and focus is back on the Later button', await waitFor(`!document.getElementById('later').classList.contains('open') && document.activeElement.id === 'later-btn'`, 3000), await where());
  await blur(); await press('l');
  check('opened with the l key: focus is in the field', await waitFor(`document.activeElement.id === 'later-input'`, 3000), await where());
  await press('Escape'); await press('Escape'); await blur();

  console.log('B: Settings');
  await ev(`(document.getElementById('cfg-btn').focus(), 1)`); await press('Enter');
  check('opened with the button: the selected tab has focus', await waitFor(`document.activeElement.getAttribute('role') === 'tab' && document.activeElement.getAttribute('aria-selected') === 'true' && !!document.activeElement.closest('#mix')`, 3000), await where());
  await sleep(1500);   // the Security and Backup tabs are drawn once the board's settings have been read: the tab list is redrawn
  check('and still has it once every tab has been drawn', await ev(`!!document.getElementById('stab-security') && document.activeElement.getAttribute('role') === 'tab' && !!document.activeElement.closest('#mix')`), await where());
  await press('Escape');
  check('Esc closes it and focus is back on the Settings button', await waitFor(`!document.getElementById('mix').classList.contains('on') && document.activeElement.id === 'cfg-btn'`, 3000), await where());

  console.log('C: the Keys sheet');
  await blur(); await press('?');
  check('opened with the ? key: the Close button has focus', await waitFor(`document.getElementById('keys').classList.contains('on') && document.activeElement.id === 'keys-close'`, 3000), await where());
  await press('Escape');
  check('Esc closes it', await waitFor(`!document.getElementById('keys').classList.contains('on')`, 3000));
  await ev(`(document.getElementById('help-btn').focus(), 1)`); await press('Enter');
  check('opened with the Help button: the Close button has focus', await waitFor(`document.activeElement.id === 'keys-close'`, 3000), await where());
  await press('Enter');
  check('Enter on Close closes it and focus is back on the Help button', await waitFor(`!document.getElementById('keys').classList.contains('on') && document.activeElement.id === 'help-btn'`, 3000), await where());
  check('no script errors on the page', errors.length === 0, errors.join(' | '));
}

main().catch(e => fail('the check itself broke: ' + (e && e.stack || e))).finally(async () => { await stopAll(); done('FOCUS ON OPEN'); });
