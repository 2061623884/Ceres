const fs = require("node:fs");
const crypto = require("node:crypto");
const inputPath = process.argv[2];
const outputPath = process.argv[3];
const html = fs.readFileSync(inputPath, "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/i);
if (!match) throw new Error("Could not find the existing inline demo script");
const demoScript = match[1];
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
const prefix = "window.fetch = async function () { return new Response('{\"opening_id\":\"demo-opening\",\"role\":\"keke\"}', { status: 200, headers: { 'Content-Type': 'application/json' } }); };\n";
const suffix = "\nchat = { opening_id: 'demo-opening', role: 'keke' };\n(async function () {\n  try {\n    await consume(new Response(" + JSON.stringify(sse) + ", { headers: { 'Content-Type': 'text/event-stream' } }));\n    const rendered = document.getElementById('history').textContent;\n    const routeSeen = rendered.includes('路由：clarify，12 ms');\n    const completedSeen = rendered.includes('请补充说明');\n    document.body.dataset.routeSeen = String(routeSeen);\n    document.body.dataset.completedSeen = String(completedSeen);\n    document.getElementById('result').textContent = JSON.stringify({ routeSeen, completedSeen, rendered });\n    document.title = 'CONSUMER:' + routeSeen + ':' + completedSeen;\n  } catch (error) {\n    document.body.dataset.consumerError = String(error && error.stack || error);\n    document.title = 'CONSUMER_ERROR';\n  }\n})();\n";
const shell = "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>consumer harness</title><body>" +
  "<button id=\"enter\"></button><button id=\"leave\"></button><b id=\"role\"></b>" +
  "<button data-role=\"keke\"></button><button data-role=\"momo\"></button>" +
  "<select id=\"order\"></select><div id=\"suggestion\"></div><pre id=\"history\"></pre>" +
  "<input id=\"message\"><button id=\"send\"></button><pre id=\"result\"></pre>" +
  "<script>" + prefix + demoScript + suffix + "</script></body></html>";
fs.writeFileSync(outputPath, shell, "utf8");
process.stdout.write(JSON.stringify({
  demo_sha256: crypto.createHash("sha256").update(html).digest("hex"),
  extracted_consumer_sha256: crypto.createHash("sha256").update(demoScript).digest("hex"),
  generated_harness_sha256: crypto.createHash("sha256").update(shell).digest("hex"),
  line9_literal_backslashes: (demoScript.split(/\r?\n/)[8].match(/\\/g) || []).length,
  line12_literal_backslashes: (demoScript.split(/\r?\n/)[11].match(/\\/g) || []).length
}) + "\n");
