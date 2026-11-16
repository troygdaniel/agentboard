// The pile's two-step Space (sweep2-bugs): Space arms the front card's first answer and lights its button; a redraw that lands in the
// three-second window (a poll that brings another card's change) must keep both the arm and the light, so the second Space sends what the
// screen says it will. A DOM check in headless Chrome against a throwaway board, never the live one.
//
//     node tests/qa/deck_arm_check.mjs            (python3 and Google Chrome on this Mac; PYTHON=... and CHROME=... override them)
//
// One ok/FAIL line per check; exit code 1 on a FAIL. BOARD_CHECK_SRC=<another checkout's src> runs it against that code.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('deckarm');
  const page = await openPage(board.url + 'need', { width: 1280, height: 900, init: `try { localStorage.setItem('ab-greeted', new Date().toDateString()); } catch (e) {}`,
    ready: `typeof deckHtml === 'function' && Array.isArray(deckIds) && deckIds.length > 0` });
  const { send, ev, waitFor, errors } = page;
  const space = async () => { await send('Input.dispatchKeyEvent', { type: 'keyDown', key: ' ', code: 'Space', text: ' ', unmodifiedText: ' ', windowsVirtualKeyCode: 32 }); await send('Input.dispatchKeyEvent', { type: 'keyUp', key: ' ', code: 'Space', windowsVirtualKeyCode: 32 }); };
  const lit = () => ev(`!!document.querySelector('.deck-slot.front .deck-armed') && !!document.querySelector('.deck-head .armed')`);

  console.log('A: Space arms the first answer of a card that asks');
  const id = await ev(`deckIds.find(i => dkKind(byId.get(i)) === 0) || null`);
  check('the seeded pile holds a card that asks', !!id, String(id));
  if (!id) { fail('no card to arm'); return; }
  await ev(`(deckGo(${JSON.stringify(id)}), 1)`);
  check('it comes to the front', await waitFor(`deckTop === ${JSON.stringify(id)} && !!document.querySelector('.deck-slot.front[data-slot=${JSON.stringify(id)}]')`, 5000));
  await sleep(300);
  await space(); await sleep(200);
  check('the arm is set and its button is lit', (await ev(`deckArm`)) === id && await lit(), await ev(`[deckArm, !!document.querySelector('.deck-slot.front .deck-armed'), !!document.querySelector('.deck-head .armed')]`));

  console.log('B: a redraw inside the window keeps the arm and the light');
  const r = board.cli(['add', 'Redraw bait', '--status', 'todo']);
  check('a card is added from outside', r.status === 0, r.out);
  check('the page sees it (a poll redrew the board)', await waitFor(`tasks.some(t => t.title === 'Redraw bait')`, 6000));
  await sleep(400);
  const after = await ev(`[deckArm, deckTop, !!document.querySelector('.deck-slot.front .deck-armed'), !!document.querySelector('.deck-head .armed')]`);
  check('the arm is still live on the same card', after[0] === id && after[1] === id, after.join(','));
  check('its button is still lit after the redraw', after[2] && after[3], after.join(','));

  console.log('C: the second Space sends what the screen says');
  await space();
  check('Go ahead is stored as the reply', await waitFor(`((byId.get(${JSON.stringify(id)}) || {}).reply || {}).text === 'Go ahead'`, 6000), JSON.stringify(await ev(`(byId.get(${JSON.stringify(id)}) || {}).reply || null`)));
  check('the card leaves the pile', await waitFor(`!deckIds.includes(${JSON.stringify(id)})`, 6000));
  check('nothing stays lit', !(await ev(`!!document.querySelector('.deck-armed')`)) && (await ev(`deckArm`)) === null);

  console.log('D: an arm left alone goes out after three seconds');
  const id2 = await ev(`deckIds.find(i => dkKind(byId.get(i)) < 2) || null`);
  if (id2) {
    await ev(`(deckGo(${JSON.stringify(id2)}), 1)`); await waitFor(`deckTop === ${JSON.stringify(id2)}`, 5000); await sleep(300);
    await space(); await sleep(200);
    check('armed', (await ev(`deckArm`)) === id2);
    check('disarmed on its own', await waitFor(`deckArm === null && !document.querySelector('.deck-armed')`, 5000));
  }
  check('no page errors', errors.length === 0, errors.join(' | '));
  page.close();
}

try { await main(); } catch (e) { fail('check crashed: ' + (e && e.message || e)); }
await stopAll();
done('deck arm');
