import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const probeDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(probeDir, '../../..');
const frontendRoot = path.join(repoRoot, 'frontend');
const requireFromFrontend = createRequire(pathToFileURL(path.join(frontendRoot, 'package.json')));
const { createServer } = await import(pathToFileURL(requireFromFrontend.resolve('vite')).href);
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(
    path.resolve(repoRoot, '..', '..'),
    'work',
    'ceres-next-agent-experience',
    '00-preparation',
    'playwright-cache',
  );
}
const { chromium } = createRequire(import.meta.url)(
  'C:/Users/20616/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright',
);

const questionId = 'clarification-snack-type';
const options = [
  { id: 'snack-chips-a', label: '薯片' },
  { id: 'snack-chips-b', label: '薯片' },
];
let turnNumber = 0;
let resolveSecondTurn;
const secondTurn = new Promise((resolve) => {
  resolveSecondTurn = resolve;
});
let cartMutationCount = 0;

const server = await createServer({
  root: frontendRoot,
  configFile: path.join(frontendRoot, 'vite.config.ts'),
  server: {
    host: '127.0.0.1',
    port: 18443,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:18012', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:18012', changeOrigin: true },
    },
  },
});

let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 430, height: 900 } });
  await context.addInitScript(() => {
    sessionStorage.setItem('ceres-langgraph-guide-session-id', 'guide-probe');
    sessionStorage.setItem('ceres-mercury-session-id', 'mercury-probe');
    sessionStorage.setItem('ceres-v3-opening-id', 'opening-probe');
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

    if (pathName === '/api/v1/bootstrap') {
      await json({
        owner_id: 'owner-probe',
        store_id: 'store-demo-01',
        delivery_zone_id: 'zone-default',
        llm_mode: 'mock',
        business_data_mode: 'demo',
      });
      return;
    }
    if (pathName === '/api/v1/cart') {
      await json({ version: 0, items: [], total_price_fen: 0, business_data_mode: 'demo' });
      return;
    }
    if (pathName === '/api/v1/categories') {
      await json([]);
      return;
    }
    if (pathName === '/api/v1/products') {
      await json({ items: [], total: 0 });
      return;
    }
    if (pathName === '/api/v1/guide/sessions/guide-probe') {
      await json({
        session_id: 'guide-probe',
        task_id: null,
        state_version: 0,
        session_version: 0,
        plan: null,
        available_actions: [],
        pending_clarifications: [],
        messages: [],
      });
      return;
    }
    if (pathName === '/api/v1/chat/openings/opening-probe') {
      await json({
        opening_id: 'opening-probe',
        guide_session_id: 'guide-probe',
        mercury_session_id: 'mercury-probe',
        role: 'keke',
        prompt_displayed: false,
        handoff_id: null,
      });
      return;
    }
    if (pathName.endsWith('/turns/stream') && request.method() === 'POST') {
      const requestBody = request.postDataJSON();
      turnNumber += 1;

      const turn = {
        request_id: requestBody.request_id,
        session_id: 'guide-probe',
        task_id: null,
        state_version: turnNumber,
        session_version: turnNumber,
        status: 'completed',
        message: turnNumber === 1 ? '你想选哪种零食？' : '已收到分类选择',
        product_cards: [],
        route: null,
        committed: false,
        plan_effect: 'keep',
        pending_clarifications: [{
          question_id: questionId,
          question: '你想选哪种零食？',
          options,
        }],
        available_actions: [],
        trace_id: 'trace-probe',
        model_mode: 'mock',
        business_data_mode: 'demo',
      };
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: `event: turn.completed\ndata: ${JSON.stringify(turn)}\n\n`,
      });
      if (turnNumber > 1) resolveSecondTurn(requestBody);
      return;
    }
    if (pathName.startsWith('/api/v1/cart/items')) cartMutationCount += 1;
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'UNEXPECTED_PROBE_REQUEST', message: pathName } }),
    });
  });

  const page = await context.newPage();
  await page.goto('http://127.0.0.1:18443/');
  await page.getByRole('button', { name: /生鲜采买/ }).click();
  await page.getByRole('button', { name: '问问可可' }).click();
  await page.getByRole('button', { name: /来点零食/ }).waitFor({ state: 'visible' });
  await page.getByRole('button', { name: /来点零食/ }).click();

  const optionButtons = page.getByRole('button', { name: /薯片/ });
  await optionButtons.first().waitFor({ state: 'visible' });
  const visibleOptionCount = await optionButtons.count();
  await optionButtons.nth(visibleOptionCount > 1 ? 1 : 0).click();

  await page.getByText('已收到分类选择', { exact: true }).waitFor({ state: 'visible' });
  const visibleDuplicateCount = await page.getByRole('button', { name: /薯片/ }).count();
  const body = await secondTurn;

  assert.deepEqual(
    body.clarification_answer,
    { question_id: questionId, option_id: 'snack-chips-b' },
    'clicking a clarification bubble must submit its question and option IDs',
  );
  assert.equal(visibleOptionCount, 2, 'equal labels must remain separate selectable options');
  assert.equal(visibleDuplicateCount, 2, 'equal labels must remain separate after the next turn');
  assert.equal(cartMutationCount, 0, 'choosing a category must not mutate the cart');
  console.log('UI clarification probe passed');
} finally {
  if (browser) await browser.close();
  await server.close();
}