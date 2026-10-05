// Actual DOM verification only. Each URL has a separate fixture DB and browser context.
// The only chat turn asks for order choices before an order is selected; this server path does not call a model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [outputRoot, playwrightModule, executablePath, ...urls] = process.argv.slice(2);
const { chromium } = require(playwrightModule);

async function main() {
  const browser = await chromium.launch({ executablePath, headless: true });
  const results = [];
  try {
    for (const [index, url] of urls.entries()) {
      const dir = path.join(outputRoot, `run-${index + 1}`);
      fs.mkdirSync(dir, { recursive: true });
      const context = await browser.newContext({ viewport: { width: 540, height: 1050 } });
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      const result = { url, started_utc: new Date().toISOString(), steps: [], requests: [], page_errors: [] };
      page.on('response', response => {
        if (response.url().includes('/api/')) result.requests.push({ method: response.request().method(), url: response.url(), status: response.status() });
      });
      page.on('pageerror', error => result.page_errors.push(error.message));
      try {
        await page.goto(url);
        const initialOrders = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/orders' && response.request().method() === 'GET');
        await page.getByRole('button', { name: '订单', exact: true }).click();
        assert.deepEqual((await (await initialOrders).json()).items, []);
        result.steps.push({ step: 'initial_orders_empty', utc: new Date().toISOString() });

        await page.getByRole('button', { name: '商品', exact: true }).click();
        await page.getByPlaceholder('搜索有机食材与好物').fill('番茄');
        const addResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/cart/items' && response.request().method() === 'POST');
        await page.getByRole('button', { name: '添加新鲜番茄 500克到购物车', exact: true }).click();
        const cart = await (await addResponse).json();
        assert.equal(cart.items.length, 1);
        assert.equal(cart.items[0].sku_id, 'demo:tomato-fresh-500g');
        assert.equal(cart.items[0].quantity, 1);
        assert.equal(cart.total_price_fen, 680);
        result.cart_after_explicit_add = cart;
        result.steps.push({ step: 'explicit_product_add', utc: new Date().toISOString() });

        await page.getByRole('button', { name: /问问可可/ }).click();
        await page.getByRole('button', { name: '购物车 1 件', exact: true }).click();
        await page.getByRole('button', { name: '结算', exact: true }).click();
        await page.getByRole('button', { name: '确认结算', exact: true }).waitFor({ state: 'visible' });
        assert.equal(result.requests.filter(request => request.url.endsWith('/cart/checkout')).length, 0);
        await page.screenshot({ path: path.join(dir, 'before-checkout.png'), fullPage: true });
        const checkoutResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/cart/checkout' && response.request().method() === 'POST');
        await page.getByRole('button', { name: '确认结算', exact: true }).click();
        const checkout = await (await checkoutResponse).json();
        const order = checkout.order;
        assert.match(order.order_id, /^O/);
        assert.equal(order.total_fen, 680);
        assert.equal(order.status, 'paid');
        assert.equal(order.items.length, 1);
        assert.equal(order.items[0].quantity, 1);
        assert.deepEqual(checkout.cart.items, []);
        assert.equal(checkout.cart.total_price_fen, 0);
        await page.getByText(order.order_id, { exact: true }).waitFor({ state: 'visible' });
        await page.getByText('本次为模拟下单，未发货；可在订单页查看商品和成交快照', { exact: true }).waitFor({ state: 'visible' });
        result.checkout = checkout;
        result.steps.push({ step: 'explicit_simulated_checkout', utc: new Date().toISOString() });
        await page.getByRole('button', { name: '查看订单', exact: true }).click();
        await page.getByRole('heading', { name: /我的订单/ }).waitFor({ state: 'visible' });
        await page.getByText(order.order_id, { exact: true }).waitFor({ state: 'visible' });

        await page.reload();
        const refreshedOrders = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/orders' && response.request().method() === 'GET');
        await page.getByRole('button', { name: '订单', exact: true }).click();
        const persisted = await (await refreshedOrders).json();
        assert.equal(persisted.items.length, 1);
        assert.equal(persisted.items[0].order_id, order.order_id);
        assert.equal(persisted.items[0].total_fen, order.total_fen);
        await page.getByText(order.order_id, { exact: true }).waitFor({ state: 'visible' });
        await page.screenshot({ path: path.join(dir, 'persisted-order.png'), fullPage: true });
        result.persisted_orders = persisted;
        result.steps.push({ step: 'order_persists_after_browser_refresh', utc: new Date().toISOString() });

        await page.getByRole('button', { name: /问问墨墨/ }).click();
        await page.getByRole('button', { name: '订单', exact: true }).click();
        await page.getByText('选择要咨询的订单', { exact: true }).waitFor({ state: 'visible' });
        const capsuleSelect = page.waitForResponse(response => /\/mercury\/sessions\/[^/]+\/order$/.test(new URL(response.url()).pathname));
        await page.getByRole('button', { name: new RegExp(order.order_id) }).click();
        assert.equal((await (await capsuleSelect).json()).order.order_id, order.order_id);
        await page.getByText(`当前咨询订单：${order.order_id}`, { exact: true }).waitFor({ state: 'visible' });
        result.steps.push({ step: 'manual_order_capsule_selection', utc: new Date().toISOString() });

        await page.getByRole('button', { name: '发起新对话', exact: true }).click();
        const input = page.getByPlaceholder('问问墨墨吧…');
        await input.fill('这一单买了什么？');
        await input.press('Enter');
        await page.getByText('请选择要咨询的订单。', { exact: true }).waitFor({ state: 'visible' });
        const bubbleSelect = page.waitForResponse(response => /\/mercury\/sessions\/[^/]+\/order$/.test(new URL(response.url()).pathname));
        await page.getByRole('button', { name: new RegExp(`${order.order_id}.*选择这笔订单`) }).click();
        assert.equal((await (await bubbleSelect).json()).order.order_id, order.order_id);
        await page.getByText(`当前咨询订单：${order.order_id}`, { exact: true }).waitFor({ state: 'visible' });
        await page.screenshot({ path: path.join(dir, 'selected-order-bubble.png'), fullPage: true });
        const turns = result.requests.filter(request => request.url.includes('/turns/'));
        assert.equal(turns.length, 1);
        assert.ok(turns[0].url.includes('/mercury/sessions/'));
        assert.equal(turns[0].status, 200);
        assert.deepEqual(result.page_errors, []);
        result.owner_id = (await context.cookies()).find(cookie => cookie.name === 'sg_owner_id').value;
        result.steps.push({ step: 'manual_real_order_id_bubble_selection_without_model', utc: new Date().toISOString() });
        result.status = 'passed';
      } catch (error) {
        // Report a failed independent case and continue the other case; no retry or alternate business path.
        result.status = 'failed';
        result.error = error.stack;
        await page.screenshot({ path: path.join(dir, 'failure.png'), fullPage: true });
      } finally {
        result.finished_utc = new Date().toISOString();
        fs.writeFileSync(path.join(dir, 'result.json'), JSON.stringify(result, null, 2));
        results.push(result);
        console.log(JSON.stringify({ run: index + 1, status: result.status, error: result.error, steps: result.steps }));
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(outputRoot, 'ui-results.json'), JSON.stringify(results, null, 2));
  process.exitCode = results.some(result => result.status !== 'passed') ? 1 : 0;
}

main().catch(error => { console.error(error.stack); process.exitCode = 1; });
