import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const repoRoot = process.env.CERES_NEXT_06_ROOT;
if (!repoRoot) throw new Error('CERES_NEXT_06_ROOT must point to the frozen 06 worktree');
const frontendRoot = path.join(repoRoot, 'frontend');
const requireFromFrontend = createRequire(pathToFileURL(path.join(frontendRoot, 'package.json')));
const { createServer } = await import(pathToFileURL(requireFromFrontend.resolve('vite')).href);
const { chromium } = createRequire(import.meta.url)(
  'C:/Users/20616/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright',
);

const order = {
  order_id: 'ord-ui-probe-06',
  status: 'paid',
  created_at: '2026-10-06T10:00:00Z',
  total_fen: 1290,
  items: [{
    product_id: 'prod-eggs-probe',
    product_name: '鲜鸡蛋 6枚装',
    sku_id: 'sku-eggs-probe',
    quantity: 1,
    unit_price_fen: 1290,
    line_total_fen: 1290,
  }],
};
const captured = { orderSelections: [], turns: [], promptDisplays: [], switches: [], unexpected: [] };
const opening = (role = 'momo', promptDisplayed = false) => ({
  opening_id: 'opening-probe-06',
  guide_session_id: 'guide-probe-06',
  mercury_session_id: 'mercury-probe-06',
  role,
  prompt_displayed: promptDisplayed,
  handoff_id: 'handoff-parent-probe-06',
});
const server = await createServer({
  root: frontendRoot,
  configFile: path.join(frontendRoot, 'vite.config.ts'),
  server: { host: '127.0.0.1', port: 18446, strictPort: true },
});
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 430, height: 900 } });
  await context.addInitScript(() => {
    sessionStorage.setItem('ceres-langgraph-guide-session-id', 'guide-probe-06');
    sessionStorage.setItem('ceres-mercury-session-id', 'mercury-probe-06');
    sessionStorage.setItem('ceres-v3-opening-id', 'opening-probe-06');
  });
  await context.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathName = url.pathname;
    const json = (body) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
    const sse = (body) => route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
      body,
    });

    if (pathName === '/api/v1/bootstrap') {
      await json({ owner_id: 'owner-probe-06', store_id: 'store-demo-01', delivery_zone_id: 'zone-default', llm_mode: 'mock', business_data_mode: 'demo' });
      return;
    }
    if (pathName === '/api/v1/cart') {
      await json({ version: 0, items: [], total_price_fen: 0, business_data_mode: 'demo' });
      return;
    }
    if (pathName === '/api/v1/orders') {
      await json({ items: [order] });
      return;
    }
    if (pathName === '/api/v1/guide/sessions/guide-probe-06') {
      await json({ session_id: 'guide-probe-06', task_id: null, state_version: 0, session_version: 0, plan: null, available_actions: [], pending_clarifications: [], messages: [] });
      return;
    }
    if (pathName === '/api/v1/chat/openings/opening-probe-06' && request.method() === 'GET') {
      await json(opening(captured.switches.length ? 'keke' : 'momo', captured.promptDisplays.length > 0));
      return;
    }
    if (pathName === '/api/v1/mercury/sessions/mercury-probe-06/order' && request.method() === 'POST') {
      const body = request.postDataJSON();
      captured.orderSelections.push(body);
      await json({ session_id: 'mercury-probe-06', order });
      return;
    }
    if (pathName === '/api/v1/chat/openings/opening-probe-06/turns/stream' && request.method() === 'POST') {
      captured.turns.push(request.postDataJSON());
      await sse(
        `event: service.route\ndata: ${JSON.stringify({ decision: 'suggest_switch', status: 'ready', current_role: 'momo', target_role: 'keke', handoff_id: 'handoff-child-probe-06', prompt_mode: 'automatic' })}\n\n` +
        `event: turn.completed\ndata: ${JSON.stringify({ business_not_run: true, message: '退款申请已提交，可可可以接着帮你。如需继续选购，请点“继续选购”。' })}\n\n`,
      );
      return;
    }
    if (pathName === '/api/v1/chat/openings/opening-probe-06/prompt-displayed' && request.method() === 'POST') {
      captured.promptDisplays.push(request.postDataJSON());
      await json(opening('momo', true));
      return;
    }
    if (pathName === '/api/v1/chat/openings/opening-probe-06/switches/stream' && request.method() === 'POST') {
      captured.switches.push(request.postDataJSON());
      await sse(
        `event: service.switch\ndata: ${JSON.stringify({ accepted: true, target_role: 'keke', handoff_id: 'handoff-child-probe-06' })}\n\n` +
        `event: answer.delta\ndata: ${JSON.stringify({ type: 'answer.delta', protocol_version: 1, payload: { text: '我已接着帮你选购。' } })}\n\n` +
        `event: turn.completed\ndata: ${JSON.stringify({ type: 'turn.completed', protocol_version: 1, payload: { status: 'completed', message: '我已接着帮你选购。' } })}\n\n`,
      );
      return;
    }
    captured.unexpected.push(`${request.method()} ${pathName}`);
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'UNEXPECTED_PROBE_REQUEST' } }) });
  });

  const page = await context.newPage();
  await page.goto('http://127.0.0.1:18446/');
  await page.getByRole('button', { name: '订单' }).click();
  await page.getByRole('button', { name: '问问墨墨' }).click();
  await page.getByRole('button', { name: '📦 查订单' }).waitFor({ state: 'visible' });
  await page.getByRole('button', { name: '📦 查订单' }).click();
  await page.getByRole('button', { name: /ord-ui-probe-06/ }).waitFor({ state: 'visible' });
  await page.getByRole('button', { name: /ord-ui-probe-06/ }).click();
  await page.getByText('当前咨询订单：').waitFor({ state: 'visible' });
  assert.deepEqual(captured.orderSelections, [{ order_id: 'ord-ui-probe-06' }], 'the order picker must select the displayed owned order');

  const promptDisplayedRequest = page.waitForRequest((req) => new URL(req.url()).pathname.endsWith('/prompt-displayed'));
  await page.getByPlaceholder('问问墨墨吧…').fill('先为这笔订单申请退款，然后继续帮我买一瓶可乐。');
  await page.getByPlaceholder('问问墨墨吧…').press('Enter');
  const displayed = await promptDisplayedRequest;
  await page.getByRole('button', { name: '继续选购' }).waitFor({ state: 'visible' });
  assert.equal(captured.turns.length, 1, 'Momo must receive the selected order turn');
  assert.equal(captured.turns[0].order_id, 'ord-ui-probe-06', 'the Momo request must carry the selected order');
  assert.deepEqual(JSON.parse(displayed.postData()), { handoff_id: 'handoff-child-probe-06' }, 'automatic display acknowledgement must identify the child continuation');
  assert.equal(captured.switches.length, 0, 'continuation must wait for the user button click');

  const acceptedSwitchRequest = page.waitForRequest((req) => new URL(req.url()).pathname.endsWith('/switches/stream'));
  await page.getByRole('button', { name: '继续选购' }).click();
  const acceptedRequest = await acceptedSwitchRequest;
  assert.deepEqual(JSON.parse(acceptedRequest.postData()), { accept: true, target_role: 'keke', handoff_id: 'handoff-child-probe-06' }, 'the explicit UI choice must accept the same child continuation');
  assert.deepEqual(captured.switches, [{ accept: true, target_role: 'keke', handoff_id: 'handoff-child-probe-06' }], 'the switch must reach the public API');
  assert.deepEqual(captured.unexpected, [], 'the flow must use only the stubbed public API calls');
  console.log('UI after-sales continuation probe passed');
} finally {
  if (browser) await browser.close();
  await server.close();
}

