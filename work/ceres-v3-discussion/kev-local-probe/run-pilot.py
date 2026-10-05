"""Small deployment pilot, not an independent acceptance evaluation."""
import json
import pathlib
import time
import urllib.request

probe_root = pathlib.Path(__file__).resolve().parent
cases = json.loads((probe_root / "chinese-pilot.json").read_text(encoding="utf-8"))
with (probe_root / "pilot-results.jsonl").open("w", encoding="utf-8") as output:
    for case in cases:
        payload = {
            "state": case["state"], "model": "kev-latest",
            "questions": {"service": {
                "type": "choice",
                "instructions": "根据本轮发言、当前角色、指向对象和近期相关对话，判断业务服务归属。可可负责选购、比较、采购清单；墨墨负责具体订单查询、订单资格判断、售后操作。一般退货、退款、配送政策咨询两角色均可回答。明确的新诉求优先于旧话题；当前角色能够处理则继续，明确需要另一角色才建议切换；上下文仍不足才澄清。只判断，不执行业务或自动跳转。",
                "criteria": {
                    "stay_current": "当前角色能承接，继续当前服务",
                    "suggest_switch": "诉求明确且需要另一角色处理，建议用户切换",
                    "clarify": "上下文仍不能确定指向的对象或业务意图，留在原聊天澄清",
                },
            }},
        }
        request = urllib.request.Request(
            "http://127.0.0.1:8009/v1/systemone",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
        wall_ms = round((time.perf_counter() - started) * 1000, 1)
        result = {
            "id": case["id"], "expected": case["expected"],
            "matches_expected": body["answers"]["service"]["choice"] == case["expected"],
            "wall_ms": wall_ms, "request": payload, "response": body,
        }
        output.write(json.dumps(result, ensure_ascii=False) + "\n")
        output.flush()
        print(json.dumps({key: result[key] for key in ("id", "expected", "matches_expected", "wall_ms")}), flush=True)
