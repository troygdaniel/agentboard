// The approval card for an action outside the board (card agent-config-slice-2): in the agent's thread (where its lines to you are), an outside proposal shows what it is, to whom, the exact words, the money and what is
// shared, with "Approve this action" and "Not now"; a plain proposal is as it was; a lapsed one shows no buttons; one yes decides that one action; a click after the 30 minutes is refused by
// the board and records nothing. A DOM check in headless Chrome on a throwaway board (made-up names and a fictional 555 number), wide and narrow.
//
//     node tests/qa/approval_check.mjs         (BOARD_CHECK_SRC=<another checkout's src> runs it against that code)
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const past = () => { const d = new Date(Date.now() - 120000), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
const expire = (board, seq) => { const f = join(board.dir, 'tasks.json'); const d = JSON.parse(readFileSync(f, 'utf8')); for (const m of d.chat) if (m.seq === seq) m.action.expires_at = past(); writeFileSync(f, JSON.stringify(d, null, 2)); };

async function main() {
  const board = await startBoard('approval');
  const send = (text, ...flags) => { const r = board.cli(['chat', 'send', text, '--name', 'Caller-1', ...flags]); const m = /#(\d+)/.exec(r.out); if (r.status !== 0 || !m) throw new Error('send failed: ' + r.out.slice(0, 300)); return +m[1]; };
  const out = ['--outside', '--target', '416-555-0100', '--say', 'A table for two on Friday at seven, first name only', '--money', 'none', '--shares', 'first name only'];
  const sOut = send('Need your word to call the restaurant', '--propose', 'Call the restaurant to book a table for two', ...out);
  const sPlain = send('Ok to rename the draft?', '--to', 'you', '--propose', 'Rename the draft file');
  const sOld = send('Need your word to send the message', '--propose', 'Send the booking message', ...out);
  const sLate = send('Need your word to pay the deposit', '--propose', 'Pay the deposit', '--outside', '--target', 'the restaurant', '--say', 'the deposit amount', '--money', '25 dollars', '--shares', 'a card number');
  expire(board, sOld);

  // narrow first: the wide pass decides proposals, which changes what the board shows
  for (const [label, width, height] of [['narrow', 390, 800], ['wide', 1280, 800]]) {
    console.log(`${label} (${width}px)`);
    const page = await openPage(board.url + 'need', { ready: `typeof openThread === 'function' && typeof chatMsgs !== 'undefined' && chatMsgs.length >= 4`, width, height });
    await page.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 700 });
    await page.ev(`(() => { openThread('Caller-1'); return true; })()`);
    await page.waitFor(`document.querySelectorAll('#thread .cmsg-act').length >= 4`, 10000);
    const info = await page.ev(`(() => { const bub = seq => [...document.querySelectorAll('#thread .cmsg')].find(c => c.innerHTML.includes('data-seq="' + seq + '"') || c.dataset.seq == seq) || null;
      const all = [...document.querySelectorAll('#thread .cmsg-act')].map(a => ({ cls: a.className, lab: a.querySelector('.lab')?.textContent, outs: [...a.querySelectorAll('.outs dd')].map(d => d.textContent), btns: [...a.querySelectorAll('.acts .btn')].map(b => b.textContent), until: a.querySelector('.until')?.textContent || null, text: a.textContent }));
      return { all, overflow: document.getElementById('thread').scrollWidth > document.getElementById('thread').clientWidth + 1 }; })()`);
    const find = frag => info.all.find(a => a.text.includes(frag));
    const o = find('Call the restaurant'), p = find('Rename the draft'), l = find('Send the booking message');
    check(`${label}: an outside proposal says it needs your word and that nothing has been done`, o && o.lab === 'Needs your word · nothing has been done', JSON.stringify(o));
    check(`${label}: it states who, the words, the money and what is shared`, o && o.outs.join('|') === '416-555-0100|A table for two on Friday at seven, first name only|none|first name only', JSON.stringify(o?.outs));
    check(`${label}: it offers Approve this action and Not now, and says it lapses`, o && o.btns.join('|') === 'Approve this action|Not now' && /this action only · lapses \d\d:\d\d/.test(o.until || ''), JSON.stringify(o));
    check(`${label}: a plain proposal is as it was (Approve, Decline, no fields)`, p && p.lab === 'Proposes · needs your OK' && p.btns.join('|') === 'Approve|Decline' && p.outs.length === 0 && !p.until, JSON.stringify(p));
    check(`${label}: a lapsed one has no buttons and says to ask again`, l && /lapsed/.test(l.cls) && l.lab === 'Lapsed · ask again' && l.btns.length === 0, JSON.stringify(l));
    check(`${label}: the thread does not scroll sideways`, !info.overflow);

    if (label === 'wide') {
      // one yes decides one action
      await page.ev(`(() => { document.querySelector('#thread [data-decide="approved"][data-seq="${sOut}"]').click(); return true; })()`);
      const ok = await page.waitFor(`!!document.querySelector('#thread .cmsg-act.approved')`, 10000);
      if (!ok) console.log('   page error: ' + await page.ev(`(document.getElementById('error-text') || {}).textContent || '(none)'`));
      check('wide: Approve this action records the yes for that action', ok && /approved/.test(board.cli(['chat', 'approvals']).out.split('\n').find(x => x.startsWith('#' + sOut)) || ''), board.cli(['chat', 'approvals']).out.slice(0, 300));
      const rest = board.cli(['chat', 'approvals']).out;
      check('wide: the other proposals still wait for their own word', new RegExp('#' + sPlain + '\\s+proposed').test(rest) && new RegExp('#' + sLate + '\\s+proposed').test(rest), rest.slice(0, 500));
      // a click after the 30 minutes: the board refuses, nothing is recorded
      expire(board, sLate);
      await page.ev(`(() => { document.querySelector('#thread [data-decide="approved"][data-seq="${sLate}"]').click(); return true; })()`);
      await sleep(1500);
      const late = board.cli(['chat', 'approvals']).out;
      check('wide: an Approve after the 30 minutes is refused and records nothing', new RegExp('#' + sLate + '\\s+lapsed').test(late), late.slice(0, 500));
      const err = await page.ev(`(document.getElementById('error-text') || {}).textContent || ''`);
      check('wide: the page says why', /lapsed/.test(err), err);
    }
    check(`${label}: no script errors`, page.errors.length === 0, page.errors.join(' | '));
    page.close();
  }
}

main().catch(e => fail('check crashed: ' + (e.stack || e))).finally(async () => { await stopAll(); done('approval check'); });
