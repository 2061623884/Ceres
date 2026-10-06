import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const probeDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = process.env.CERES_PROBE_REPO_ROOT || path.resolve(probeDir, '../../..');
const frontendRoot = path.join(repoRoot, 'frontend');
const requireFromFrontend = createRequire(pathToFileURL(path.join(frontendRoot, 'package.json')));
const { createServer } = await import(pathToFileURL(requireFromFrontend.resolve('vite')).href);
const { chromium } = createRequire(import.meta.url)(
  'C:/Users/20616/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright',
);

const activityProducts = [
  {
    sku_id: 'demo:green-reset-avocado-salad',
    name: 'Green Reset Avocado Salad',
    name_zh: '牛油果成品沙拉',
    category_id: 'snack',
    price_fen: 2380,
    image_path: null,
    sellable: true,
  },
  {
    sku_id: 'demo:green-reset-fruit-platter',
    name: 'Green Reset Fruit Platter',
    name_zh: '鲜果成品拼盘',
    category_id: 'fruit',
    price_fen: 1980,
    image_path: null,
    sellable: true,
  },
  {
    sku_id: 'demo:cn-minute-maid-peach-450ml-bottle',
    name: 'Minute Maid Peach Juice Drink 450ml Bottle',
    name_zh: '美汁源汁汁桃桃桃汁饮料450毫升瓶装',
    category_id: 'beverage',
    price_fen: 450,
    image_path: null,
    sellable: true,
  },
];

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
let turnRequestBody = null;
let confirmationBody = null;
let turnNumber = 0;
let stateVersion = 0;
let sessionVersion = 0;
let cartMutationCount = 0;
let cart = { version: 0, items: [], total_price_fen: 0, business_data_mode: 'demo' };

try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 430, height: 900 } });
  await context.addInitScript(() => {
    sessionStorage.setItem('ceres-langgraph-guide-session-id', 'guide-activity-probe');
    sessionStorage.setItem('ceres-mercury-session-id', 'mercury-activity-probe');
    sessionStorage.setItem('ceres-v3-opening-id', 'opening-activity-probe');
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
      await json({ owner_id: 'owner-activity-probe', store_id: 'store-demo-01', delivery_zone_id: 'zone-default', llm_mode: 'mock', business_data_mode: 'demo' });
      return;
    }
    if (pathName === '/api/v1/cart' && request.method() === 'GET') {
      await json(cart);
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
    if (pathName.startsWith('/api/v1/products/')) {
      const skuId = decodeURIComponent(pathName.slice('/api/v1/products/'.length));
      const product = activityProducts.find((item) => item.sku_id === skuId);
      if (product) {
        await json(product);
        return;
      }
    }
    if (pathName === '/api/v1/guide/sessions/guide-activity-probe') {
      await json({
        session_id: 'guide-activity-probe', task_id: null, state_version: stateVersion,
        session_version: sessionVersion, plan: null, available_actions: [],
        pending_clarifications: [], messages: [],
      });
      return;
    }
    if (pathName === '/api/v1/chat/openings/opening-activity-probe') {
      await json({
        opening_id: 'opening-activity-probe', guide_session_id: 'guide-activity-probe',
        mercury_session_id: 'mercury-activity-probe', role: 'keke', prompt_displayed: false, handoff_id: null,
      });
      return;
    }
    if (pathName.endsWith('/turns/stream') && request.method() === 'POST') {
      turnRequestBody = request.postDataJSON();
      turnNumber += 1;
      const selectedProduct = activityProducts.find((item) =>
        turnRequestBody.message.includes(item.name_zh),
      );
      const plan = selectedProduct ? {
        plan_id: 'plan-activity-probe', plan_version: 1, mode: 'bundle',
        items: [{
          sku_id: selectedProduct.sku_id, name: selectedProduct.name_zh, quantity: 1,
          unit_price_fen: selectedProduct.price_fen, line_total_fen: selectedProduct.price_fen,
          image_path: selectedProduct.image_path, selected: true,
        }],
        total_price_fen: selectedProduct.price_fen, expires_at: '2026-10-07T00:00:00Z',
        validation_status: 'valid', can_confirm: true,
      } : null;
      const turn = {
        request_id: turnRequestBody.request_id,
        session_id: 'guide-activity-probe',
        task_id: selectedProduct ? 'task-activity-probe' : null,
        state_version: ++stateVersion,
        session_version: ++sessionVersion,
        status: selectedProduct ? 'awaiting_confirmation' : 'completed',
        message: selectedProduct ? '这款已放入本次采购清单，确认后才会加购。' : '已进入可可。',
        product_cards: [], route: selectedProduct ? 'purchase' : null, committed: false,
        plan, plan_effect: selectedProduct ? 'replace' : 'keep',
        pending_clarifications: [], available_actions: selectedProduct ? ['modify', 'confirm'] : [],
        trace_id: `trace-activity-${turnNumber}`, model_mode: 'mock', business_data_mode: 'demo',
      };
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: `event: turn.completed\ndata: ${JSON.stringify(turn)}\n\n`,
      });
      return;
    }
    if (pathName === '/api/v1/guide/tasks/task-activity-probe/confirm' && request.method() === 'POST') {
      confirmationBody = request.postDataJSON();
      cartMutationCount += 1;
      const selected = confirmationBody.selected_items[0];
      const product = activityProducts.find((item) => item.sku_id === selected.sku_id);
      cart = {
        version: 1,
        items: [{
          sku_id: product.sku_id, name: product.name_zh, quantity: selected.quantity,
          unit_price_fen: product.price_fen, line_total_fen: product.price_fen,
          image_path: product.image_path, sellable: true,
        }],
        total_price_fen: product.price_fen,
        business_data_mode: 'demo',
      };
      await json({
        operation_id: 'operation-activity-probe', status: 'confirmed', cart_version: 1,
        items_added: [selected], errors: [], task_id: 'task-activity-probe',
        state_version: ++stateVersion, session_version: ++sessionVersion,
        confirmation_id: 'confirmation-activity-probe',
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'UNEXPECTED_PROBE_REQUEST', message: pathName } }),
    });
  });

  const page = await context.newPage();
  await page.goto('http://127.0.0.1:18443/');
  await page.getByRole('button', { name: /减脂餐|GREEN RESET/ }).click();
  await page.getByText('GREEN RESET', { exact: false }).waitFor({ state: 'visible', timeout: 3000 });
  await page.getByText('牛油果成品沙拉', { exact: true }).waitFor({ state: 'visible' });
  await page.getByText('鲜果成品拼盘', { exact: true }).waitFor({ state: 'visible' });
  await page.getByText('美汁源汁汁桃桃桃汁饮料450毫升瓶装', { exact: true }).waitFor({ state: 'visible' });

  await page.getByRole('button', { name: /选购牛油果成品沙拉/ }).click();
  await page.getByText('采购清单', { exact: true }).waitFor({ state: 'visible' });
  await page.getByText('牛油果成品沙拉', { exact: true }).waitFor({ state: 'visible' });
  assert.equal(cartMutationCount, 0, 'browsing or selecting an activity SKU must not add it to the cart');
  assert.match(turnRequestBody.message, /GREEN RESET/);
  assert.match(turnRequestBody.message, /牛油果成品沙拉/);
  assert.deepEqual(turnRequestBody.view_context, {
    page: 'product',
    category_id: null,
    product_id: activityProducts[0].sku_id,
    activity_id: 'green_reset',
  });

  await page.getByRole('button', { name: '确认加购' }).click();
  await page.getByRole('button', { name: /购物车 1 件/ }).waitFor({ state: 'visible' });
  assert.equal(cartMutationCount, 1, 'only the explicit confirmation may add the selected SKU');
  assert.deepEqual(confirmationBody.selected_items, [{ sku_id: activityProducts[0].sku_id, quantity: 1 }]);
  await page.getByRole('button', { name: /购物车 1 件/ }).click();
  await page.getByText('牛油果成品沙拉', { exact: true }).waitFor({ state: 'visible' });
  console.log('Homepage activity → selected finished SKU → plan → explicit confirmation probe passed');
} finally {
  if (browser) await browser.close();
  await server.close();
}
