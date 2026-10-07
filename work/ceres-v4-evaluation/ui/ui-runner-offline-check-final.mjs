import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync('scripts/eval_v4_ui.mjs', 'utf8');
const parseMatch = source.match(/function parseSse\(text\) \{[\s\S]*?\n\}/);
assert.ok(parseMatch, 'parseSse function found');
const parseSse = new Function(parseMatch[0] + '; return parseSse;')();
assert.deepEqual(parseSse('event: turn.completed\ndata: {"ok":true}\n\n'), [{ type: 'turn.completed', payload: { ok: true } }]);
assert.deepEqual(parseSse('data: {"type":"turn.completed","payload":{"finish_reason":"complete"}}\n\n'), [{ type: 'turn.completed', payload: { finish_reason: 'complete' } }]);
const blocks = [...source.matchAll(/const \[(?:response|openingResponse)\] = await Promise\.all\(\[[\s\S]*?\n\s*\]\);/g)].map(match => match[0]);
assert.equal(blocks.length, 2, 'Both response waiters use Promise.all');
const unhandled = [];
const onUnhandled = reason => unhandled.push(String(reason));
process.on('unhandledRejection', onUnhandled);
for (const expression of blocks) {
  const run = new Function('page', 'action', `return (async () => { try { ${expression}; return { caught: false }; } catch (error) { return { caught: true, message: error.message }; } })();`);
  const waiterFailurePage = { waitForResponse: () => Promise.reject(new Error('waiter failed')), getByRole: () => ({ click: () => Promise.resolve() }) };
  const failedWaiter = await run(waiterFailurePage, () => Promise.resolve());
  assert.equal(failedWaiter.caught, true);
  assert.match(failedWaiter.message, /waiter failed/);
  const actionFailurePage = { waitForResponse: () => new Promise((_, reject) => setTimeout(() => reject(new Error('late waiter failed')), 5)), getByRole: () => ({ click: () => Promise.reject(new Error('action failed')) }) };
  const failedAction = await run(actionFailurePage, () => Promise.reject(new Error('action failed')));
  assert.equal(failedAction.caught, true);
  assert.match(failedAction.message, /action failed/);
  await new Promise(resolve => setTimeout(resolve, 10));
}
process.off('unhandledRejection', onUnhandled);
assert.deepEqual(unhandled, []);
console.log(JSON.stringify({ parser_named_event: 'passed', parser_candidate_payload_event: 'passed', response_waiter_blocks: blocks.length, waiter_and_action_failures_recorded: blocks.length * 2, unhandled_rejections: unhandled.length, network_or_browser: 'none' }, null, 2));
