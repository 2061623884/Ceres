"""One paired replay of the frozen actual R02 policy-answer request; evaluator only."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

import httpx
from app.core.config import get_settings
from app.prompts.semantic import POLICY_SYSTEM_PROMPT, POLICY_COMPLETE_PROMPT

root = Path(__file__).resolve().parents[3]
source = root / "work/ceres-v3/05/evidence/candidate-v5-20261005T230721Z-y3rsbooc/role-sampling/role-samples/R02.json"
destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
receipt = json.loads(source.read_text(encoding="utf-8"))
row = receipt["upstream"][-1]
before = json.loads(row["request_body"])
assert len(before["messages"]) == 3 and "一般政策检索已完成" in before["messages"][0]["content"]
after = copy.deepcopy(before)
protocol = before["messages"][0]["content"].split("\nprotocol:\n", 1)[1]
after["messages"][0]["content"] = POLICY_SYSTEM_PROMPT + POLICY_COMPLETE_PROMPT + "\nprotocol:\n" + protocol
settings = get_settings()
assert before["model"] == settings.llm_model and before["max_tokens"] == settings.llm_max_output_tokens == 3072
assert row["url"] == settings.openai_base_url.rstrip("/") + "/chat/completions"
assert before["temperature"] == after["temperature"] == 0.3
records = []
try:
    with httpx.Client(timeout=settings.llm_timeout) as client:
        for name, payload in (("baseline", before), ("candidate", after)):
            record = {"name": name, "request": payload, "system_chars": len(payload["messages"][0]["content"]), "scope": "one complete upstream HTTP response; not complete API, browser or TTFT"}
            records.append(record)
            started = time.perf_counter()
            response = client.post(row["url"], json=payload, headers={"Authorization": "Bearer " + settings.openai_api_key})
            record.update(http_status=response.status_code, raw_response=response.text, upstream_wall_ms=(time.perf_counter()-started)*1000)
            response.raise_for_status()
            record["response"] = response.json()
except Exception as exc:
    records[-1].update(error_type=type(exc).__name__, error=str(exc))
    raise
finally:
    data = {"source_receipt": str(source.relative_to(root)), "source_receipt_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "variable": "only policy-answer system message; all other request fields unchanged", "remote_weight_revision": "not exposed by provider; no immutable weight claim", "records": records}
    raw = (json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode("utf-8")
    (destination / "comparison.json").write_bytes(raw)
    (destination / "comparison.sha256").write_text(hashlib.sha256(raw).hexdigest()+"\n", encoding="utf-8")
