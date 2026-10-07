// Two fixed real-frontend journeys; API reads verify the state produced by UI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const HEAD = 'ac895fd620af617fa31f4e0006841a4d6a89cd53';
const out = path.resolve(process.env.CERES_UI_OUTPUT);
const appUrl = process.env.CERES_APP_URL;
const runtimePath = process.env.CERES_UI_RUNTIME_RECEIPT;
const runtime = JSON.parse(fs.readFileSync(runtimePath, 'utf8'));
assert.equal(runtime.product_head, HEAD);
assert.equal(runtime.llm_mode, 'live');
assert.equal(runtime.retrieval_mode, 'lexical');
assert.ok(runtime.database_path && runtime.backend_pid && runtime.frontend_pid);
assert.equal(new URL(runtime.frontend_url).href, new URL(appUrl).href);
assert.equal(new URL(appUrl).hostname, '127.0.0.1');
assert.equal(runtime.proxy_api_target, runtime.api_base_url);
assert.equal(crypto.createHash('sha256').update(fs.readFileSync(runtime.vite_config_path)).digest('hex'), runtime.vite_config_sha256);
const databaseRelative = path.relative(path.dirname(path.resolve(runtimePath)), path.resolve(runtime.database_path));
assert.ok(!databaseRelative.startsWith('..') && !path.isAbsolute(databaseRelative), 'Database must be under the dedicated runtime receipt directory');
fs.mkdirSync(out); // Never overwrite an earlier batch.
const { chromium } = createRequire(import.meta.url)(process.env.CERES_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true, channel: runtime.browser_channel });
const report = { product_head: HEAD, started_utc: new Date().toISOString(), app_url: appUrl,
  runtime_receipt_path: path.resolve(runtimePath), runtime_identity: runtime,
  runtime_receipt_sha256: crypto.createHash('sha256').update(fs.readFileSync(runtimePath)).digest('hex'),
  runner_sha256: crypto.createHash('sha256').update(fs.readFileSync(new URL(import.meta.url))).digest('hex'),
  journeys: [], usage: null, usage_reason: 'Browser server has no provider transport capture; API batch usage is separate',
  human_evaluation: 'not_evaluated' };

function save() {
  const json = JSON.stringify(report, null, 2)
    .replace(/https?:\/\/[^\s"'<>\\]+/g, text => {
      const url = new URL(text);
      url.username = ''; url.password = '';
      for (const key of [...url.searchParams.keys()]) if (/^(api_key|key|token|access_token|refresh_token|authorization|internal_admin_token)$/i.test(key)) url.searchParams.set(key, '[REDACTED]');
      return url.href;
    })
    .replace(/(["']?(?:api_key|openai_api_key|embedding_api_key|internal_admin_token|access_token|refresh_token|authorization|x-internal-token|secret_key)["']?\s*[:=]\s*["']?)(?:Bearer\s+)?[^"',\s}\]]+/gi, '$1[REDACTED]');
  fs.writeFileSync(path.join(out, 'result.json'), json + '\n');
}
function parseSse(text) {
  return text.replaceAll('\r\n', '\n').split('\n\n').flatMap(block => {
    const type = block.split('\n').find(line => line.startsWith('event: '))?.slice(7);
    const data = block.split('\n').find(line => line.startsWith('data: '))?.slice(6);
    if (!data) return [];
    const body = JSON.parse(data);
    return [type ? { type, payload: body } : { type: body.type, payload: body.payload ?? body }];
  });
}

try {
for (const name of ['activity-salad', 'snack-bubble']) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  const item = { name, status: 'running', stage: 'load', steps: [], requests: [], console_errors: [] };
  report.journeys.push(item);
  page.on('pageerror', error => item.console_errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/api/v1/')) item.requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() });
  });
  let sessionId;
  page.on('response', async response => {
    if (response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/guide/sessions' && response.ok()) {
      sessionId = (await response.json()).session_id;
    }
  });
  async function get(url) {
    return page.evaluate(async endpoint => {
      const response = await fetch(endpoint, { credentials: 'include' });
      if (!response.ok) throw new Error(`${endpoint}: HTTP ${response.status}`);
      return response.json();
    }, url);
  }
  async function turn(label, action, marker) {
    item.stage = label;
    const started = performance.now();
    const first = marker ? marker.waitFor({ state: 'visible', timeout: 100000 }).then(() => performance.now() - started).catch(error => ({ error: error.message })) : Promise.resolve(null);
    const [response] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/turns/stream'), { timeout: 100000 }),
      action(),
    ]);
    const text = await response.text();
    const elapsed = performance.now() - started;
    const firstResult = await first;
    const row = { label, request: response.request().postDataJSON(), http_status: response.status(), events: [], raw_sse: text,
      final_reply_ms: elapsed, first_useful_result_ms: typeof firstResult === 'number' ? firstResult : null,
      timing_basis: 'UI action start to fully received turn.completed SSE; final reply rendering not sampled',
      first_useful_result_note: firstResult === null ? 'No DOM marker sampled for this step' : firstResult,
      performance_passed: elapsed <= 15000 };
    item.steps.push(row);
    save();
    const events = parseSse(text);
    row.events = events;
    assert.equal(response.status(), 200);
    assert.ok(events.some(event => event.type === 'turn.completed'));
    assert.ok(!events.some(event => event.type === 'error'));
    row.cart_after_reply = await get('/api/v1/cart');
    save();
    assert.equal(row.cart_after_reply.items.length, 0, 'No cart write after any pre-confirm reply');
    return row;
  }
  async function send(label, text, marker) {
    const input = page.getByPlaceholder('问问可可吧…');
    await input.fill(text);
    return turn(label, () => input.press('Enter'), marker);
  }
  try {
    const [bootstrap] = await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/bootstrap'),
      page.goto(appUrl, { waitUntil: 'domcontentloaded' }),
    ]);
    await bootstrap.finished();
    item.bootstrap = await bootstrap.json();
    assert.equal(item.bootstrap.llm_mode, 'live');
    assert.equal(item.bootstrap.business_data_mode, 'demo');
    const servedApp = await page.request.get(new URL('/src/App.tsx', appUrl).href);
    assert.equal(crypto.createHash('sha256').update(await servedApp.body()).digest('hex'), runtime.served_app_module_sha256);
    item.initial_cart = await get('/api/v1/cart');
    assert.equal(item.initial_cart.items.length, 0);
    await page.screenshot({ path: path.join(out, name + '-home.png'), fullPage: true });
    let sku, quantity, unitPrice;
    if (name === 'activity-salad') {
      sku = 'demo:green-reset-avocado-salad'; quantity = 1; unitPrice = 2380;
      item.stage = 'activity-entry';
      await page.getByRole('button', { name: /GREEN RESET 今天轻一点专题活动/ }).click();
      await page.getByText('GREEN RESET｜今天轻一点', { exact: true }).waitFor({ state: 'visible' });
      await page.screenshot({ path: path.join(out, name + '-entry.png'), fullPage: true });
      const selected = await turn('select-activity-product', () => page.getByRole('button', { name: '选购牛油果成品沙拉', exact: true }).click());
      assert.equal(selected.request.view_context.product_id, sku);
      assert.equal(selected.request.view_context.activity_id, 'green_reset');
      await page.getByRole('button', { name: '关闭', exact: true }).last().click();
      await send('request-plan', '请把 GREEN RESET 里的牛油果成品沙拉一份作为唯一商品整理成采购清单，先让我确认，暂不加购。');
    } else {
      sku = 'demo:snack-original-potato-chips-70g-bag'; quantity = 2; unitPrice = 590;
      item.stage = 'open-guide';
      await page.getByRole('button', { name: '商品', exact: true }).click();
      const [openingResponse] = await Promise.all([
        page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/chat/openings'),
        page.getByRole('button', { name: /问问可可$/ }).click(),
      ]);
      await openingResponse.finished();
      const option = page.getByRole('button', { name: /薯片$/ });
      await send('request-snack', '来点零食', option);
      await turn('select-type-bubble', () => option.click());
      await send('request-plan', '原味薯片70克两包，预算20元，整理成清单让我确认，暂不加购。');
    }
    assert.ok(sessionId, 'Guide session was created by the UI');
    const guide = await get(`/api/v1/guide/sessions/${sessionId}`);
    item.plan_before_confirm = guide;
    assert.ok(guide.plan?.can_confirm);
    const selected = guide.plan.items.filter(row => row.selected);
    assert.deepEqual(selected.map(row => [row.sku_id, row.quantity]), [[sku, quantity]]);
    assert.equal(selected[0].unit_price_fen, unitPrice);
    assert.equal(selected[0].line_total_fen, quantity * unitPrice);
    assert.equal(guide.plan.selected_total_fen, quantity * unitPrice);
    if (name === 'snack-bubble') assert.equal(guide.constraints_summary.budget_fen, 2000);
    item.cart_before_confirm = await get('/api/v1/cart');
    assert.equal(item.cart_before_confirm.items.length, 0);
    item.writes_before_confirm = item.requests.filter(request => request.method !== 'GET' &&
      (/\/api\/v1\/cart(?:\/|$)/.test(new URL(request.url).pathname) || /\/guide\/tasks\/[^/]+\/confirm$/.test(new URL(request.url).pathname)));
    assert.equal(item.writes_before_confirm.length, 0, 'No cart or confirmation writes before explicit confirmation');
    item.stage = 'show-plan-capsule';
    const confirm = page.getByRole('button', { name: '确认加购', exact: true });
    if (!await confirm.isVisible()) await page.getByRole('button', { name: /采购清单(?: \d+ 件)?/ }).last().click();
    await confirm.waitFor({ state: 'visible' });
    await page.screenshot({ path: path.join(out, name + '-plan.png'), fullPage: true });
    item.stage = 'explicit-confirm';
    const [response] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && /\/guide\/tasks\/[^/]+\/confirm$/.test(new URL(response.url()).pathname)),
      confirm.click(),
    ]);
    item.confirmation = { status: response.status(), body: await response.json() };
    assert.equal(response.status(), 200);
    item.final_cart = await get('/api/v1/cart');
    assert.deepEqual(item.final_cart.items.map(row => [row.sku_id, row.quantity, row.unit_price_fen]), [[sku, quantity, unitPrice]]);
    assert.equal(item.final_cart.total_price_fen, quantity * unitPrice);
    assert.equal(item.console_errors.length, 0);
    item.status = 'passed';
  } catch (error) {
    item.status = 'failed';
    item.error = { type: error.name, message: error.message };
  } finally {
    item.performance_passed = item.steps.length > 0 && item.steps.every(row => row.performance_passed);
    try {
      item.visible_text = await page.locator('body').innerText();
      await page.screenshot({ path: path.join(out, name + '-final.png'), fullPage: true });
    } catch (error) {
      item.evidence_error = { type: error.name, message: error.message };
      item.status = 'failed';
    } finally {
      await context.close();
      save();
    }
  }
}
} finally {
  await browser.close();
  report.finished_utc = new Date().toISOString();
  report.automatic_browser_acceptance = report.journeys.length === 2 && report.journeys.every(item => item.status === 'passed' && item.performance_passed) ? 'passed' : 'not_passed';
  save();
}
console.log(JSON.stringify({ acceptance: report.automatic_browser_acceptance, journeys: report.journeys.map(({ name, status, performance_passed }) => ({ name, status, performance_passed })) }));
process.exitCode = report.automatic_browser_acceptance === 'passed' ? 0 : 1;
