// The owner can delete a card that nobody has started (card fix-delete-todo-later-cards): the panel's Delete button used to sit inside the closed "More" fold for every card
// that was not done or in review, so a Todo or Later card showed no way to delete it. A DOM check in headless Chrome on a throwaway board (made-up cards), wide and phone width:
// for a Later card (opened from the Later drawer), a Todo card and a Doing card, Delete is on the panel with "More" closed, is the element under its own centre (nothing covers it),
// the first click only arms it, the second deletes the card from the board, and the panel does not scroll sideways.
//
//     node tests/qa/delete_cards_check.mjs          (BOARD_CHECK_SRC=<another checkout's src> runs it against that code)
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();

async function main() {
  const board = await startBoard('delete');
  const listed = () => board.cli(['list']).out;
  const seed = () => {   // three made-up cards: Later (`add` puts a card there), Todo, and one an agent holds (Doing)
    const mk = title => (/added (\S+)/.exec(board.cli(['add', title]).out) || [])[1];
    const ids = { later: mk('Later card to delete'), todo: mk('Todo card to delete') };
    board.cli(['move', ids.todo, 'todo']);
    ids.doing = board.cli(['start', 'Doing card to delete', '--name', 'Ada']).out.trim().split('\n')[0].trim();
    return ids;
  };

  for (const [label, width, height] of [['wide', 1280, 800], ['narrow', 390, 800]]) {
    console.log(`${label} (${width}px)`);
    const ids = seed();
    check(`${label}: three cards were made, and the board lists them`, Object.values(ids).every(id => id && new RegExp('\\b' + id + '\\b').test(listed())), JSON.stringify(ids));
    const page = await openPage(board.url + 'need', { ready: `typeof openPanel === 'function' && !!document.querySelector('#tab-board')`, width, height });
    await page.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 700 }); await sleep(300);
    const { ev, waitFor } = page;
    await ev(`(() => { document.getElementById('tab-board').click(); return true; })()`);   // Now is the home page; the Todo and Doing columns are on the Map
    await waitFor(`location.pathname === '/' && !!document.querySelector('.col .card')`, 10000);
    for (const key of ['later', 'todo', 'doing']) {
      const id = ids[key];
      if (key === 'later') {   // the way it is reached by hand: the Later drawer, then the card
        await ev(`(() => { document.getElementById('later-btn').click(); return true; })()`);
        await waitFor(`!!document.querySelector('#later-list .card[data-id="${id}"]')`, 8000);
        await ev(`document.querySelector('#later-list .card[data-id="${id}"]').click()`);
      } else {
        const there = await waitFor(`!!document.querySelector('.col .card[data-id="${id}"]')`, 8000);
        if (!there) console.log('   no card on the board:', id, JSON.stringify(await ev(`({ n: document.querySelectorAll('.col .card').length, ids: [...document.querySelectorAll('.col .card')].map(c => c.dataset.id).slice(-8), t: tasks.filter(t => /delete/.test(t.id)).map(t => t.id + ':' + t.status) })`)));
        await ev(`document.querySelector('.col .card[data-id="${id}"]').click()`);
      }
      await waitFor(`typeof openId !== 'undefined' && openId === '${id}' && !!document.getElementById('p-del')`, 8000);
      await sleep(400);
      const s = await ev(`(() => { const d = document.getElementById('p-del'); if (!d) return { has: false };
        d.scrollIntoView({ block: 'center' }); const r = d.getBoundingClientRect(), at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        const fold = document.querySelector('.p-fold'); const panel = document.getElementById('panel') || d.closest('aside, .panel');
        return { has: true, shown: d.checkVisibility(), covered: at !== d && !d.contains(at), inFold: !!d.closest('details.p-fold'), foldOpen: fold ? fold.open : false,
          inView: r.left >= 0 && r.right <= innerWidth, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()`);
      check(`${label}: a ${key} card shows Delete with "More" closed`, s.has && s.shown && !s.inFold && !s.foldOpen, JSON.stringify(s));
      check(`${label}: a ${key} card's Delete is not covered, and is on the screen`, s.has && !s.covered && s.inView, JSON.stringify(s));
      check(`${label}: the panel of a ${key} card does not scroll sideways`, !s.overflow, JSON.stringify(s));
      const first = await ev(`(() => { const d = document.getElementById('p-del'); d.click(); return { text: d.textContent, armed: !!d.dataset.armed }; })()`);
      check(`${label}: the first click on a ${key} card only arms Delete`, first.armed && /again/i.test(first.text) && new RegExp('\\b' + id + '\\b').test(listed()), JSON.stringify(first));
      await ev(`document.getElementById('p-del').click()`);
      await waitFor(`!byId.get('${id}')`, 8000);
      await sleep(300);
      const still = new RegExp('\\b' + id + '\\b').test(listed()), inPage = await ev(`!!byId.get('${id}') || tasks.some(t => t.id === '${id}') || !!document.querySelector('.col .card[data-id="${id}"]')`), dbg = await ev(`({ byId: !!byId.get('${id}'), dom: [...document.querySelectorAll('.card[data-id="${id}"]')].map(c => c.closest('[id]')?.id), inTasks: tasks.some(t => t.id === '${id}'), openId, laterOpen: document.getElementById('later').classList.contains('open'), n: tasks.length })`);
      check(`${label}: the second click deletes the ${key} card`, !still && !inPage, `still on the board: ${still}, still on the page: ${inPage}, error: ${await ev(`document.getElementById('err') ? document.getElementById('err').textContent : ''`)}`);
      if (key === 'later') await ev(`(() => { if (document.getElementById('later').classList.contains('open')) document.getElementById('later-btn').click(); return true; })()`);
      await sleep(200);
    }
    check(`${label}: no script errors`, page.errors.length === 0, page.errors.join(' | '));
    page.close();
  }
}

main().catch(e => fail('check crashed: ' + (e.stack || e))).finally(async () => { await stopAll(); done('delete check'); });
