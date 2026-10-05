const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const demoPath = process.argv[2];
const html = fs.readFileSync(demoPath, "utf8");
const matched = html.match(/<script>([\s\S]*?)<\/script>/i);
if (!matched) throw new Error("Could not extract the existing demo inline script");
const consumer = matched[1];
const route = { decision: "clarify", prompt_mode: "fixed_entry", route_ms: 12, handoff_id: "diagnostic-handoff" };
const completed = { message: "请补充说明", business_not_run: true };
const sse = [
  "event: service.route",
  "data: " + JSON.stringify(route),
  "",
  "event: turn.completed",
  "data: " + JSON.stringify(completed),
  "",
  ""
].join("\r\n");
const elements = new Map();
for (const id of ["enter", "leave", "role", "order", "suggestion", "history", "message", "send"]) {
  elements.set(id, { id, textContent: "", hidden: true, disabled: false, value: "", dataset: {}, append() {}, replaceChildren() {} });
}
const document = {
  body: { dataset: {} },
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, { id, textContent: "", hidden: false, disabled: false, value: "", dataset: {}, append() {}, replaceChildren() {} });
    return elements.get(id);
  },
  querySelectorAll() { return []; },
  createElement(tag) { return { tag, textContent: "", dataset: {}, onclick: null }; },
  createTextNode(text) { return { textContent: text }; }
};
const fetchCalls = [];
const context = {
  document,
  sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  fetch: async (url, options) => {
    fetchCalls.push({ url, method: (options && options.method) || "GET" });
    return { ok: true, json: async () => ({ opening_id: "demo-opening", role: "keke" }), text: async () => "" };
  },
  console
};
context.globalThis = context;
vm.createContext(context);
const sourceLine = consumer.split(/\r?\n/).find(line => line.includes("async function consume"));
const instrumented = consumer +
  "\nchat = { opening_id: 'demo-opening', role: 'keke' };" +
  "\nthis.__consumerPromise = consume({ text: async () => " + JSON.stringify(sse) + " });";
vm.runInContext(instrumented, context, { filename: "work/ceres-v3/03/demo.html#inline-consumer" });
context.__consumerPromise.then(() => {
  const rendered = elements.get("history").textContent;
  const routeSeen = rendered.includes("路由：clarify，12 ms");
  const completedSeen = rendered.includes("请补充说明");
  assert.equal(routeSeen, true, "real demo consumer did not render service.route");
  assert.equal(completedSeen, true, "real demo consumer did not render turn.completed");
  assert.equal(fetchCalls.length, 1, "expected only the mocked opening GET from sync()");
  process.stdout.write(JSON.stringify({
    pid: process.pid,
    port: null,
    temporary_server_started: false,
    route_seen: routeSeen,
    turn_completed_seen: completedSeen,
    rendered_history: rendered,
    fetch_calls: fetchCalls,
    source_sha256: crypto.createHash("sha256").update(html).digest("hex"),
    extracted_consumer_sha256: crypto.createHash("sha256").update(consumer).digest("hex"),
    consume_source_line: sourceLine,
    consume_line_backslash_count: [...sourceLine].filter(char => char === "\\").length,
    mode: "Node vm with a minimal DOM and mocked opening GET; the exact existing consumer function was executed against a standard CRLF SSE response; no live backend/model/API."
  }) + "\n");
}).catch(error => {
  process.stderr.write(String(error && error.stack || error) + "\n");
  process.exitCode = 1;
});
