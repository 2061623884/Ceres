"""Create an acceptance record from completed API, UI and diagnostic artifacts."""
import argparse
from collections import Counter
import json
from pathlib import Path

import eval_v4 as evaluation


def usage(calls):
    reported = [call.get("usage") or call.get("kev_response", {}).get("usage") for call in calls]
    fields = {"input_tokens": ("input_tokens", "prompt_tokens"), "output_tokens": ("output_tokens", "completion_tokens"),
              "total_tokens": ("total_tokens",)}
    result = {"calls": len(calls), "calls_with_usage": sum(isinstance(row, dict) for row in reported)}
    for name, aliases in fields.items():
        values = [next((row[key] for key in aliases if isinstance(row.get(key), int)), None) if isinstance(row, dict) else None for row in reported]
        known = [value for value in values if value is not None]
        result[name] = {"coverage": len(known), "reported_sum": sum(known) if known else None}
    pairs = [(row.get("input_tokens", row.get("prompt_tokens")), row.get("output_tokens", row.get("completion_tokens"))) for row in reported if isinstance(row, dict)]
    known_pairs = [(left, right) for left, right in pairs if isinstance(left, int) and isinstance(right, int)]
    result["input_plus_output"] = {"coverage": len(known_pairs), "derived_sum": sum(left + right for left, right in known_pairs) if known_pairs else None}
    timings = [call["request_latency_ms"] for call in calls if isinstance(call.get("request_latency_ms"), (int, float))]
    result["request_latency_ms"] = {"coverage": len(timings), "p50": evaluation.percentile(timings, .5),
                                    "p95": evaluation.percentile(timings, .95), "max": max(timings) if timings else None}
    reasoning = [(row.get("completion_tokens_details") or {}).get("reasoning_tokens") for row in reported if isinstance(row, dict)]
    known_reasoning = [value for value in reasoning if isinstance(value, int)]
    result["reasoning_tokens"] = {"coverage": len(known_reasoning), "reported_sum": sum(known_reasoning) if known_reasoning else None}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--ui", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--probe", required=True, action="append", help="Preserved failed one-call diagnostic probe directory; repeat for both probes")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source, ui_path, diagnostics, output = map(lambda value: Path(value).resolve(), (args.source, args.ui, args.diagnostics, args.output))
    manifest = evaluation.read(source / "manifest.json")
    summary = evaluation.read(source / "summary.json")
    records = [(item, evaluation.read(source / item["execution_id"] / "result.json")) for item in manifest["schedule"]]
    if any(record["status"] in ("preparing", "running") for _, record in records):
        raise ValueError("API batch is still running")
    ui = evaluation.read(ui_path)
    if ui["product_head"] != manifest["product_head"] or ui["runtime_identity"]["product_head"] != manifest["product_head"]:
        raise ValueError("UI candidate differs from API candidate")
    ui_assertions = []
    for journey in ui["journeys"]:
        if journey["status"] != "passed":
            ui_assertions.append({"name": journey["name"], "additional_plan_assertions": "not_reached"})
            continue
        guide = journey["plan_before_confirm"]
        selected = [item for item in guide["plan"]["items"] if item["selected"]]
        checks = {"line_totals": all(item["line_total_fen"] == item["quantity"] * item["unit_price_fen"] for item in selected),
                  "selected_total": guide["plan"]["selected_total_fen"] == sum(item["line_total_fen"] for item in selected)}
        if journey["name"] == "snack-bubble":
            checks["budget"] = guide["constraints_summary"]["budget_fen"] == 2000
        if not all(checks.values()):
            raise ValueError("Recorded UI pass contradicts completed plan assertions")
        ui_assertions.append({"name": journey["name"], "additional_plan_assertions": checks, "basis": "offline retained state, no browser rerun"})
    diagnosed = [evaluation.read(diagnostics / (item["execution_id"] + ".json")) for item, _ in records]
    probes = [(Path(value).resolve(), evaluation.read(Path(value).resolve() / "R01-r1.json")) for value in args.probe]
    probe_modes = []
    for probe_path, probe in probes:
        if probe["source_result_sha256"] != evaluation.read(source / "R01-r1" / "result.json")["source_scoring_result"]["sha256"]:
            raise ValueError("Failed probe belongs to a different source result")
        request = probe["request"]
        if request.get("enable_thinking") is False:
            probe_modes.append("enable_thinking=false")
        elif request.get("chat_template_kwargs", {}).get("enable_thinking") is False:
            probe_modes.append("chat_template_kwargs.enable_thinking=false")
        else:
            raise ValueError("Expected a preserved thinking-parameter probe")
        if len(probe["calls"]) != 1 or probe["result"]["verdict"] != "unknown":
            raise ValueError("Expected a preserved one-call failed probe")
        probe_call = probe["calls"][0]
        if probe_call["response_choices"][0]["finish_reason"] != "length" or probe_call["usage"]["completion_tokens_details"]["reasoning_tokens"] != request["max_tokens"]:
            raise ValueError("Probe does not substantiate the reported exhausted reasoning budget")
    if sorted(probe_modes) != sorted(["enable_thinking=false", "chat_template_kwargs.enable_thinking=false"]):
        raise ValueError("Both distinct failed parameter probes are required")
    for (item, api_row), row in zip(records, diagnosed):
        parent = api_row["source_scoring_result"]
        if row["source_result_sha256"] != parent["sha256"] or evaluation.digest(parent["path"]) != parent["sha256"]:
            raise ValueError("Diagnostic source hash mismatch")
    output.mkdir()  # New derived record; original reports/results are immutable.
    components = {name: usage([call for _, row in records for call in row["model_calls"].get(name, [])])
                  for name in ("role", "mercury", "kev", "background_memory")}
    components["original_judge"] = usage([call for _, row in records for call in row["judge"]["calls"]])
    components["diagnostic_judge"] = usage([call for row in diagnosed for call in row["calls"]])
    components["failed_probe_judge"] = usage([call for _, probe in probes for call in probe["calls"]])
    timed = [(item["execution_id"], step) for item, row in records for step in row.get("steps", [])
             if step["op"] in ("turn", "select_pending_option", "switch")]
    failed = [{"execution_id": item["execution_id"], "case_id": item["case_id"], "group": item["group"],
               "business_status": row["status"], "performance_passed": row["performance_passed"],
               "failure_stages": [{"label": step["label"], "status": step["status"],
                                   "failed_checks": [check for check in step.get("checks", []) if not check["passed"]],
                                   "error": step.get("error")} for step in row.get("steps", []) if step["status"] != "passed"],
               "slow_turns": [{"label": step["label"], "elapsed_ms": step["elapsed_ms"]} for step in row.get("steps", [])
                              if step["op"] in ("turn", "select_pending_option", "switch") and step["elapsed_ms"] > 15000],
               "critical_violations": row.get("critical_violations", []), "error": row.get("error")}
              for item, row in records if row["status"] != "passed" or not row["performance_passed"]]
    verdicts = dict(Counter(row["result"]["verdict"] for row in diagnosed))
    record = {"product_head": manifest["product_head"], "source_manifest_sha256": evaluation.digest(source / "manifest.json"),
              "source_summary_sha256": evaluation.digest(source / "summary.json"), "ui_result_sha256": evaluation.digest(ui_path),
              "diagnostic_manifest_sha256": evaluation.digest(diagnostics / "manifest.json"), "reporter_sha256": evaluation.digest(__file__),
              "failed_probes": [{"directory": str(probe_path), "result_sha256": evaluation.digest(probe_path / "R01-r1.json"),
                                 "manifest_sha256": evaluation.digest(probe_path / "manifest.json"), "verdict": probe["result"]["verdict"],
                                 "parameter": mode} for (probe_path, probe), mode in zip(probes, probe_modes)],
              "execution_sha256": {item["execution_id"]: {"api": evaluation.digest(source / item["execution_id"] / "result.json"),
                                                         "diagnostic_source_api": api_row["source_scoring_result"],
                                                         "diagnostic": evaluation.digest(diagnostics / (item["execution_id"] + ".json"))} for item, api_row in records},
              "source": str(source), "ui": str(ui_path), "diagnostics": str(diagnostics), "api": summary,
              "ui_acceptance": ui["automatic_browser_acceptance"], "ui_journeys": [
                  {**{key: row[key] for key in ("name", "status", "stage", "performance_passed")}, "error": row.get("error"),
                   "slow_steps": [{"label": step["label"], "final_reply_ms": step["final_reply_ms"]} for step in row["steps"] if step["final_reply_ms"] > 15000],
                   "failed_action_codes": [action["code"] for step in row["steps"] for event in step["events"] if event["type"] == "turn.completed"
                                           for action in event["payload"]["action_results"] if action["status"] == "failed"]}
                  for row in ui["journeys"]],
              "ui_assertion_review": ui_assertions,
              "automatic_acceptance": "passed" if summary["automatic_acceptance"] == "passed" and ui["automatic_browser_acceptance"] == "passed" else "not_passed",
              "observed_critical_violations": summary["critical_violation_count"], "free_text_factual_error_count": None,
              "turns_within_15s": sum(step["elapsed_ms"] <= 15000 for _, step in timed), "timed_turns": len(timed),
              "diagnostic_verdicts": verdicts, "diagnostic_errors": sum("error" in row for row in diagnosed),
              "usage": components, "failures": failed, "money_cost": None, "human_evaluation": "not_evaluated",
              "limitations": ["lexical only; hybrid not evaluated", "API first useful result time unknown (TestClient buffers SSE)",
                              "UI timing is action start to fully received completed SSE; final text render latency not sampled",
                              "Final UI subtotal/budget assertions added after run-02; passed plan checked offline, failed snack plan not reached",
                              "Same-model semantic judge uncalibrated; diagnostics do not alter business/latency scores",
                              "Diagnostic replay uses run-03 inputs; R14/R17 pilot hints predate correction and R17/H03/H12 hints predate completed assertions",
                              "Judge inputs include business state/catalog facts but omit captured policy/retrieval requests; grounding findings are incomplete diagnostics",
                              "Token sums have explicit coverage; no verified price and no UI provider usage capture",
                              "Observable deterministic critical violations do not establish zero free-text factual errors",
                              "Original failed HTTP status may lack response body; see available state/trace, do not invent error code"]}
    evaluation.write(output / "acceptance.json", record)
    evaluation.write(output / "failures.json", failed)
    lines = ["# Ceres1 V4 自动验收记录", "", f"**结论：{'通过' if record['automatic_acceptance'] == 'passed' else '未通过'}。** 产品候选 `{manifest['product_head']}`；人工评测未执行。", "",
             f"60 场景、100 次计划执行；实际 {summary['actual_executions']} 次。业务达标 {summary['counts']['passed']}/100，同时满足业务与性能 {summary['fully_passed']}/100；核心三次均达标 {summary['core_pass3']['passed']}/20。",
             f"确定性检查发现关键违规 {summary['critical_violation_count']}；自由文本事实错误总数未知，不据此宣称全部事实正确。准备失败 {summary['counts']['preparation_failed']}、脚本失败 {summary['counts']['runner_failed']}、未执行 {summary['counts']['not_executed']}。",
             f"最终回复 ≤15 秒：{record['turns_within_15s']}/{len(timed)} 回合。P50 {summary['reply_latency_ms']['p50']}ms、P95 {summary['reply_latency_ms']['p95']}ms、最大 {summary['reply_latency_ms']['max']}ms。", "",
             "| 分组 | 执行 | 业务达标 | 业务与性能达标 |", "|---|---:|---:|---:|"]
    lines += [f"| {group} | {counts['planned']} | {counts['business_passed']} | {counts['fully_passed']} |" for group, counts in summary["groups"].items()]
    lines += ["", f"正常完成 {summary['normal_completion']['business_passed']}/{summary['normal_completion']['planned']}；合规拒绝 {summary['compliant_refusal']['business_passed']}/{summary['compliant_refusal']['planned']}。",
              f"生成可确认清单的执行 {summary['hard_constraints']['produced_plan_executions']} 次，其中硬约束全部满足 {summary['hard_constraints']['all_satisfied']} 次；该分母只包含已生成清单的执行，未生成清单仍在总执行分母内。", "",
              "## 浏览器与组件", "", "API 100 次与下列两条浏览器旅程分别统计；浏览器使用候选真实前后端、独立数据库和真实模型。", ""]
    lines += [f"- {row['name']}：业务 {row['status']}；性能 {row['performance_passed']}；阶段 {row['stage']}；失败动作码 {', '.join(row['failed_action_codes']) or '无'}；超时 {json.dumps(row['slow_steps'], ensure_ascii=False)}。" for row in record["ui_journeys"]]
    lines += ["", "最终审查补足确认前清单小计/选中总额和零食预算断言；专题成功清单用已捕获状态离线核对，零食未到清单阶段仍保留失败，不冒称新脚本已重跑浏览器。检查见 acceptance.json 的 ui_assertion_review。"]
    lines += ["", "记忆场景包含显式写入/更正/删除/跨会话、owner 隔离、当前需求覆盖记忆、临时预算提取与 Dream。Dream 的初始记忆和内部触发属于组件验证；逐步前后状态、后台调用与 trace 在 API 结果中保留。", "",
              "## 裁判与调用", "", f"原裁判多次输出 content=null/finish_reason=length，全部记录保留。顶层 enable_thinking=false 与 chat_template_kwargs.enable_thinking=false 的两个单条探针均耗尽 1200 推理 token、无可见 JSON，单列失败探针调用。最终诊断仅重放已捕获请求，将 max_tokens 调整为候选有效配置的 3072，保持推理配置不变，保存实际序列化请求与响应，不执行产品任务。诊断分布 {json.dumps(verdicts, ensure_ascii=False)}，调用/解析错误 {record['diagnostic_errors']}；未人工校准、同模型，均不作硬门槛。", "",
              "历史参数探针参考 [Qwen 官方部署文档](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md)；该端点框架未独立确认，本次探针未证明关闭推理生效。重放保留 run-03 原始评分提示，R14/R17 首批提示早于离线纠正，R17/H03/H12 提示早于补足 SKU/数量/金额断言，语义发现须结合最终业务记录复核。裁判输入有业务状态和商品事实，但未包含已捕获的政策/检索调用请求，不能用 grounding 判分证明这些回答已经与实际来源逐项核对；原始调用另在执行批次保留。", "",
              "| 组件 | 调用 | 有 usage | 输入 token / 覆盖调用 | 输出 token / 覆盖调用 |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {name} | {value['calls']} | {value['calls_with_usage']} | {value['input_tokens']['reported_sum']} / {value['input_tokens']['coverage']} | {value['output_tokens']['reported_sum']} / {value['output_tokens']['coverage']} |" for name, value in components.items()]
    lines += ["", "金额成本未知；不同供应商的原始 total_tokens 与 input+output 派生和分别保留，缺失不能按零估算。", "",
              "## 失败与证据", "", "以下失败按实际阶段归档，不推断根因。复跑须使用原批次 badcases.json 的独立输出目录和冻结候选；不会自动重跑。", "",
              "| 执行 | 业务 | 失败阶段 | 超时回合 |", "|---|---|---|---|"]
    lines += [f"| {row['execution_id']} | {row['business_status']} | {', '.join(step['label'] for step in row['failure_stages']) or '—'} | {', '.join(step['label'] for step in row['slow_turns']) or '—'} |" for row in failed]
    lines += ["", "完整分项与摘要见 [acceptance.json](acceptance.json)、[failures.json](failures.json)；原始 API、UI、诊断的绝对路径和来源 SHA256 均在 acceptance.json 内。产品修复任务见 [总 TASK](../../../tasks/ceres-v4-evaluation.md)。", "",
              "## 条件与限制", ""]
    lines += ["- " + limitation for limitation in record["limitations"]]
    (output / "acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"automatic_acceptance": record["automatic_acceptance"], "actual_executions": summary["actual_executions"], "failures": len(failed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
