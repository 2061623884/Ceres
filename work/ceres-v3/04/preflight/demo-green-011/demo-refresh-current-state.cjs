const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const demoPath = process.argv[2];
const expectedSourceHash = "a89d73a74c324902d62e50bd4a917404b0c30891518319171fc34d182ea5f61d";
const html = fs.readFileSync(demoPath, "utf8");
const sourceHash = crypto.createHash("sha256").update(html).digest("hex");
assert.equal(sourceHash, expectedSourceHash, "demo source is not the frozen original");
const match = html.match(/<script>([\s\S]*?)<\/script>/i);
assert.ok(match, "existing inline script was not found");
const originalInlineScript = match[1];
const guideId = "guide-existing-42";
const mercuryId = "mercury-existing-12";
const openingId = "opening-existing-9";
const expectedGuide = {
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
  product_cards: []
};
const opening = {
  opening_id: openingId,
  guide_session_id: guideId,
  mercury_session_id: mercuryId,
  role: "keke",
  prompt_displayed: true,
  handoff_id: null
};
const store = new Map([
  ["ceres-v3-opening", openingId],
  ["ceres-v3-role-sessions", JSON.stringify({ guide_session_id: guideId, mercury_session_id: mercuryId })]
]);
const sessionStorage = {
  getItem(key) { return store.has(key) ? store.get(key) : null; },
  setItem(key, value) { store.set(key, String(value)); },
  removeItem(key) { store.delete(key); }
};
const elements = new Map();
for (const id of ["enter", "leave", "role", "order", "suggestion", "history", "message", "send"]) {
  elements.set(id, { id, textContent: "", hidden: id === "suggestion", disabled: false, value: "", dataset: {}, children: [], append(child) { this.children.push(child); }, replaceChildren(...children) { this.children = children; } });
}
elements.get("leave").disabled = html.includes('<button id="leave" disabled');
const roleButtons = ["keke", "momo"].map(role => ({
  dataset: { role },
  textContent: role,
  disabled: html.includes('<button data-role="' + role + '" disabled'),
  onclick: null
}));
const document = {
  body: { dataset: {} },
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, { id, textContent: "", hidden: false, disabled: false, value: "", dataset: {}, children: [], append(child) { this.children.push(child); }, replaceChildren(...children) { this.children = children; } });
    return elements.get(id);
  },
  querySelectorAll(selector) {
    return selector === "[data-role]" ? roleButtons : [];
  },
  createElement(tag) { return { tag, textContent: "", dataset: {}, onclick: null }; },
  createTextNode(text) { return { textContent: text }; }
};
const calls = [];
let turnBody;
let requestCounter = 0;
const jsonResponse = value => ({ ok: true, status: 200, json: async () => value, text: async () => JSON.stringify(value) });
const emptySseResponse = () => ({ ok: true, status: 200, text: async () => "" });
const fetch = async (url, options = {}) => {
  const method = options.method || "GET";
  const call = { url, method, bodyText: options.body };
  if (options.body) {
    try { call.body = JSON.parse(options.body); } catch { call.body = options.body; }
  }
  calls.push(call);
  if (method === "GET" && url === "/api/v1/chat/openings/" + openingId) return jsonResponse(opening);
  if (method === "GET" && url === "/api/v1/guide/sessions/" + guideId) return jsonResponse(expectedGuide);
  if (method === "GET" && url === "/api/v1/orders") return jsonResponse({ items: [] });
  if (method === "POST" && url === "/api/v1/chat/openings/" + openingId + "/turns/stream") {
    turnBody = call.body;
    return emptySseResponse();
  }
  if (method === "DELETE" && url === "/api/v1/chat/openings/" + openingId) return { ok: true, status: 204, text: async () => "" };
  if (method === "POST" && url === "/api/v1/guide/sessions") return jsonResponse(expectedGuide);
  if (method === "POST" && url === "/api/v1/mercury/sessions") return jsonResponse({ session_id: mercuryId, created_at: "2026-10-06T00:00:00Z", selected_order_id: null });
  if (method === "POST" && url === "/api/v1/chat/openings") return jsonResponse(opening);
  if (method === "POST" && url === "/api/v1/chat/openings/" + openingId + "/prompt-displayed") return jsonResponse(opening);
  if (method === "POST" && url === "/api/v1/chat/openings/" + openingId + "/switches/stream") return emptySseResponse();
  throw new Error("Unexpected mocked fetch: " + method + " " + url);
};
const context = {
  document,
  sessionStorage,
  fetch,
  crypto: { randomUUID: () => "request-" + (++requestCounter) },
  console
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(originalInlineScript, context, { filename: "work/ceres-v3/03/demo.html#inline-script" });
(async () => {
  for (let i = 0; i < 10 && elements.get("role").textContent === ""; i++) await new Promise(resolve => setTimeout(resolve, 0));
  elements.get("message").value = "继续查看当前清单";
  await elements.get("send").onclick();
  const guideGet = calls.some(call => call.method === "GET" && call.url === "/api/v1/guide/sessions/" + guideId);
  const openingPosts = calls.filter(call => call.method === "POST" && call.url === "/api/v1/chat/openings").length;
  const openingGetCount = calls.filter(call => call.method === "GET" && call.url === "/api/v1/chat/openings/" + openingId).length;
  const observation = {
    pid: process.pid,
    port: null,
    temporary_server_started: false,
    demo_sha256: sourceHash,
    inline_consumer_sha256: crypto.createHash("sha256").update(originalInlineScript).digest("hex"),
    existing_opening_restored: elements.get("role").textContent === "当前：可可",
    guide_session_response_fixture: expectedGuide,
    guide_get_seen: guideGet,
    opening_post_count_after_reload: openingPosts,
    opening_get_count: openingGetCount,
    turn_request_body: turnBody,
    role_buttons: roleButtons.map(button => ({ role: button.dataset.role, disabled: button.disabled, handler_attached: typeof button.onclick === "function" })),
    leave_button: { disabled: elements.get("leave").disabled, handler_attached: typeof elements.get("leave").onclick === "function" },
    fetch_calls: calls
  };
  process.stdout.write(JSON.stringify(observation) + "\n");
  assert.equal(observation.existing_opening_restored, true, "refresh should restore the current opening");
  assert.equal(observation.opening_post_count_after_reload, 0, "refresh must not create another opening");
  assert.equal(observation.guide_get_seen, true, "refresh must GET the current Guide SessionResponse");
  assert.equal(observation.turn_request_body.expected_task_id, expectedGuide.task_id, "turn must carry the latest Guide task_id");
  assert.equal(observation.turn_request_body.expected_state_version, expectedGuide.state_version, "turn must carry the latest Guide state_version");
  assert.equal(observation.turn_request_body.expected_session_version, expectedGuide.session_version, "turn must carry the latest Guide session_version");
  assert.equal(observation.role_buttons.every(button => !button.disabled), true, "both role buttons should be available after restore");
  assert.equal(observation.leave_button.disabled, false, "leave should be available after restore");
})().catch(error => {
  process.stderr.write(String(error && error.stack || error) + "\n");
  process.exitCode = 1;
});
