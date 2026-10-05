const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");

const demoPath = process.argv[2];
const outputDirectory = process.argv[3];
const expectedDemoHash = "b2c81bdb621249d72163c20b3b4cc6fcca77929c0a229b28b4512b260ba20026";
const html = fs.readFileSync(demoPath, "utf8");
const demoHash = crypto.createHash("sha256").update(html).digest("hex");
assert.equal(demoHash, expectedDemoHash, "demo source is not the frozen green-011 version");
const match = html.match(/<script>([\s\S]*?)<\/script>/i);
assert.ok(match, "demo inline script not found");
const source = match[1];
const extractedPath = require("node:path").join(outputDirectory, "inline-script-under-test.js");
fs.writeFileSync(extractedPath, source, "utf8");

const guideId = "guide-existing-42";
const mercuryId = "mercury-existing-12";
const initialOpeningId = "opening-existing-9";
const guideSession = {
  session_id: guideId,
  task_id: "task-current-73",
  state_version: 7,
  session_version: 11,
  current_step: "planning",
  task_status: "active",
  entry_context: { page: "home", store_id: "store-demo-01", delivery_zone_id: "zone-default" },
  plan: null,
  plan_read_only: false,
  pending_clarifications: [],
  confirmation_result: null,
  message: null,
  available_actions: ["send_message"],
  constraints_summary: {},
  cart_version: null,
  confirmation_id: null,
  history_status: "complete",
  messages: null,
  product_cards: [],
};

const calls = [];
const state = { opening_id: initialOpeningId, role: "keke", nextOpening: 0, closed: new Set() };

function openingView() {
  return {
    opening_id: state.opening_id,
    guide_session_id: guideId,
    mercury_session_id: mercuryId,
    role: state.role,
    prompt_displayed: state.opening_id === initialOpeningId,
    handoff_id: null,
  };
}

function response(status, body) {
  const text = body === undefined ? "" : typeof body === "string" ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return JSON.parse(text); },
    async text() { return text; },
  };
}

function sse(event, payload) {
  return response(200, `data: ${JSON.stringify({ type: event, payload })}\n\n`);
}

async function fetchMock(url, options = {}) {
  const method = options.method || "GET";
  const body = options.body === undefined ? undefined : JSON.parse(options.body);
  assert.equal(options.credentials, "include", "consumer must send same-origin owner credentials");
  calls.push({ method, url, body });

  if (method === "GET" && url === `/api/v1/chat/openings/${state.opening_id}`) {
    if (state.closed.has(state.opening_id)) return response(404, { error: { code: "OPENING_NOT_FOUND" } });
    return response(200, openingView());
  }
  if (method === "GET" && url === `/api/v1/guide/sessions/${guideId}`) return response(200, guideSession);
  if (method === "GET" && url === "/api/v1/orders") return response(200, { items: [] });
  if (method === "POST" && url === "/api/v1/chat/openings") {
    state.nextOpening += 1;
    state.opening_id = `opening-new-${state.nextOpening}`;
    state.role = body.role;
    return response(200, openingView());
  }
  if (method === "POST" && url === `/api/v1/chat/openings/${state.opening_id}/switches/stream`) {
    state.role = body.target_role;
    return sse("service.switch", { status: "resumed", role: state.role });
  }
  if (method === "POST" && url === `/api/v1/chat/openings/${state.opening_id}/turns/stream`) {
    return sse("turn.completed", { message: "新回合完成" });
  }
  if (method === "POST" && url === `/api/v1/chat/openings/${state.opening_id}/prompt-displayed`) {
    return response(200, openingView());
  }
  if (method === "DELETE" && url === `/api/v1/chat/openings/${state.opening_id}`) {
    state.closed.add(state.opening_id);
    return response(204);
  }
  throw new Error(`Unexpected public API request: ${method} ${url}`);
}

function makeElement(tag = "div") {
  return {
    tagName: tag,
    dataset: {},
    textContent: "",
    value: "",
    hidden: false,
    disabled: false,
    children: [],
    onclick: null,
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = [...items]; },
  };
}

const storage = new Map([
  ["ceres-v3-opening", initialOpeningId],
  ["ceres-v3-role-sessions", JSON.stringify({ guide_session_id: guideId, mercury_session_id: mercuryId })],
]);

function createPage() {
  const elements = new Map(["enter", "leave", "role", "order", "suggestion", "history", "message", "send"].map(id => [id, makeElement()]));
  const roleButtons = ["keke", "momo"].map(role => {
    const button = makeElement("button");
    button.dataset.role = role;
    button.disabled = true;
    return button;
  });
  const document = {
    getElementById(id) { return elements.get(id); },
    querySelectorAll(selector) { assert.equal(selector, "[data-role]"); return roleButtons; },
    createElement(tag) { return makeElement(tag); },
    createTextNode(text) { return { textContent: text }; },
  };
  const context = vm.createContext({
    document,
    sessionStorage: {
      getItem(key) { return storage.has(key) ? storage.get(key) : null; },
      setItem(key, value) { storage.set(key, String(value)); },
      removeItem(key) { storage.delete(key); },
    },
    fetch: fetchMock,
    crypto,
    Promise,
    JSON,
    Error,
    requestAnimationFrame(callback) { return Promise.resolve().then(callback); },
  });
  vm.runInContext(source, context, { filename: "demo-inline-consumer.js" });
  return { elements, roleButtons };
}

async function settle() {
  for (let index = 0; index < 5; index += 1) await new Promise(resolve => setTimeout(resolve, 0));
}

async function main() {
  const firstPage = createPage();
  await settle();
  assert.equal(firstPage.elements.get("role").textContent, "当前：可可");
  assert.equal(calls.filter(call => call.method === "GET" && call.url === `/api/v1/guide/sessions/${guideId}`).length, 1);
  assert.equal(calls.filter(call => call.method === "POST" && call.url === "/api/v1/chat/openings").length, 0);
  assert.equal(firstPage.roleButtons.every(button => !button.disabled), true);
  assert.equal(firstPage.elements.get("leave").disabled, false);

  await firstPage.roleButtons.find(button => button.dataset.role === "momo").onclick();
  assert.equal(state.role, "momo");
  assert.equal(firstPage.elements.get("role").textContent, "当前：墨墨");
  assert.equal(calls.filter(call => call.method === "POST" && call.url.endsWith("/turns/stream")).length, 0);

  const openingGetsBeforeRefresh = calls.filter(call => call.method === "GET" && call.url === `/api/v1/chat/openings/${state.opening_id}`).length;
  const refreshPage = createPage();
  await settle();
  assert.equal(refreshPage.elements.get("role").textContent, "当前：墨墨", "refresh restores the current role");
  assert.equal(calls.filter(call => call.method === "POST" && call.url === "/api/v1/chat/openings").length, 0, "refresh must not create a new opening");
  assert.equal(calls.filter(call => call.method === "GET" && call.url === `/api/v1/chat/openings/${state.opening_id}`).length, openingGetsBeforeRefresh + 1);

  await refreshPage.roleButtons.find(button => button.dataset.role === "keke").onclick();
  assert.equal(state.role, "keke");
  assert.equal(refreshPage.elements.get("role").textContent, "当前：可可");
  const switchPosts = calls.filter(call => call.method === "POST" && call.url.endsWith("/switches/stream"));
  assert.deepEqual(switchPosts.map(call => call.body.target_role), ["momo", "keke"]);
  assert.equal(switchPosts.some(call => JSON.stringify(call.body).includes("继续查看当前清单")), false, "role-only switch must not replay a previous turn");
  assert.equal(calls.filter(call => call.method === "POST" && call.url.endsWith("/turns/stream")).length, 0);

  refreshPage.elements.get("message").value = "继续查看当前清单";
  await refreshPage.elements.get("send").onclick();
  const turnPosts = calls.filter(call => call.method === "POST" && call.url.endsWith("/turns/stream"));
  assert.equal(turnPosts.length, 1, "only the newly entered user turn should be sent");
  assert.equal(turnPosts[0].body.message, "继续查看当前清单");
  assert.equal(turnPosts[0].body.expected_task_id, guideSession.task_id);
  assert.equal(turnPosts[0].body.expected_state_version, guideSession.state_version);
  assert.equal(turnPosts[0].body.expected_session_version, guideSession.session_version);

  const oldOpening = state.opening_id;
  const roleSessionsBeforeLeave = storage.get("ceres-v3-role-sessions");
  await refreshPage.elements.get("leave").onclick();
  assert.ok(state.closed.has(oldOpening));
  assert.equal(storage.has("ceres-v3-opening"), false);
  assert.equal(storage.get("ceres-v3-role-sessions"), roleSessionsBeforeLeave, "leave retains both role session IDs");

  await refreshPage.elements.get("enter").onclick();
  assert.notEqual(state.opening_id, oldOpening, "explicit re-entry creates a new opening cycle");
  assert.equal(storage.get("ceres-v3-opening"), state.opening_id);
  assert.equal(storage.get("ceres-v3-role-sessions"), roleSessionsBeforeLeave);
  assert.equal(calls.filter(call => call.method === "POST" && call.url === "/api/v1/chat/openings").length, 1);
  assert.equal(calls.filter(call => call.method === "POST" && call.url === "/api/v1/guide/sessions").length, 0);
  assert.equal(calls.filter(call => call.method === "POST" && call.url === "/api/v1/mercury/sessions").length, 0);

  process.stdout.write(JSON.stringify({
    pid: process.pid,
    port: null,
    temporary_server_started: false,
    demo_sha256: demoHash,
    inline_script_sha256: crypto.createHash("sha256").update(source).digest("hex"),
    extracted_inline_script: extractedPath,
    opening_restored_without_recreation: true,
    guide_get_calls: calls.filter(call => call.method === "GET" && call.url === `/api/v1/guide/sessions/${guideId}`).length,
    roles_available_after_restore: refreshPage.roleButtons.map(button => ({ role: button.dataset.role, disabled: button.disabled })),
    manual_switches_without_old_turn_replay: switchPosts.length === 2 && turnPosts.length === 1,
    sent_turn_body: turnPosts[0].body,
    leave_closed_old_opening_and_retained_sessions: true,
    reentry_opening_id: state.opening_id,
    request_count: calls.length,
    requests: calls,
  }) + "\n");
}

main().catch(error => {
  process.stderr.write(String(error && error.stack || error) + "\n");
  process.exitCode = 1;
});
