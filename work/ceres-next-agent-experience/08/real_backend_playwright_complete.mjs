// Real-backend/browser evidence probe for Ceres Next 08.
// Public UI only: no API interception, fulfillment, mocks, or direct state writes.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const appUrl = process.env.CERES_APP_URL;
const evidenceFile = process.env.CERES_UI_EVIDENCE_FILE;
const playwrightModule = process.env.CERES_PLAYWRIGHT_MODULE;
const publicApiEvidenceFile = process.env.CERES_PUBLIC_API_EVIDENCE_FILE;
const backendStartupReceiptFile = process.env.CERES_BACKEND_STARTUP_RECEIPT_FILE;
const sourceRoot = process.env.CERES_SOURCE_ROOT;
const sourceRevision = process.env.CERES_SOURCE_REVISION || null;
if (!evidenceFile) throw new Error('CERES_UI_EVIDENCE_FILE is required so failures can be saved');

const resolvedEvidenceFile = path.resolve(evidenceFile);
const evidenceDirectory = path.dirname(resolvedEvidenceFile);
const screenshotDirectory = path.join(evidenceDirectory, 'real-backend-ui');
fs.mkdirSync(evidenceDirectory, { recursive: true });

const UI_TIMEOUT_MS = 15000;
const IDENTITY_FIELDS = [
  'database_path_fingerprint',
  'projection_snapshot_hash',
  'index_root_fingerprint',
  'index_version',
  'index_manifest_id',
  'retrieval_mode',
  'embedding_contract',
];
const SOURCE_FILES = [
  'frontend/src/App.tsx',
  'frontend/src/MercuryChat.tsx',
  'frontend/src/lib/chatOpening.ts',
  'frontend/src/lib/saleGuide.ts',
  'backend/app/api/chat.py',
  'backend/app/api/mercury.py',
  'backend/app/api/cart.py',
  'backend/app/api/orders.py',
  'Mercury/mercury/services.py',
];
const evidence = {
  runner_version: 'ceres-next-08-real-backend-ui-v1',
  runner_sha256: null,
  status: 'running',
  current_stage: 'preflight',
  app_origin: null,
  timeout_ms: UI_TIMEOUT_MS,
  runtime_identity: null,
  source_manifest: { revision: sourceRevision, files: [] },
  browser_actions: [],
  api_requests: [],
  api_responses: [],
  public_reads: [],
  business_state: {},
  screenshots: [],
};
let browser = null;
let page = null;
let exitCode = 0;
const pendingCaptureReads = [];

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}
function stableJson(value) {
  return JSON.stringify(canonical(value));
}
function clipped(value, maxLength = 800) {
  if (typeof value !== 'string') return value;
  return value.length <= maxLength ? value : value.slice(0, maxLength) + '…[truncated]';
}
function credentialRedact(value) {
  return String(value).replace(
    /(["']?(?:api_key|openai_api_key|embedding_api_key|internal_admin_token|access_token|refresh_token|authorization|x-internal-token|secret_key)["']?\s*[:=]\s*["']?)[^"',\s}\]]+/gi,
    '$1[REDACTED]',
  );
}
function scrubTree(value) {
  if (typeof value === 'string') return credentialRedact(value);
  if (Array.isArray(value)) return value.map(scrubTree);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrubTree(item)]));
  }
  return value;
}
function scalar(value, maxLength = 240) {
  if (typeof value === 'string') return clipped(value, maxLength);
  if (typeof value === 'number' || typeof value === 'boolean' || value === null) return value;
  return undefined;
}
function onlyFields(source, fields) {
  const result = {};
  for (const field of fields) {
    if (source && Object.hasOwn(source, field)) {
      const value = scalar(source[field]);
      if (value !== undefined) result[field] = value;
    }
  }
  return result;
}
function summarizePlan(plan) {
  if (!plan || typeof plan !== 'object') return null;
  return {
    plan_id: scalar(plan.plan_id),
    plan_version: scalar(plan.plan_version),
    can_confirm: scalar(plan.can_confirm),
    status: scalar(plan.status),
    items: (Array.isArray(plan.items) ? plan.items : []).map(item => ({
      sku_id: scalar(item.sku_id),
      name: scalar(item.name),
      quantity: scalar(item.quantity ?? item.required_quantity),
      selected: scalar(item.selected),
      added_quantity: scalar(item.added_quantity),
      unit_price_fen: scalar(item.unit_price_fen),
    })),
  };
}
function summarizeClarifications(items) {
  return (Array.isArray(items) ? items : []).map(item => ({
    question_id: scalar(item.question_id),
    slot: scalar(item.slot),
    question: scalar(item.question),
    options: (Array.isArray(item.options) ? item.options : []).map(option => ({
      id: scalar(option.id),
      label: scalar(option.label),
    })),
  }));
}
function summarizeProductCards(cards) {
  return (Array.isArray(cards) ? cards : []).slice(0, 20).map(card => ({
    ref: scalar(card.ref),
    sku_id: scalar(card.sku_id),
    name: scalar(card.name),
    brand: scalar(card.brand),
    packaging: scalar(card.packaging),
    pack_count: scalar(card.pack_count),
    item_volume_ml: scalar(card.item_volume_ml),
    total_volume_ml: scalar(card.total_volume_ml),
    price_fen: scalar(card.price_fen),
  }));
}
function summarizeCart(cart) {
  if (!cart || typeof cart !== 'object') return null;
  return {
    version: scalar(cart.version),
    total_price_fen: scalar(cart.total_price_fen),
    items: (Array.isArray(cart.items) ? cart.items : []).map(item => ({
      sku_id: scalar(item.sku_id),
      name: scalar(item.name),
      product_name: scalar(item.product_name),
      quantity: scalar(item.quantity),
      unit_price_fen: scalar(item.unit_price_fen),
      line_total_fen: scalar(item.line_total_fen),
    })),
  };
}
function summarizeOrder(order) {
  if (!order || typeof order !== 'object') return null;
  return {
    order_id: scalar(order.order_id),
    status: scalar(order.status),
    total_fen: scalar(order.total_fen),
    items: (Array.isArray(order.items) ? order.items : []).map(item => ({
      item_id: scalar(item.item_id),
      sku_id: scalar(item.sku_id),
      product_id: scalar(item.product_id),
      product_name: scalar(item.product_name),
      quantity: scalar(item.quantity),
      unit_price_fen: scalar(item.unit_price_fen),
      line_total_fen: scalar(item.line_total_fen),
    })),
  };
}
function summarizeTurnPayload(payload) {
  const result = onlyFields(payload, [
    'status', 'message', 'final_text', 'answer_status', 'task_id',
    'state_version', 'session_version', 'trace_id', 'route', 'committed',
    'plan_effect', 'business_not_run', 'current_step', 'task_status',
  ]);
  if (payload && Object.hasOwn(payload, 'plan')) result.plan = summarizePlan(payload.plan);
  if (payload && Object.hasOwn(payload, 'pending_clarifications')) {
    result.pending_clarifications = summarizeClarifications(payload.pending_clarifications);
  } else if (payload && Object.hasOwn(payload, 'pending_clarification')) {
    result.pending_clarifications = summarizeClarifications(payload.pending_clarification ? [payload.pending_clarification] : []);
  }
  if (payload && Object.hasOwn(payload, 'product_cards')) result.product_cards = summarizeProductCards(payload.product_cards);
  if (payload && Object.hasOwn(payload, 'available_actions')) {
    result.available_actions = Array.isArray(payload.available_actions) ? payload.available_actions.map(value => scalar(value)) : [];
  }
  if (payload && Object.hasOwn(payload, 'confirmation_result')) {
    const confirmation = payload.confirmation_result;
    result.confirmation_result = confirmation && typeof confirmation === 'object'
      ? {
          items_added: (Array.isArray(confirmation.items_added) ? confirmation.items_added : []).map(item => ({
            sku_id: scalar(item.sku_id),
            quantity: scalar(item.quantity),
          })),
          cart_version: scalar(confirmation.cart_version),
        }
      : null;
  }
  return result;
}
function summarizeGuideSession(session) {
  return {
    session_id: scalar(session.session_id),
    task_id: scalar(session.task_id),
    state_version: scalar(session.state_version),
    session_version: scalar(session.session_version),
    current_step: scalar(session.current_step),
    task_status: scalar(session.task_status),
    available_actions: Array.isArray(session.available_actions) ? session.available_actions.map(value => scalar(value)) : [],
    plan: summarizePlan(session.plan),
    pending_clarifications: summarizeClarifications(session.pending_clarifications),
    messages: (Array.isArray(session.messages) ? session.messages : []).slice(-8).map(message => ({
      role: scalar(message.role),
      kind: scalar(message.kind),
      sequence: scalar(message.sequence),
      content: clipped(String(message.content ?? ''), 500),
    })),
    product_cards: summarizeProductCards(session.product_cards),
  };
}
function summarizeJson(pathname, body) {
  const route = pathname.split('?')[0];
  if (route === '/api/v1/cart') return summarizeCart(body);
  if (route === '/api/v1/orders') return { items: (Array.isArray(body.items) ? body.items : []).map(summarizeOrder) };
  if (/^\/api\/v1\/guide\/sessions\/[^/]+$/.test(route)) return summarizeGuideSession(body);
  if (route === '/api/v1/guide/sessions') return onlyFields(body, ['session_id', 'task_id', 'state_version', 'session_version']);
  if (route === '/api/v1/cart/checkout') return { order: summarizeOrder(body.order), cart: summarizeCart(body.cart) };
  if (/^\/api\/v1\/guide\/tasks\/[^/]+\/confirm$/.test(route)) {
    return {
      task_id: scalar(body.task_id),
      state_version: scalar(body.state_version),
      session_version: scalar(body.session_version),
      confirmation_result: summarizeTurnPayload({ confirmation_result: body.confirmation_result }).confirmation_result,
      cart: summarizeCart(body.cart),
    };
  }
  if (/^\/api\/v1\/mercury\/sessions\/[^/]+\/order$/.test(route)) {
    return { session_id: scalar(body.session_id), order: summarizeOrder(body.order) };
  }
  if (route === '/api/v1/chat/openings') return onlyFields(body, ['opening_id', 'guide_session_id', 'mercury_session_id', 'role', 'handoff_id']);
  if (/^\/api\/v1\/chat\/openings\/[^/]+$/.test(route)) {
    return onlyFields(body, ['opening_id', 'guide_session_id', 'mercury_session_id', 'role', 'prompt_displayed', 'handoff_id']);
  }
  if (route === '/api/v1/mercury/sessions') return onlyFields(body, ['session_id', 'selected_order_id']);
  if (/^\/api\/v1\/products\/[^/]+$/.test(route)) return onlyFields(body, ['sku_id', 'product_id', 'name', 'name_zh', 'sellable', 'price_fen']);
  return null;
}
function safeSsePayload(type, payload) {
  if (type === 'service.route') {
    return onlyFields(payload, ['status', 'decision', 'current_role', 'target_role', 'handoff_id', 'prompt_mode', 'decision_source', 'request_id', 'route_ms']);
  }
  if (type === 'service.switch') return onlyFields(payload, ['status', 'accepted', 'role', 'current_role', 'target_role', 'handoff_id']);
  if (type === 'answer.delta') return { text: clipped(String(payload.delta ?? payload.text ?? payload.content ?? ''), 1600) };
  if (type === 'turn.completed') return summarizeTurnPayload(payload);
  if (type === 'accepted') return onlyFields(payload, ['request_id']);
  if (type === 'orders') return { items: (Array.isArray(payload.items) ? payload.items : []).map(summarizeOrder) };
  if (type === 'error') return onlyFields(payload, ['code', 'message', 'retryable']);
  if (type === 'turn.progress' || type === 'progress') return onlyFields(payload, ['phase', 'status']);
  if (type === 'clarification') {
    return { pending_clarifications: summarizeClarifications(payload.pending_clarifications ?? (payload.pending_clarification ? [payload.pending_clarification] : [])) };
  }
  return {};
}
function summarizeSse(text) {
  const events = [];
  let visibleText = '';
  for (const block of text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n\n')) {
    if (!block.trim()) continue;
    let eventName = '';
    const dataLines = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) continue;
    let parsed;
    try { parsed = JSON.parse(dataLines.join('\n')); } catch {
      events.push({ type: eventName || 'unparsed', parse_error: true });
      continue;
    }
    const type = eventName && eventName !== 'message' ? eventName : (typeof parsed.type === 'string' ? parsed.type : '');
    const payload = parsed.payload && typeof parsed.payload === 'object' ? parsed.payload : parsed;
    if (!type) continue;
    const safePayload = safeSsePayload(type, payload);
    events.push({ type, payload: safePayload });
    if (type === 'answer.delta' && safePayload.text) visibleText += safePayload.text;
    if (type === 'turn.completed') {
      const completedText = safePayload.final_text ?? safePayload.message;
      if (typeof completedText === 'string') visibleText = completedText;
    }
  }
  return { events, visible_text: clipped(visibleText, 1800) };
}
function summarizeRequestBody(method, pathname, parsed) {
  const route = pathname.split('?')[0];
  if (!parsed || typeof parsed !== 'object') return null;
  if (method === 'POST' && /\/turns\/stream$/.test(route)) {
    const result = onlyFields(parsed, ['request_id', 'message', 'order_id', 'expected_task_id', 'expected_state_version', 'expected_session_version']);
    if (parsed.view_context && typeof parsed.view_context === 'object') {
      result.view_context = onlyFields(parsed.view_context, ['page', 'category_id', 'product_id', 'activity_id']);
    }
    if (parsed.clarification_answer && typeof parsed.clarification_answer === 'object') {
      result.clarification_answer = onlyFields(parsed.clarification_answer, ['question_id', 'option_id']);
    }
    if (parsed.plan_selection && typeof parsed.plan_selection === 'object') {
      result.plan_selection = {
        plan_id: scalar(parsed.plan_selection.plan_id),
        plan_version: scalar(parsed.plan_selection.plan_version),
        selected_items: (Array.isArray(parsed.plan_selection.selected_items) ? parsed.plan_selection.selected_items : []).map(item => ({
          sku_id: scalar(item.sku_id),
          quantity: scalar(item.quantity),
        })),
      };
    }
    return result;
  }
  if (method === 'POST' && /\/switches\/stream$/.test(route)) return onlyFields(parsed, ['accept', 'target_role', 'handoff_id']);
  if (method === 'POST' && /\/prompt-displayed$/.test(route)) return onlyFields(parsed, ['handoff_id']);
  if (method === 'POST' && /\/confirm$/.test(route)) {
    return {
      task_id: scalar(parsed.task_id),
      plan_id: scalar(parsed.plan_id),
      plan_version: scalar(parsed.plan_version),
      expected_state_version: scalar(parsed.expected_state_version),
      expected_session_version: scalar(parsed.expected_session_version),
      selected_items: (Array.isArray(parsed.selected_items) ? parsed.selected_items : []).map(item => ({
        sku_id: scalar(item.sku_id),
        quantity: scalar(item.quantity),
      })),
    };
  }
  if (method === 'POST' && route === '/api/v1/cart/checkout') return onlyFields(parsed, ['expected_cart_version']);
  if (method === 'POST' && /\/mercury\/sessions\/[^/]+\/order$/.test(route)) return onlyFields(parsed, ['order_id']);
  if (method === 'POST' && route === '/api/v1/chat/openings') return onlyFields(parsed, ['guide_session_id', 'mercury_session_id', 'role']);
  if (method === 'POST' && route === '/api/v1/guide/sessions') {
    return { entry_context: onlyFields(parsed.entry_context, ['page', 'category_id', 'product_id', 'activity_id', 'store_id', 'delivery_zone_id']) };
  }
  if (method === 'POST' && route === '/api/v1/mercury/sessions') return {};
  return null;
}
function isWhitelistedJson(method, pathname) {
  const route = pathname.split('?')[0];
  if (method === 'GET' && (route === '/api/v1/cart' || route === '/api/v1/orders')) return true;
  if (method === 'GET' && /^\/api\/v1\/guide\/sessions\/[^/]+$/.test(route)) return true;
  if (method === 'GET' && /^\/api\/v1\/chat\/openings\/[^/]+$/.test(route)) return true;
  if (method === 'GET' && /^\/api\/v1\/products\/[^/]+$/.test(route)) return true;
  if (method === 'POST' && (
    route === '/api/v1/guide/sessions'
    || route === '/api/v1/chat/openings'
    || route === '/api/v1/mercury/sessions'
    || route === '/api/v1/cart/checkout'
    || /^\/api\/v1\/guide\/tasks\/[^/]+\/confirm$/.test(route)
    || /^\/api\/v1\/mercury\/sessions\/[^/]+\/order$/.test(route)
  )) return true;
  return false;
}
function isStreamPath(pathname) {
  return /^\/api\/v1\/chat\/openings\/[^/]+\/(?:turns|switches)\/stream$/.test(pathname);
}
async function persistEvidence() {
  fs.mkdirSync(evidenceDirectory, { recursive: true });
  fs.writeFileSync(resolvedEvidenceFile, JSON.stringify(scrubTree(evidence), null, 2) + '\n', 'utf8');
}
function setStage(stage) {
  evidence.current_stage = stage;
}
function recordAction(action, details = {}) {
  evidence.browser_actions.push({ stage: evidence.current_stage, action, ...details });
}
async function screenshot(name) {
  if (!page) return;
  fs.mkdirSync(screenshotDirectory, { recursive: true });
  const fullPath = path.join(screenshotDirectory, name);
  await page.screenshot({ path: fullPath, fullPage: true, animations: 'disabled' });
  evidence.screenshots.push(path.relative(evidenceDirectory, fullPath).replace(/\\/g, '/'));
}
function requestSummary(request) {
  const url = new URL(request.url());
  if (!url.pathname.startsWith('/api/')) return null;
  const method = request.method();
  let parsed = null;
  try { parsed = request.postDataJSON(); } catch {}
  return {
    sequence: evidence.api_requests.length + 1,
    method,
    path: url.pathname,
    body: summarizeRequestBody(method, url.pathname, parsed),
  };
}
async function responseSummary(response) {
  const url = new URL(response.url());
  if (!url.pathname.startsWith('/api/')) return null;
  const method = response.request().method();
  const result = { sequence: evidence.api_responses.length + 1, method, path: url.pathname, status: response.status() };
  if (isStreamPath(url.pathname)) {
    result.stream = summarizeSse(await response.text());
    return result;
  }
  if (!isWhitelistedJson(method, url.pathname)) return result;
  try { result.body = summarizeJson(url.pathname, await response.json()); } catch { result.body_parse_error = true; }
  return result;
}
function turnResponses() {
  return evidence.api_responses.filter(item => item.stream && /\/turns\/stream$/.test(item.path));
}
function turnRequests() {
  return evidence.api_requests.filter(item => item.method === 'POST' && /\/turns\/stream$/.test(item.path));
}
async function waitUntil(predicate, label, timeout = UI_TIMEOUT_MS) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) return value;
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  throw new Error('Timed out after ' + timeout + 'ms waiting for ' + label);
}
async function waitForNextTurn(previousCount, label) {
  return waitUntil(() => {
    const records = turnResponses();
    return records.length > previousCount ? records[previousCount] : null;
  }, label);
}
async function waitForResponseSince(previousCount, predicate, label) {
  return waitUntil(() => evidence.api_responses.slice(previousCount).find(predicate), label);
}
function terminalPayload(record) {
  const completed = record?.stream?.events?.filter(event => event.type === 'turn.completed') ?? [];
  return completed.length ? completed[completed.length - 1].payload : null;
}
function requestAfter(previousCount, predicate) {
  return evidence.api_requests.slice(previousCount).find(predicate) ?? null;
}
function sessionIdFromEvidence() {
  const create = evidence.api_responses.find(item =>
    item.method === 'POST' && item.path === '/api/v1/guide/sessions' && item.body?.session_id,
  );
  if (create) return create.body.session_id;
  const openingCreate = evidence.api_requests.find(item => item.method === 'POST' && item.path === '/api/v1/chat/openings');
  if (openingCreate?.body?.guide_session_id) return openingCreate.body.guide_session_id;
  const get = evidence.api_requests.find(item => item.method === 'GET' && /^\/api\/v1\/guide\/sessions\/[^/]+$/.test(item.path));
  return get ? get.path.split('/').at(-1) : null;
}
async function publicGet(pathname, label) {
  const result = await page.evaluate(async url => {
    const response = await fetch(url, { method: 'GET', credentials: 'include' });
    let body = null;
    try { body = await response.json(); } catch {}
    return { status: response.status, body };
  }, pathname);
  evidence.public_reads.push({
    label,
    path: pathname.split('?')[0],
    status: result.status,
    body: summarizeJson(pathname.split('?')[0], result.body),
  });
  assert.equal(result.status, 200, 'Public GET failed: ' + label);
  return result.body;
}
async function readGuideSnapshot(guideSessionId, label) {
  const pathname = '/api/v1/guide/sessions/' + encodeURIComponent(guideSessionId) + '?include_messages=1';
  return summarizeGuideSession(await publicGet(pathname, label));
}
async function visibleGuideBubbles() {
  return page.locator('.guide-glass-bubble').evaluateAll(nodes =>
    nodes.filter(node => node.getClientRects().length > 0)
      .map(node => String(node.innerText || '').trim())
      .filter(Boolean),
  );
}
function findOption(question, predicate, label) {
  const option = (question.options ?? []).find(item => predicate(item.label));
  assert.ok(question.question_id, label + ' question_id is present');
  assert.ok(option?.id, label + ' option_id is present');
  return { question_id: question.question_id, option_id: option.id, label: option.label };
}
function escapedRegExp(text) {
  return text.replace(/[\^$.*+?()[\]{}|]/g, '\\$&');
}
async function clickClarificationBubble(label) {
  const locator = page.getByRole('button', { name: new RegExp(escapedRegExp(label) + '$') }).last();
  await locator.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await locator.click();
}
async function sendKekeMessage(message, label) {
  const before = turnResponses().length;
  const input = page.getByPlaceholder('问问可可吧…');
  await input.fill(message);
  await input.press('Enter');
  return waitForNextTurn(before, label);
}
async function clickPlanCapsuleIfNeeded() {
  const confirm = page.getByRole('button', { name: '确认加购', exact: true });
  if (await confirm.isVisible().catch(() => false)) return;
  const capsule = page.getByRole('button', { name: /采购清单(?: \d+ 件)?/ }).last();
  await capsule.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await capsule.click();
  await confirm.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
}
async function writeRuntimeAndSourceEvidence() {
  for (const name of [
    'CERES_APP_URL',
    'CERES_PLAYWRIGHT_MODULE',
    'CERES_PUBLIC_API_EVIDENCE_FILE',
    'CERES_BACKEND_STARTUP_RECEIPT_FILE',
    'CERES_SOURCE_ROOT',
  ]) assert.ok(process.env[name], name + ' is required');
  evidence.app_origin = new URL(appUrl).origin;
  const publicApiEvidence = JSON.parse(fs.readFileSync(publicApiEvidenceFile, 'utf8'));
  const backendStartupReceipt = JSON.parse(fs.readFileSync(backendStartupReceiptFile, 'utf8'));
  const expected = publicApiEvidence.runtime_identity;
  const actual = backendStartupReceipt.runtime_identity;
  assert.ok(expected && actual, 'Both receipts must include runtime_identity');
  assert.ok(Number.isInteger(backendStartupReceipt.process_id), 'Backend startup receipt must identify its process');
  const matched = {};
  for (const key of IDENTITY_FIELDS) {
    assert.ok(Object.hasOwn(expected, key), 'Public API runtime identity is missing ' + key);
    assert.ok(Object.hasOwn(actual, key), 'Backend runtime identity is missing ' + key);
    assert.equal(stableJson(actual[key]), stableJson(expected[key]), 'Backend and public API runtime identity differ at ' + key);
    matched[key] = key === 'embedding_contract'
      ? { sha256: sha256(Buffer.from(stableJson(actual[key]), 'utf8')) }
      : scalar(actual[key]);
  }
  evidence.runtime_identity = { matched: true, process_id: backendStartupReceipt.process_id, identity: matched };
  for (const relativePath of SOURCE_FILES) {
    evidence.source_manifest.files.push({
      path: relativePath,
      sha256: sha256(fs.readFileSync(path.join(sourceRoot, relativePath))),
    });
  }
}
async function main() {
  await writeRuntimeAndSourceEvidence();
  const { chromium } = createRequire(import.meta.url)(playwrightModule);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 430, height: 900 }, deviceScaleFactor: 1 });
  page = await context.newPage();
  page.setDefaultTimeout(UI_TIMEOUT_MS);
  page.on('request', request => {
    try {
      const summary = requestSummary(request);
      if (summary) evidence.api_requests.push(summary);
    } catch {
      const url = new URL(request.url());
      if (url.pathname.startsWith('/api/')) {
        evidence.api_requests.push({ sequence: evidence.api_requests.length + 1, method: request.method(), path: url.pathname, body: null });
      }
    }
  });
  page.on('response', response => {
    const capture = responseSummary(response)
      .then(summary => { if (summary) evidence.api_responses.push(summary); })
      .catch(() => {
        const url = new URL(response.url());
        if (url.pathname.startsWith('/api/')) {
          evidence.api_responses.push({
            sequence: evidence.api_responses.length + 1,
            method: response.request().method(),
            path: url.pathname,
            status: response.status(),
            body_parse_error: true,
          });
        }
      });
    pendingCaptureReads.push(capture);
  });

  setStage('load-home');
  await page.goto(appUrl, { waitUntil: 'domcontentloaded' });
  const activityCard = page.getByRole('button', { name: /GREEN RESET 今天轻一点专题活动/ });
  await activityCard.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const initialCartRaw = await publicGet('/api/v1/cart', 'initial cart');
  const initialOrdersRaw = await publicGet('/api/v1/orders', 'initial orders');
  const initialCart = summarizeCart(initialCartRaw);
  const initialOrders = (initialOrdersRaw.items ?? []).map(summarizeOrder);
  const initialOrderIds = new Set(initialOrders.map(order => order.order_id));
  evidence.business_state.initial = { cart: initialCart, orders: initialOrders };
  await screenshot('00-homepage.png');

  setStage('activity-finished-product');
  const beforeActivityTurn = turnResponses().length;
  await activityCard.click();
  recordAction('open-homepage-green-reset', { accessible_name: 'GREEN RESET 今天轻一点专题活动' });
  await page.getByText('GREEN RESET｜今天轻一点', { exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const saladButton = page.getByRole('button', { name: '选购牛油果成品沙拉', exact: true });
  await saladButton.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await screenshot('01-activity-products.png');
  await saladButton.click();
  recordAction('select-finished-activity-product', { sku_id: 'demo:green-reset-avocado-salad', activity_id: 'green_reset' });
  const activityTurn = await waitForNextTurn(beforeActivityTurn, 'activity product turn');
  assert.equal(activityTurn.status, 200, 'Activity selection stream must succeed');
  const activityRequest = turnRequests().at(-1);
  assert.ok(activityRequest, 'Activity product turn request is recorded');
  assert.equal(activityRequest.body?.view_context?.page, 'product', 'Activity turn must use product view context');
  assert.equal(activityRequest.body?.view_context?.product_id, 'demo:green-reset-avocado-salad', 'Activity turn must carry selected SKU');
  assert.equal(activityRequest.body?.view_context?.activity_id, 'green_reset', 'Activity turn must retain activity identity');
  const activityClose = page.getByRole('button', { name: '关闭', exact: true }).last();
  if (await activityClose.isVisible().catch(() => false)) await activityClose.click();
  await screenshot('02-activity-product-selected.png');

  setStage('activity-plan');
  const guideSessionId = await waitUntil(() => sessionIdFromEvidence(), 'real guide session ID');
  const activitySku = 'demo:green-reset-avocado-salad';
  let activitySnapshot = await readGuideSnapshot(guideSessionId, 'activity snapshot before plan');
  if (!activitySnapshot.plan?.items?.some(item => item.sku_id === activitySku)) {
    await sendKekeMessage(
      '请把 GREEN RESET 里的这份牛油果成品沙拉作为唯一商品整理成采购清单，先给我看清单，等我确认后再加购。',
      'activity plan turn',
    );
    activitySnapshot = await readGuideSnapshot(guideSessionId, 'activity plan');
  }
  assert.ok(activitySnapshot.plan?.plan_id, 'Activity must produce a persisted purchase plan');
  assert.ok(activitySnapshot.plan.items.some(item => item.sku_id === activitySku), 'Activity plan must contain selected finished salad SKU');
  await clickPlanCapsuleIfNeeded();
  const activityItemName = activitySnapshot.plan.items.find(item => item.sku_id === activitySku).name;
  await page.getByText(activityItemName, { exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await screenshot('03-activity-plan-before-confirm.png');
  const cartBeforeConfirm = summarizeCart(await publicGet('/api/v1/cart', 'cart before activity confirmation'));
  const initialActivityQuantity = initialCart.items
    .filter(item => item.sku_id === activitySku)
    .reduce((quantity, item) => quantity + item.quantity, 0);
  const activityQuantityBefore = cartBeforeConfirm.items
    .filter(item => item.sku_id === activitySku)
    .reduce((quantity, item) => quantity + item.quantity, 0);
  assert.equal(activityQuantityBefore, initialActivityQuantity, 'Activity selection and planning must not change the activity SKU quantity before explicit confirmation');
  const confirmResponseStart = evidence.api_responses.length;
  await page.getByRole('button', { name: '确认加购', exact: true }).click();
  recordAction('explicitly-confirm-activity-plan', { sku_id: activitySku });
  const confirmResponse = await waitForResponseSince(
    confirmResponseStart,
    item => item.method === 'POST' && /\/api\/v1\/guide\/tasks\/[^/]+\/confirm$/.test(item.path),
    'real plan confirmation response',
  );
  assert.equal(confirmResponse.status, 200, 'Activity plan confirmation must succeed');
  const cartAfterConfirm = summarizeCart(await publicGet('/api/v1/cart', 'cart after activity confirmation'));
  const activityQuantityAfter = cartAfterConfirm.items
    .filter(item => item.sku_id === activitySku)
    .reduce((quantity, item) => quantity + item.quantity, 0);
  assert.ok(activityQuantityAfter > activityQuantityBefore, 'Explicit confirmation must increase the activity SKU quantity in the real cart');
  evidence.business_state.activity = {
    selected_sku_id: activitySku,
    view_context: activityRequest.body.view_context,
    plan: activitySnapshot.plan,
    cart_before_confirm: cartBeforeConfirm,
    cart_after_confirm: cartAfterConfirm,
    confirmation_response: confirmResponse.body,
  };
  await screenshot('04-activity-confirmed-cart.png');

  setStage('independent-checkout');
  await page.getByRole('button', { name: /购物车 \d+ 件/ }).last().click();
  await page.getByRole('button', { name: '结算', exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await page.getByRole('button', { name: '结算', exact: true }).click();
  await page.getByRole('button', { name: '确认结算', exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const checkoutResponseStart = evidence.api_responses.length;
  await page.getByRole('button', { name: '确认结算', exact: true }).click();
  recordAction('independent-cart-checkout');
  await page.getByText('订单已提交', { exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const checkoutResponse = await waitForResponseSince(
    checkoutResponseStart,
    item => item.method === 'POST' && item.path === '/api/v1/cart/checkout',
    'real independent checkout response',
  );
  assert.equal(checkoutResponse.status, 200, 'Independent checkout must succeed');
  await screenshot('05-independent-checkout-success.png');
  const ordersAfterCheckoutRaw = await publicGet('/api/v1/orders', 'orders after checkout');
  const newOrders = (ordersAfterCheckoutRaw.items ?? []).map(summarizeOrder).filter(order => !initialOrderIds.has(order.order_id));
  const placedOrder = newOrders.find(order => order.items.some(item => item.sku_id === activitySku || item.product_id === activitySku));
  assert.ok(placedOrder?.order_id, 'Checkout must create an order containing activity SKU');
  await page.getByText(placedOrder.order_id, { exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  evidence.business_state.checkout = { order: placedOrder, checkout_response: checkoutResponse.body };
  await page.getByRole('button', { name: '继续聊天', exact: true }).click();
  await page.getByPlaceholder('问问可可吧…').waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });

  setStage('real-type-filter-bubbles');
  const cartBeforeBubbles = summarizeCart(await publicGet('/api/v1/cart', 'cart before type/filter exploration'));
  const broadDrink = await sendKekeMessage('买点饮料，两瓶，预算20元', 'broad drink type clarification');
  assert.equal(broadDrink.status, 200, 'Broad drink turn must return a real response');
  const broadPayload = terminalPayload(broadDrink);
  const typeQuestion = (broadPayload?.pending_clarifications ?? []).find(item => item.slot === 'product_type');
  assert.ok(typeQuestion, 'Broad drink query must present a product_type bubble');
  const colaChoice = findOption(typeQuestion, label => label === '可乐', 'drink type');
  await screenshot('06-product-type-bubbles.png');
  const typeRequestStart = turnRequests().length;
  const typeResponseStart = turnResponses().length;
  await clickClarificationBubble(colaChoice.label);
  recordAction('click-product-type-bubble', { label: colaChoice.label, question_id: colaChoice.question_id, option_id: colaChoice.option_id });
  const selectedTypeTurn = await waitForNextTurn(typeResponseStart, 'selected drink type response');
  const selectedTypeRequest = turnRequests()[typeRequestStart];
  assert.ok(selectedTypeRequest, 'Type bubble request must be recorded');
  assert.equal(selectedTypeRequest.body?.clarification_answer?.question_id, colaChoice.question_id, 'Type bubble must retain question_id');
  assert.equal(selectedTypeRequest.body?.clarification_answer?.option_id, colaChoice.option_id, 'Type bubble must retain option_id');
  const selectedTypePayload = terminalPayload(selectedTypeTurn);
  const filterQuestion = (selectedTypePayload?.pending_clarifications ?? []).find(item => item.slot === 'product_filter');
  assert.ok(filterQuestion, 'Cola response must present a product_filter bubble');
  const pepsiChoice = findOption(filterQuestion, label => label === '品牌：百事可乐', 'brand filter');
  const colaCards = selectedTypePayload?.product_cards ?? [];
  assert.ok(colaCards.length >= 2, 'Type selection must show the actual multi-candidate cola list');
  const shownBrands = new Set(colaCards.map(card => card.brand));
  assert.ok(shownBrands.has('可口可乐') && shownBrands.has('百事可乐'), 'Pre-filter candidates must include both actual cola brands');
  await screenshot('07-product-filter-bubbles.png');

  const filterRequestStart = turnRequests().length;
  const filterResponseStart = turnResponses().length;
  await clickClarificationBubble(pepsiChoice.label);
  recordAction('click-product-filter-bubble', { label: pepsiChoice.label, question_id: pepsiChoice.question_id, option_id: pepsiChoice.option_id });
  const filteredTurn = await waitForNextTurn(filterResponseStart, 'filtered beverage response');
  const filterRequest = turnRequests()[filterRequestStart];
  assert.ok(filterRequest, 'Filter bubble request must be recorded');
  assert.equal(filterRequest.body?.clarification_answer?.question_id, pepsiChoice.question_id, 'Filter bubble must retain question_id');
  assert.equal(filterRequest.body?.clarification_answer?.option_id, pepsiChoice.option_id, 'Filter bubble must retain option_id');
  const filteredCards = terminalPayload(filteredTurn)?.product_cards ?? [];
  assert.ok(filteredCards.length > 0, 'Filter answer must return real product cards');
  assert.ok(filteredCards.every(card => card.brand === '百事可乐'), 'Brand filter must leave only Pepsi product cards');
  const cartAfterFilter = summarizeCart(await publicGet('/api/v1/cart', 'cart after type/filter browsing'));
  assert.equal(JSON.stringify(cartAfterFilter), JSON.stringify(cartBeforeBubbles), 'Type/filter browsing must not change the real cart');
  await screenshot('08-filtered-products.png');

  setStage('persist-shopping-plan-for-continuation');
  const selectedCard = filteredCards[filteredCards.length - 1];
  const productButtonStart = turnRequests().length;
  const productTurnStart = turnResponses().length;
  await page.getByRole('button', { name: '选这款，生成清单', exact: true }).last().click();
  recordAction('select-filtered-real-product-card', { sku_id: selectedCard.sku_id, candidate_ref: selectedCard.ref });
  const selectedProductTurn = await waitForNextTurn(productTurnStart, 'filtered product plan turn');
  const selectedProductRequest = turnRequests()[productButtonStart];
  assert.ok(selectedProductRequest?.body?.message?.includes('候选 ' + selectedCard.ref), 'Product-card click must submit displayed candidate ref');
  assert.equal(selectedProductTurn.status, 200, 'Filtered product selection turn must succeed');
  const guideSessionIdForPlan = await waitUntil(() => sessionIdFromEvidence(), 'guide session ID for pending plan');
  const pendingPlanSnapshot = await readGuideSnapshot(guideSessionIdForPlan, 'pending beverage plan before Momo handoff');
  assert.ok(pendingPlanSnapshot.plan?.plan_id, 'Filtered product selection must persist a purchase plan');
  assert.ok(pendingPlanSnapshot.plan.items.some(item => item.sku_id === selectedCard.sku_id), 'Pending plan must retain selected filtered SKU');
  await clickPlanCapsuleIfNeeded();
  const pendingItemName = pendingPlanSnapshot.plan.items.find(item => item.sku_id === selectedCard.sku_id).name;
  await page.getByText(pendingItemName, { exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const cartBeforeMomo = summarizeCart(await publicGet('/api/v1/cart', 'cart before Momo handoff'));
  assert.equal(JSON.stringify(cartBeforeMomo), JSON.stringify(cartBeforeBubbles), 'Unconfirmed plan must remain outside the cart');
  evidence.business_state.pending_keke_plan = pendingPlanSnapshot.plan;
  await screenshot('09-keke-pending-plan-before-momo.png');

  setStage('momo-select-checked-out-order');
  await page.getByRole('button', { name: /售后找我/ }).click();
  recordAction('open-momo-through-keke-entry');
  const momoInput = page.getByPlaceholder('问问墨墨吧…');
  await momoInput.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await page.getByRole('button', { name: /查订单/ }).click();
  const orderChoice = page.getByRole('button', { name: new RegExp(escapedRegExp(placedOrder.order_id)) }).last();
  await orderChoice.waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const selectedOrderRequestStart = evidence.api_requests.length;
  const selectedOrderResponseStart = evidence.api_responses.length;
  await orderChoice.click();
  recordAction('select-actual-checked-out-order', { order_id: placedOrder.order_id });
  await page.getByText('当前咨询订单：', { exact: false }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  assert.ok((await page.locator('body').innerText()).includes(placedOrder.order_id), 'Momo UI must show selected actual order');
  const orderSelectionResponse = await waitForResponseSince(
    selectedOrderResponseStart,
    item => item.method === 'POST' && /\/api\/v1\/mercury\/sessions\/[^/]+\/order$/.test(item.path),
    'Momo actual-order selection response',
  );
  const orderSelectionRequest = requestAfter(
    selectedOrderRequestStart,
    item => item.method === 'POST' && /\/api\/v1\/mercury\/sessions\/[^/]+\/order$/.test(item.path),
  );
  assert.equal(orderSelectionResponse.status, 200, 'Momo must select the actual checked-out order');
  assert.equal(orderSelectionRequest?.body?.order_id, placedOrder.order_id, 'Momo order-selection request must carry actual order ID');

  setStage('momo-real-refund-application');
  const momoTurnStart = turnResponses().length;
  const momoTurnRequestStart = turnRequests().length;
  await momoInput.fill('请帮我为这笔订单申请退款。');
  await momoInput.press('Enter');
  recordAction('request-refund-through-momo-ui', { order_id: placedOrder.order_id });
  const refundTurn = await waitForNextTurn(momoTurnStart, 'Momo refund application and continuation');
  const refundRequest = turnRequests()[momoTurnRequestStart];
  assert.equal(refundTurn.status, 200, 'Momo refund request must return a real stream response');
  assert.equal(refundRequest?.body?.order_id, placedOrder.order_id, 'Momo refund request must carry selected order ID');
  const refundRoute = refundTurn.stream.events.find(event =>
    event.type === 'service.route' && event.payload?.decision_source === 'aftersales_tool_result' && event.payload?.target_role === 'keke',
  );
  assert.ok(refundRoute, 'Keke continuation must be sourced from actual Momo after-sales tool result');
  assert.ok(refundTurn.stream.events.some(event =>
    event.type === 'turn.completed' && String(event.payload?.message ?? '').includes('退款申请已提交，正在处理，还没有到账'),
  ), 'Actual refund tool result must report pending-submission message');
  await page.getByRole('button', { name: '继续选购', exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const visibleMomoText = await visibleGuideBubbles();
  assert.ok(visibleMomoText.some(text => text.includes('退款申请已提交，正在处理，还没有到账')), 'Momo UI must visibly show pending refund result');
  const continuationHandoffId = refundRoute.payload.handoff_id;
  assert.ok(continuationHandoffId, 'Actual after-sales continuation must expose a handoff ID');
  evidence.business_state.refund = {
    order_id: placedOrder.order_id,
    evidence: 'service.route.decision_source=aftersales_tool_result',
    result_message: '退款申请已提交，正在处理，还没有到账',
    pending_status: 'server-reported pending submission',
    handoff_id: continuationHandoffId,
  };
  await screenshot('10-momo-refund-pending-continuation.png');

  setStage('user-accepts-keke-continuation');
  const switchResponseStart = evidence.api_responses.length;
  const switchRequestStart = evidence.api_requests.length;
  await page.getByRole('button', { name: '继续选购', exact: true }).click();
  recordAction('user-clicks-continue-shopping');
  const switchResponse = await waitForResponseSince(
    switchResponseStart,
    item => item.method === 'POST' && /\/api\/v1\/chat\/openings\/[^/]+\/switches\/stream$/.test(item.path),
    'user-approved Keke role-switch response',
  );
  const switchRequest = requestAfter(
    switchRequestStart,
    item => item.method === 'POST' && /\/api\/v1\/chat\/openings\/[^/]+\/switches\/stream$/.test(item.path),
  );
  assert.equal(switchResponse.status, 200, 'User-approved role switch must succeed');
  assert.equal(switchRequest?.body?.accept, true, 'Continuation must wait for explicit user acceptance');
  assert.equal(switchRequest?.body?.target_role, 'keke', 'User acceptance must return to Keke');
  assert.equal(switchRequest?.body?.handoff_id, continuationHandoffId, 'User acceptance must use actual after-sales handoff ID');

  setStage('keke-get-session-restoration');
  const guidePath = '/api/v1/guide/sessions/' + encodeURIComponent(guideSessionId);
  const sessionResponseStart = evidence.api_responses.length;
  await page.getByPlaceholder('问问可可吧…').waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  const restoredSessionResponse = await waitForResponseSince(
    sessionResponseStart,
    item => item.method === 'GET' && item.path === guidePath,
    'real Keke GET session restoration after accepted handoff',
  );
  assert.equal(restoredSessionResponse.status, 200, 'Keke must reload real guide session after handoff');
  const restoredSnapshot = restoredSessionResponse.body;
  assert.ok(restoredSnapshot?.plan?.plan_id, 'GET guide session must restore pending purchase plan');
  assert.equal(restoredSnapshot.plan.plan_id, pendingPlanSnapshot.plan.plan_id, 'GET guide session must restore same pending plan ID');
  assert.ok(restoredSnapshot.plan.items.some(item => item.sku_id === selectedCard.sku_id), 'GET guide session must restore filtered candidate SKU');
  const restoredAssistant = [...(restoredSnapshot.messages ?? [])].reverse().find(message => message.role === 'assistant' && message.content?.trim());
  assert.ok(restoredAssistant, 'GET guide session must include assistant reply after continuation');
  const visibleBubbles = await visibleGuideBubbles();
  const replyFragment = restoredAssistant.content.slice(0, Math.min(18, restoredAssistant.content.length));
  assert.ok(visibleBubbles.some(text => text.includes(replyFragment)), 'Keke continuation reply from GET session must be visible');
  await page.getByRole('button', { name: /采购清单(?: \d+ 件)?/ }).last().click();
  const restoredItemName = restoredSnapshot.plan.items.find(item => item.sku_id === selectedCard.sku_id).name;
  await page.getByText(restoredItemName, { exact: true }).waitFor({ state: 'visible', timeout: UI_TIMEOUT_MS });
  await screenshot('11-keke-reply-and-plan-restored.png');
  evidence.business_state.keke_after_handoff = {
    guide_session_id: guideSessionId,
    visible_assistant_reply: clipped(restoredAssistant.content, 500),
    plan: restoredSnapshot.plan,
    visible_plan_item: restoredItemName,
  };
  evidence.status = 'passed';
  evidence.current_stage = 'complete';
}
async function mainWrapper() {
  evidence.runner_sha256 = sha256(fs.readFileSync(fileURLToPath(import.meta.url)));
  try {
    await main();
  } catch (error) {
    exitCode = 1;
    evidence.status = 'failed';
    evidence.failure = {
      stage: evidence.current_stage,
      type: error?.constructor?.name ?? 'Error',
      message: clipped(credentialRedact(String(error?.message ?? error)), 400),
    };
    if (page) {
      try { await screenshot('failure-' + evidence.current_stage.replace(/[^a-z0-9-]/gi, '-') + '.png'); }
      catch { evidence.screenshot_failure = true; }
    }
  } finally {
    await Promise.race([
      Promise.allSettled(pendingCaptureReads),
      new Promise(resolve => setTimeout(resolve, 2500)),
    ]);
    if (browser) {
      try { await browser.close(); } catch { evidence.browser_close_error = true; }
    }
    try { await persistEvidence(); } catch (error) {
      exitCode = 1;
      process.stderr.write('Could not persist UI evidence: ' + credentialRedact(String(error?.message ?? error)) + '\n');
    }
  }
  process.stdout.write(JSON.stringify({
    status: evidence.status,
    stage: evidence.current_stage,
    actions: evidence.browser_actions.length,
    api_requests: evidence.api_requests.length,
    api_responses: evidence.api_responses.length,
    screenshots: evidence.screenshots.length,
    evidence_file: resolvedEvidenceFile,
    runner_sha256: evidence.runner_sha256,
  }) + '\n');
  if (evidence.status !== 'passed') exitCode = 1;
  process.exitCode = exitCode;
}
await mainWrapper();
