// Talk it through: an answer lands in the thread of the question (card talk-it-through-bugs). A DOM check in headless Chrome on a throwaway board.
//
//     node tests/qa/talk_check.mjs         (BOARD_CHECK_SRC=<another checkout's src> to see it fail on code without the fix)
//
// The owner asks ORCH about the card in front (the board's own Talk it through box posts exactly this: to ORCH, with the card). ORCH answers the way a
// session does from a shell, with and without the flags that thread a line (--card, --reply-to, --to). Each answer must show in the conversation box on
// the board, under the question, and an answer addressed to the owner must not turn up in another agent's inbox. Lines that are NOT answers (a line to an
// agent, an announcement after the question was answered, a line about another card) must stay out of the thread.
import { openPage, startBoard, stopAll, checker, sleep } from './boardchrome.mjs';

const { check, done, fail } = checker();
const seq = r => { const m = /#(\d+)/.exec(r.out); if (!m) throw new Error('no line number in: ' + r.out.slice(0, 200)); return +m[1]; };

async function main() {
  const board = await startBoard('talk');
  const page = await openPage(board.url, { ready: `typeof talkOpen === 'function' && MEFIRST && !nowWatch && !!deckTop` });
  const { ev, waitFor, errors } = page;
  const C = await ev(`deckTop`);                                  // the card in front on Now: the one Talk it through is about
  const OTHER = await ev(`[...byId.keys()].find(id => id !== deckTop)`);
  board.cli(['chat', 'agents', 'on']);                            // the owner's switch: a line from ORCH to an agent is allowed
  let n = 0;
  const owner = text => seq(board.cli(['chat', 'send', text, '--user', '--to', 'ORCH', '--card', C]));
  const orch = (text, ...flags) => board.cli(['chat', 'send', text, '--name', 'ORCH', ...flags]);
  const loaded = text => waitFor(`chatMsgs.some(m => m.text === ${JSON.stringify(text)})`, 12000);   // the board polls: the line is in the page
  const inThread = text => ev(`talkLines(${JSON.stringify(C)}).some(m => m.text === ${JSON.stringify(text)})`);
  const line = text => ev(`(() => { const m = chatMsgs.find(m => m.text === ${JSON.stringify(text)}); return m ? { seq: m.seq, to: m.to || null, card: m.card || null, reply_to: m.reply_to || null, kind: m.kind } : null; })()`);
  const inbox = name => board.cli(['chat', 'inbox', '--name', name, '--all']).out;
  const ask = async () => { const q = `question ${++n}: what does this card want?`; const s = owner(q); await loaded(q); return { q, s }; };

  await ev(`(() => { talkOpen(${JSON.stringify(C)}); return true; })()`);
  await waitFor(`!!$('talk') && talkCard === ${JSON.stringify(C)}`, 8000);

  // ---- 1. the reported bug: an answer sent with no flags at all ----
  console.log('1: ORCH answers with no flags (agentboard chat send "..." --name ORCH)');
  let { q, s } = await ask();
  const a1 = 'It wants a decision: ship it, or hold it.';
  orch(a1);
  await loaded(a1);
  check('the answer is in the conversation of that card', await inThread(a1), JSON.stringify(await line(a1)));
  const l1 = await line(a1);
  check('it is addressed to the owner, threaded to the question and carries the card', l1 && l1.to && l1.reply_to === s && l1.card === C, JSON.stringify(l1));
  check('the box shows it, and ORCH is no longer "answering"', await waitFor(`$('talk').innerText.includes(${JSON.stringify(a1)}) && !$('talk').querySelector('.think')`, 8000));
  check('it did not go to every agent: it is not in another agent\'s inbox', !inbox('AGENT-2').includes(a1), inbox('AGENT-2').slice(-200));

  // ---- 2. a reply-to but no card ----
  console.log('2: ORCH answers with --reply-to only');
  ({ q, s } = await ask());
  const a2 = 'Answer by reply-to only.';
  orch(a2, '--reply-to', String(s));
  await loaded(a2);
  const l2 = await line(a2);
  check('the card is taken from the question, so the answer is in the conversation', await inThread(a2) && l2 && l2.card === C && l2.reply_to === s, JSON.stringify(l2));

  // ---- 3. a card but no recipient (a broadcast today) ----
  console.log('3: ORCH answers with --card only');
  ({ q, s } = await ask());
  const a3 = 'Answer by card only.';
  orch(a3, '--card', C);
  await loaded(a3);
  const l3 = await line(a3);
  check('it is in the conversation, threaded to the question and addressed to the owner', await inThread(a3) && l3 && l3.reply_to === s && !!l3.to, JSON.stringify(l3));
  check('and it did not go to every agent', !inbox('AGENT-3').includes(a3), inbox('AGENT-3').slice(-200));

  // ---- 4. lines that are not answers stay out ----
  console.log('4: lines that are not answers');
  const a4 = 'Merged, thanks.';   // the question above was answered: this is an announcement
  orch(a4);
  await loaded(a4);
  const l4 = await line(a4);
  check('an announcement after the question was answered stays a plain line: not in the thread, not threaded, still for every agent', !(await inThread(a4)) && l4 && !l4.reply_to && !l4.to && inbox('AGENT-1').includes(a4), JSON.stringify(l4));
  ({ q, s } = await ask());
  const a5 = 'AGENT-1, please rebase.';
  orch(a5, '--to', 'AGENT-1');
  await loaded(a5);
  const l5 = await line(a5);
  check('a line to an agent while a question is open is not an answer: it stays to that agent, unthreaded', !(await inThread(a5)) && l5 && l5.to === 'AGENT-1' && !l5.reply_to, JSON.stringify(l5));
  const a6 = 'About another card.';
  orch(a6, '--card', OTHER);
  await loaded(a6);
  const l6 = await line(a6);
  check('a line about another card while a question is open is not taken for its answer', !(await inThread(a6)) && l6 && l6.card === OTHER && !l6.reply_to, JSON.stringify(l6));
  const a7 = 'Now the real answer.';
  orch(a7);
  await loaded(a7);
  const l7 = await line(a7);
  check('the question was still open: the next plain line from ORCH answers it', await inThread(a7) && l7 && l7.reply_to === s, JSON.stringify(l7));

  check('the page raised no console errors', errors.length === 0, errors.join(' | '));
  page.close();
}

try { await main(); } catch (e) { fail('the check ran: ' + e.message); } finally { await stopAll(); }
done('TALK CHECK');
