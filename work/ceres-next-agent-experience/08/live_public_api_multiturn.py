"""Finite Ceres Next 08 live API evidence runner.

Uses existing public API routes, actual configured Kev/Qwen services, and the
04 safe model-payload capture boundary. No model call is retried. --cases-file
is a root-authorized fixed operation list; do not inspect holdout data before
root's separate gate.

Allowed operations: turn, select_pending_option, switch, replay_switch,
select_order, confirm_plan, checkout, snapshot. Cases may set initial_role,
entry_context and an actual aftersales_expectation; turns may carry view_context.
A step may carry a narrow expect object for route, pending slots/options,
product cards, plan and cart/order snapshots. aftersales_expectation is
{"tool":"create_refund"|"create_return","result":"pending"|"failed"}.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx

BASE_SOURCE_COMMIT="e5f80f3635fb1ef9cfbaa62ece3e621637c30733"  # product source freeze
FROZEN_INPUTS={
 "data/fixtures/demo-products.json":"2b3f4a98461e4c5eea7369f426a506b2f36707014d14153ad31fbb27ae6f6361",
 "data/fixtures/store-offers.json":"b29b9491ba34f6f0f8ef8e9fb3acae314f092b5abf242809fefce8cfa0ccb16f",
}
SOURCE_FILES=("backend/app/api/chat.py","backend/app/agent/graph/nodes/capability.py",
 "backend/app/agent/graph/nodes/workflow.py","backend/app/agent/turn_context_plan.py",
 "backend/app/prompts/semantic.py","backend/app/llm/kev_provider.py",
 "backend/app/llm/embedding.py","Mercury/mercury/prompt.py","frontend/src/App.tsx")
PUBLIC_CASES=[
 {"case_id":"snack_broad_then_type_bubble","steps":[
                {"op":"turn","label":"broad-snack","message":"来点零食","expect":{"pending_slots":["product_type"],"minimum_options":2,"plan_present":False,"cart_unchanged":True,"trace_capability":"category_exploration"}},
  {"op":"select_pending_option","label":"select-chips-type","slot":"product_type","label_contains":"薯片","message":"薯片",
   "expect":{"pending_slots":[],"plan_present":False,"cart_unchanged":True,"trace_branch":"direct_product_type_workflow"}}]},
 {"case_id":"drink_multisku_attribute_filter_explicit_purchase","steps":[
  {"op":"turn","label":"broad-drinks","message":"买点饮料，两瓶，预算20元","expect":{"pending_slots":["product_type"],"minimum_options":2,"plan_present":False,"cart_unchanged":True,"trace_capability":"purchase_modify"}},
  {"op":"select_pending_option","label":"select-cola-type","slot":"product_type","label_equals":"可乐","message":"可乐",
   "expect":{"pending_slots":["product_filter"],"minimum_product_cards":2,"card_field_values":{"brand":["可口可乐","百事可乐"]},"plan_present":False,"cart_unchanged":True,"trace_branch":"direct_product_type_workflow"}},
  {"op":"select_pending_option","label":"filter-pepsi-brand","slot":"product_filter","label_equals":"品牌：百事可乐","message":"品牌：百事可乐",
   "expect":{"pending_slots":[],"minimum_product_cards":1,"all_card_fields":{"brand":"百事可乐"},"plan_present":False,"cart_unchanged":True,"budget_fen":2000,"trace_branch":"direct_product_filter_workflow"}},
 {"op":"turn","label":"prepare-selected-plan","message":"那就买两罐百事可乐原味汽水330ml罐装","expect":{"plan_present":True,"cart_unchanged":True,"plan_item_skus":["demo:cn-pepsi-original-330ml-can"],"plan_quantities":{"demo:cn-pepsi-original-330ml-can":2},"maximum_plan_total_fen":2000,"budget_fen":2000}},
  {"op":"confirm_plan","label":"explicit-plan-confirm","expect":{"cart_changed":True}},
  {"op":"checkout","label":"create-paid-order-for-aftersales"}]},
 {"case_id":"facts_qa_grounded_policy","steps":[
  {"op":"turn","label":"delivery-policy-question","message":"一般配送时间是多久？","expect":{"plan_present":False,"cart_unchanged":True,"orders_unchanged":True,"trace_capability":"facts_qa"}}]},
 {"case_id":"chat-without-business-write","steps":[
  {"op":"turn","label":"greeting","message":"你好，今天心情有点累。","expect":{"plan_present":False,"cart_unchanged":True,"orders_unchanged":True,"trace_capability":"chat"}}]},
 {"case_id":"keke-momo-refund-visible-keke-plan","requires_latest_order":True,
  "aftersales_expectation":{"tool":"create_refund","result":"pending"},"steps":[
  {"op":"select_order","label":"select-paid-order-for-aftersales","order_id":"latest"},
  {"op":"turn","label":"ask-refund-and-continue","message":"我刚下的订单 {{latest_order_id}} 想申请退款，办好后再帮我买一瓶可乐。","expect":{"decision":"suggest_switch","target_role":"momo","cart_unchanged":True}},
  {"op":"switch","label":"consent-to-momo","target_role":"momo","accept":True},
  {"op":"switch","label":"consent-to-keke-continuation","target_role":"keke","accept":True,"expect":{"plan_present":True,"cart_unchanged":True}},
  {"op":"replay_switch","label":"replay-no-duplicate-write"},
  {"op":"snapshot","label":"restored-guide-session"}]}]

def module_from(path,name):
 spec=importlib.util.spec_from_file_location(name,path)
 if spec is None or spec.loader is None: raise RuntimeError(f"Cannot load {path.name}")
 module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def atomic_json(path,value,pattern):
 text=json.dumps(value,ensure_ascii=False,indent=2)+"\n"; tmp=path.with_suffix(path.suffix+".tmp")
 tmp.write_text(pattern.sub(r"\1[REDACTED]",text),encoding="utf-8"); os.replace(tmp,path)
def parse_sse(raw):
 result=[]
 for block in raw.replace("\r\n","\n").split("\n\n"):
  name=next((x[7:].strip() for x in block.splitlines() if x.startswith("event: ")),None)
  data=next((x[6:] for x in block.splitlines() if x.startswith("data: ")),None)
  if data is None: continue
  body=json.loads(data)
  if name: result.append({"type":name,"payload":body})
  elif isinstance(body,dict) and isinstance(body.get("type"),str): result.append({"type":body["type"],"payload":body.get("payload",body)})
 return result
def compact(e):
 kind,p=e.get("type"),e.get("payload") or {}
 fields={"turn.completed":("message","final_text","status","task_id","state_version","session_version","plan",
  "pending_clarifications","product_cards","plan_effect","action_results","answer_status","business_not_run","route","trace_id","confirmation_result"),
  "service.route":("status","decision","raw_choice","current_role","target_role","decision_source","handoff_id","prompt_mode","request_id","route_ms","criteria_version"),
  "service.switch":("status","role","handoff_id"),"error":("code","message","retryable")}.get(kind,tuple(p.keys()))
 return {"type":kind,"payload":{k:p[k] for k in fields if k in p}}
def terminal(events):
 return next((e.get("payload",{}) for e in reversed(events) if e.get("type") in ("turn.completed","turn.stopped")),{})
class KevCapture(httpx.BaseTransport):
 def __init__(self,helper,timeout): self.forward=helper.CapturingTransport(timeout); self.calls=self.forward.calls
 def handle_request(self,request):
  body=json.loads(request.read()); response=self.forward.handle_request(request); row=self.calls[-1]
  row["kev_request"]={k:body[k] for k in ("model","questions","state") if k in body}
  if response.status_code<400:
   data=response.json(); row["kev_response"]={k:data[k] for k in ("model","answers","usage") if k in data}
  return response
 def close(self): self.forward.close()
def origin(url):
 p=urlsplit(url); return p.scheme+"://"+(p.hostname or "")+((":"+str(p.port)) if p.port else "")+p.path
def source_manifest(tree,fixture_tree):
 hashes={}
 for name,expected in FROZEN_INPUTS.items():
  hashes[name]=sha(fixture_tree/name)
  if hashes[name]!=expected: raise RuntimeError(f"Frozen input changed: {name}")
 counts={}
 for name in FROZEN_INPUTS:
  body=json.loads((fixture_tree/name).read_text(encoding="utf-8")); key="products" if "products" in body else "offers"
  counts[Path(name).name]=len(body[key])
 if counts!={"demo-products.json":67,"store-offers.json":58}: raise RuntimeError(f"Raw fixture counts differ: {counts}")
 product_hashes={}; product_absent=[]
 for name in SOURCE_FILES:
  path=tree/name
  if path.is_file(): product_hashes[name]=sha(path)
  else: product_hashes[name]=None; product_absent.append(name)
 head=subprocess.run(["git","rev-parse","HEAD"],cwd=tree,capture_output=True,text=True,check=True).stdout.strip()
 fixture_head=subprocess.run(["git","rev-parse","HEAD"],cwd=fixture_tree,capture_output=True,text=True,check=True).stdout.strip()
 return {"product_source_base_commit":BASE_SOURCE_COMMIT,"runner_checkout_commit":head,
  "product_source_checkout":str(tree),"fixture_source_checkout":str(fixture_tree),"fixture_source_commit":fixture_head,
  "product_source_sha256":product_hashes,"product_source_absent":product_absent,"fixture_sha256":hashes,
  "raw_fixture_counts":counts,"note":"raw 58 offers are not the seeded DB Offer count"}
def verify_runtime(tree,database_url,index_root,mode):
 sys.path[:0]=[str(tree/"backend"),str(tree)]
 from sqlalchemy.engine import make_url
 from sqlalchemy import create_engine,func,select
 from sqlalchemy.orm import Session
 from app.core.config import get_settings
 from app.services.retrieval_projection import build_projection
 from app.services.retrieval_index import embedding_contract_key,load_index
 from app.llm.embedding import HttpEmbeddingProvider
 os.environ.update({"LLM_MODE":"live","RETRIEVAL_MODE":mode,"DATABASE_URL":database_url,
  "RETRIEVAL_INDEX_DIR":str(index_root.resolve())})
 get_settings.cache_clear(); settings=get_settings()
 if settings.llm_mode!="live" or settings.retrieval_mode!=mode: raise RuntimeError("Actual configured LLM/retrieval mode mismatch")
 if settings.database_url!=database_url or Path(settings.retrieval_index_dir).resolve()!=index_root.resolve(): raise RuntimeError("Runtime DB/index path mismatch")
 url=make_url(database_url)
 if url.get_backend_name()!="sqlite" or not url.database or url.database==":memory:": raise RuntimeError("Persistent tester SQLite DB required")
 db_path=Path(url.database)
 if not db_path.is_absolute(): db_path=(tree/db_path).resolve()
 if not db_path.is_file(): raise RuntimeError("Tester DB missing")
 projection,_=build_projection(str(db_path)); index=load_index(index_root)
 try:
  if index.snapshot_hash!=projection.snapshot_hash: raise RuntimeError("DB projection/index snapshot mismatch")
  has_vectors=index.has_vectors(); contract=index.embedding_contract or None
  if mode=="hybrid":
   if not has_vectors or not contract: raise RuntimeError("Hybrid gate failed: vector index/contract absent")
   runtime=HttpEmbeddingProvider.from_settings(settings).contract.as_dict()
   if embedding_contract_key(runtime)!=embedding_contract_key(contract): raise RuntimeError("Hybrid embedding contract mismatch")
   hybrid="passed"
  else:
   if has_vectors or contract: raise RuntimeError("Lexical run requires a separately built no-embed index")
   hybrid="not_passed_lexical_execution"
  from app.models.catalog import CatalogProduct
  from app.models.store import Offer
  engine=create_engine("sqlite:///"+db_path.as_posix())
  with Session(engine) as db:
   product_count=db.scalar(select(func.count()).select_from(CatalogProduct))
   offer_count=db.scalar(select(func.count()).select_from(Offer))
   sellable_count=db.scalar(select(func.count()).select_from(Offer).where(Offer.sellable.is_(True)))
  engine.dispose()
  return {"database_path_fingerprint":hashlib.sha256(str(db_path).encode()).hexdigest(),
   "projection_snapshot_hash":projection.snapshot_hash,
   "index_root_fingerprint":hashlib.sha256(str(index_root.resolve()).encode()).hexdigest(),
   "index_version":index.version,"index_manifest_id":index.manifest["manifest_id"],
   "retrieval_mode":mode,"has_vectors":has_vectors,"embedding_contract":contract,
   "hybrid_gate":hybrid,"database_counts":{"catalog_products":product_count,"offers":offer_count,"sellable_offers":sellable_count}},settings
 finally: index.close()
def snapshot(client,ctx,include_messages=False):
 c=client.get("/api/v1/cart"); c.raise_for_status(); o=client.get("/api/v1/orders"); o.raise_for_status()
 g=client.get(f"/api/v1/guide/sessions/{ctx['guide_session_id']}",params={"include_messages":int(include_messages)}); g.raise_for_status()
 h=client.get(f"/api/v1/chat/openings/{ctx['opening_id']}"); h.raise_for_status()
 ctx["last_guide"]=g.json(); ctx["role"]=h.json()["role"]
 return {"cart":c.json(),"orders":o.json().get("items",[]),"guide":g.json(),
  "opening":{k:h.json().get(k) for k in ("role","pending_question","prompt_displayed")}}
def new_case(client,case,role_calls,kev_calls):
 entry_context=case.get("entry_context",{"page":"home","store_id":"store-demo-01","delivery_zone_id":"zone-default"})
 g=client.post("/api/v1/guide/sessions",json={"entry_context":entry_context}); g.raise_for_status()
 m=client.post("/api/v1/mercury/sessions"); m.raise_for_status()
 role=case.get("initial_role","keke")
 h=client.post("/api/v1/chat/openings",json={"guide_session_id":g.json()["session_id"],"mercury_session_id":m.json()["session_id"],"role":role}); h.raise_for_status()
 return {"case_id":case["case_id"],"guide_session_id":g.json()["session_id"],"mercury_session_id":m.json()["session_id"],
  "opening_id":h.json()["opening_id"],"role":role,"role_calls":role_calls,"kev_calls":kev_calls,
  "aftersales_expectation":case.get("aftersales_expectation",{"tool":"create_refund","result":"pending"})}
def read_pending(client,ctx):
 r=client.get(f"/api/v1/guide/sessions/{ctx['guide_session_id']}"); r.raise_for_status(); ctx["last_guide"]=r.json()
 return r.json().get("pending_clarifications") or []
def trace_for(client,payload,helper,token):
 return helper.read_trace(client,payload["trace_id"],{"X-Internal-Token":token}) if payload.get("trace_id") else []
def turn(client,ctx,message,label,answer,helper,token,view_context=None):
 s=client.get(f"/api/v1/guide/sessions/{ctx['guide_session_id']}"); s.raise_for_status(); state=s.json()
 body={"request_id":"08-"+ctx["case_id"]+"-"+uuid.uuid4().hex[:10],"message":message,"expected_task_id":state.get("task_id"),
  "expected_state_version":state.get("state_version",0),"expected_session_version":state.get("session_version",0)}
 if answer: body["clarification_answer"]=answer
 if view_context is not None: body["view_context"]=view_context
 before=snapshot(client,ctx); rc,kc=len(ctx["role_calls"]),len(ctx["kev_calls"]); start=time.perf_counter()
 response=client.post(f"/api/v1/chat/openings/{ctx['opening_id']}/turns/stream",json=body)
 events=parse_sse(response.text); end=terminal(events)
 row={"label":label,"active_role_before":ctx["role"],"request":body,"http_status":response.status_code,
  "elapsed_ms":round((time.perf_counter()-start)*1000,1),"latency_target_ms":15000,
  "latency_target_exceeded":(time.perf_counter()-start)*1000>15000,"events":[compact(e) for e in events],
  "role_model_call_range":[rc,len(ctx["role_calls"])],"kev_call_range":[kc,len(ctx["kev_calls"])],
  "terminal":compact({"type":"turn.completed","payload":end})["payload"],"trace":trace_for(client,end,helper,token)}
 ctx["last_step"]={**row,"events":events}
 if response.status_code>=400: row["failure_body"]=response.text[:1000]; raise RuntimeError(f"{label}: HTTP {response.status_code}")
 row["snapshot_after"]=snapshot(client,ctx,True); return row
def find_handoff(step,ctx):
 target=step["target_role"]; events=ctx.get("last_step",{}).get("events",[])
 rows=[e.get("payload",{}) for e in events if e.get("type")=="service.route" and e.get("payload",{}).get("target_role")==target]
 if not rows or not rows[-1].get("handoff_id"): raise AssertionError(f"No current handoff to {target}")
 return rows[-1]["handoff_id"]
def expectation_failures(exp,row,before,after):
 fail=[]; events=row.get("events",[]); routes=[e.get("payload",{}) for e in events if e.get("type")=="service.route"]
 route=routes[-1] if routes else {}; end=row.get("terminal") or row.get("switch_terminal") or {}
 guide=after.get("guide",{}); pending=guide.get("pending_clarifications") or end.get("pending_clarifications") or []
 slots=sorted(q.get("slot") for q in pending if q.get("slot")); cards=guide.get("product_cards") or end.get("product_cards") or []
 if "decision" in exp and route.get("decision")!=exp["decision"]: fail.append("service route decision mismatch")
 if "target_role" in exp and route.get("target_role")!=exp["target_role"]: fail.append("service route target mismatch")
 if "pending_slots" in exp and slots!=sorted(exp["pending_slots"]): fail.append(f"pending slots: {slots}")
 if "minimum_options" in exp and max((len(q.get("options") or []) for q in pending),default=0)<exp["minimum_options"]: fail.append("too few option bubbles")
 if "minimum_product_cards" in exp and len(cards)<exp["minimum_product_cards"]: fail.append("too few candidate cards")
 for field,values in exp.get("card_field_values",{}).items():
  if not set(values).issubset({c.get(field) for c in cards}): fail.append(f"candidate field values missing for {field}")
 for field,value in exp.get("all_card_fields",{}).items():
  if not cards or {c.get(field) for c in cards}!={value}: fail.append(f"candidate cards not all {field}={value}")
 has_plan=bool(guide.get("plan") or end.get("plan"))
 if "plan_present" in exp and has_plan!=exp["plan_present"]: fail.append(f"plan_present={has_plan}")
 plan=guide.get("plan") or end.get("plan") or {}
 items=plan.get("items") or []
 skus={i.get("sku_id") for i in items}
 if "plan_item_skus" in exp and not set(exp["plan_item_skus"]).issubset(skus): fail.append(f"plan SKU set: {skus}")
 if "plan_quantities" in exp:
  quantities={i.get("sku_id"):i.get("quantity") for i in items}
  if any(quantities.get(sku)!=quantity for sku,quantity in exp["plan_quantities"].items()): fail.append(f"plan quantities: {quantities}")
 if "maximum_plan_total_fen" in exp and plan.get("selected_total_fen",0)>exp["maximum_plan_total_fen"]: fail.append("selected plan total exceeds budget")
 if "budget_fen" in exp and guide.get("constraints_summary",{}).get("budget_fen")!=exp["budget_fen"]: fail.append("budget constraint was not preserved")
 if exp.get("cart_unchanged") and before.get("cart")!=after.get("cart"): fail.append("cart changed without explicit confirmation")
 if exp.get("cart_changed") and before.get("cart")==after.get("cart"): fail.append("confirmation did not change cart")
 if exp.get("orders_unchanged") and before.get("orders")!=after.get("orders"): fail.append("orders changed during read/chat step")
 trace=row.get("trace") or []
 if "trace_capability" in exp and not any(t.get("capability")==exp["trace_capability"] for t in trace): fail.append("capability trace mismatch")
 if "trace_branch" in exp and not any(t.get("branch")==exp["trace_branch"] for t in trace): fail.append("workflow branch mismatch")
 return fail

def aftersales_capture_check(calls,events,expectation):
 expected_tool=expectation["tool"]; expected_result=expectation["result"]
 if expected_tool not in ("create_refund","create_return") or expected_result not in ("pending","failed"):
  raise ValueError("aftersales_expectation requires a supported tool and pending/failed result")
 call_names={}; matching_calls=[]; results_by_id={}; visible=[]
 for call in calls:
  for choice in call.get("response_choices",[]):
   message=choice.get("message") or {}
   for tool in message.get("tool_calls") or []:
    name=(tool.get("function") or {}).get("name"); call_id=tool.get("id")
    if call_id: call_names[call_id]=name
    if name==expected_tool: matching_calls.append(tool)
  for message in (call.get("request") or {}).get("messages") or []:
   if message.get("role")!="tool" or call_names.get(message.get("tool_call_id"))!=expected_tool: continue
   body=json.loads(message.get("content") or "")
   data=body.get("data") if isinstance(body.get("data"),dict) else {}
   status="failed" if body.get("ok") is False else data.get("status")
   result={"ok":body.get("ok"),"status":status,"message":data.get("message") or body.get("message"),
    "tool_call_id":message.get("tool_call_id")}
   results_by_id[message.get("tool_call_id")]=result
 for event in events:
  body=event.get("payload") or {}
  if event.get("type")=="turn.completed" and body.get("business_not_run"):
   visible.append(body.get("message",""))
 if len(matching_calls)!=1: raise AssertionError(f"Expected one real {expected_tool} call, captured {len(matching_calls)}")
 matching_results=[results_by_id.get(tool.get("id")) for tool in matching_calls]
 result=next((item for item in reversed(matching_results) if item),None)
 if result is None: raise AssertionError(f"No actual {expected_tool} tool result was captured")
 if result["status"]!=expected_result: raise AssertionError(f"Expected {expected_tool} result {expected_result}, captured {result['status']}")
 contains_result=bool(result["message"] and any(result["message"] in text and "继续选购" in text for text in visible))
 if expected_result=="pending" and not contains_result:
  raise AssertionError("Pending after-sales result was not visible in the Keke continuation prompt")
 return {"tool":expected_tool,"tool_calls":len(matching_calls),"result":result["status"],
         "tool_result":result,"continuation_prompt_contains_result":contains_result}
def execute(client,ctx,step,evidence,path,helper,token):
 op=step["op"]; label=step.get("label",op); before=snapshot(client,ctx); row={"case_id":ctx["case_id"],"op":op,"label":label,"before":before}; start=time.perf_counter()
 try:
  if op=="turn":
   text=step["message"].replace("{{latest_order_id}}",str(evidence.get("latest_order_id") or "<missing-order>"))
   row.update(turn(client,ctx,text,label,None,helper,token,step.get("view_context")))
  elif op=="select_pending_option":
   questions=read_pending(client,ctx); q=next((x for x in questions if x.get("slot")==step["slot"]),None)
   if q is None: raise AssertionError(f"No pending field {step['slot']}")
   opts=q.get("options") or []
   if "label_equals" in step: option=next((x for x in opts if x.get("label")==step["label_equals"]),None)
   elif "label_contains" in step: option=next((x for x in opts if step["label_contains"] in x.get("label","")),None)
   else: option=opts[0] if opts else None
   if option is None: raise AssertionError(f"No current option matches field {step['slot']}")
   row["selected_option"]={"question_id":q["question_id"],"option_id":option["id"],"slot":q["slot"],"label":option["label"]}
   row.update(turn(client,ctx,step.get("message",option["label"]),label,{"question_id":q["question_id"],"option_id":option["id"]},helper,token,step.get("view_context")))
  elif op=="switch":
   handoff=find_handoff(step,ctx); target=step["target_role"]; base=f"/api/v1/chat/openings/{ctx['opening_id']}"
   shown=client.post(base+"/prompt-displayed",json={"handoff_id":handoff}); shown.raise_for_status()
   rc,kc=len(ctx["role_calls"]),len(ctx["kev_calls"])
   response=client.post(base+"/switches/stream",json={"target_role":target,"handoff_id":handoff,"accept":step["accept"]})
   events=parse_sse(response.text); row.update({"handoff_id":handoff,"target_role":target,"accepted":step["accept"],
    "http_status":response.status_code,"events":[compact(e) for e in events],"role_model_call_range":[rc,len(ctx["role_calls"])],
    "kev_call_range":[kc,len(ctx["kev_calls"])],"switch_terminal":compact({"type":"turn.completed","payload":terminal(events)})["payload"]})
   if response.status_code>=400: raise RuntimeError(f"{label}: switch HTTP {response.status_code}")
   after=snapshot(client,ctx,True); row["snapshot_after"]=after; ctx["last_handoff_id"]=handoff
   ctx["last_step"]={**row,"events":events}
   if step["accept"]:
    ctx["last_accepted_handoff_id"]=handoff
    done=[e["payload"] for e in events if e.get("type")=="turn.completed" and not e.get("payload",{}).get("business_not_run")]
    if done: ctx["last_completed"]=done[-1]
    if target=="momo":
     row["aftersales_result_check"]=aftersales_capture_check(ctx["role_calls"][rc:],events,ctx["aftersales_expectation"])
    if target=="keke":
     if not done or not done[-1].get("plan"): raise AssertionError("Keke continuation returned no visible plan")
     restored=after["guide"]; restored_plan=restored.get("plan") or {}
     plan=done[-1]["plan"]
     if restored_plan.get("plan_id")!=plan.get("plan_id"): raise AssertionError("GET session did not restore the continuation plan")
     reply=done[-1].get("message") or done[-1].get("final_text")
     messages=restored.get("messages") or []
     saved=any(m.get("role")=="assistant" and m.get("content")==reply for m in messages)
     if not reply or not saved: raise AssertionError("GET session did not restore the Keke reply")
     row["session_restore_check"]={"reply":reply,"reply_visible_in_get_session_messages":True,
        "plan_id":restored_plan["plan_id"],"plan_visible_in_get_session":True}
  elif op=="replay_switch":
   handoff=ctx.get("last_accepted_handoff_id")
   if not handoff: raise AssertionError("No accepted handoff to replay")
   rc,kc=len(ctx["role_calls"]),len(ctx["kev_calls"])
   response=client.post(f"/api/v1/chat/openings/{ctx['opening_id']}/switches/stream",
    json={"target_role":ctx["role"],"handoff_id":handoff,"accept":True})
   events=parse_sse(response.text); after=snapshot(client,ctx,True)
   row.update({"handoff_id":handoff,"http_status":response.status_code,"events":[compact(e) for e in events],
    "snapshot_after":after,"role_model_calls_before_after":[rc,len(ctx["role_calls"])],
    "kev_calls_before_after":[kc,len(ctx["kev_calls"])],"cart_unchanged":before["cart"]==after["cart"],
    "orders_unchanged":before["orders"]==after["orders"]})
   if response.status_code>=400: raise RuntimeError(f"{label}: replay HTTP {response.status_code}")
   if rc!=len(ctx["role_calls"]) or kc!=len(ctx["kev_calls"]): raise AssertionError("Replay invoked a model")
   if before["cart"]!=after["cart"] or before["orders"]!=after["orders"]: raise AssertionError("Replay repeated a business write")
  elif op=="select_order":
   order=step.get("order_id","latest")
   if order=="latest": order=evidence.get("latest_order_id")
   if not order: raise AssertionError("No order available for selection")
   res=client.post(f"/api/v1/mercury/sessions/{ctx['mercury_session_id']}/order",json={"order_id":order})
   res.raise_for_status(); ctx["selected_order_id"]=order; row["selected_order"]=res.json()
   if row["selected_order"].get("order",{}).get("order_id")!=order: raise AssertionError("Selected order response mismatch")
  elif op=="confirm_plan":
   res=client.get(f"/api/v1/guide/sessions/{ctx['guide_session_id']}"); res.raise_for_status(); state=res.json(); plan=state.get("plan")
   if not plan or not plan.get("can_confirm"): raise AssertionError("No confirmable plan")
   items=[{"sku_id":i["sku_id"],"quantity":i.get("remaining_quantity") or i["quantity"]} for i in plan["items"]
          if i.get("selected",True) and (i.get("remaining_quantity") or i["quantity"])>0]
   res=client.post(f"/api/v1/guide/tasks/{state['task_id']}/confirm",headers={"Idempotency-Key":"08-"+uuid.uuid4().hex},
    json={"plan_id":plan["plan_id"],"plan_version":plan["plan_version"],"expected_state_version":state["state_version"],
     "expected_session_version":state["session_version"],"selected_items":items})
   res.raise_for_status(); row["confirmed_items"]=items; row["confirmation"]=res.json()
  elif op=="checkout":
   res=client.get("/api/v1/cart"); res.raise_for_status(); cart=res.json()
   if not cart.get("items"): raise AssertionError("Checkout requires explicitly confirmed non-empty cart")
   res=client.post("/api/v1/cart/checkout",json={"expected_cart_version":cart["version"]}); res.raise_for_status()
   row["checkout"]=res.json(); evidence["latest_order_id"]=res.json()["order"]["order_id"]
  elif op=="snapshot": row["snapshot"]=snapshot(client,ctx,True)
  else: raise ValueError(f"Unsupported fixed operation {op}")
  row.setdefault("snapshot_after",snapshot(client,ctx,True)); row["elapsed_ms"]=round((time.perf_counter()-start)*1000,1)
  if step.get("expect"):
   row["expectation_failures"]=expectation_failures(step["expect"],row,before,row["snapshot_after"])
   row["status"]="failed_expectation" if row["expectation_failures"] else "captured"
  else: row["status"]="captured"
  evidence["steps"].append(row); atomic_json(path,evidence,helper.CREDENTIAL_VALUE)
  if row["status"]!="captured": raise AssertionError("; ".join(row["expectation_failures"]))
  return row
 except Exception as exc:
  if not any(x.get("case_id")==ctx["case_id"] and x.get("label")==label for x in evidence["steps"]):
   row.update({"status":"failed","failure_type":type(exc).__name__,"failure_message":str(exc)[:500],
               "last_response":ctx.get("last_step"),"elapsed_ms":round((time.perf_counter()-start)*1000,1)})
   evidence["steps"].append(row)
  atomic_json(path,evidence,helper.CREDENTIAL_VALUE); raise
def run_case(client,case,role_calls,kev_calls,evidence,path,helper,token):
 record={"case_id":case["case_id"],"status":"running"}; evidence["cases"].append(record); started=time.perf_counter()
 try:
  if case.get("requires_latest_order") and not evidence.get("latest_order_id"):
   record.update({"status":"blocked_prerequisite","failure_message":"No paid order from drink case"}); return
  record["setup"]={"initial_role":case.get("initial_role","keke"),
   "entry_context":case.get("entry_context",{"page":"home","store_id":"store-demo-01","delivery_zone_id":"zone-default"}),
   "aftersales_expectation":case.get("aftersales_expectation")}
  ctx=new_case(client,case,role_calls,kev_calls)
  record.update({k:ctx[k] for k in ("guide_session_id","mercury_session_id","opening_id")})
  for step in case["steps"]: execute(client,ctx,step,evidence,path,helper,token)
  record.update({"status":"captured","last_guide_snapshot":ctx.get("last_guide"),"active_role_at_end":ctx.get("role"),
                 "last_handoff_id":ctx.get("last_handoff_id")})
 except Exception as exc: record.update({"status":"failed","failure_type":type(exc).__name__,"failure_message":str(exc)[:500]})
 finally:
  record["elapsed_ms"]=round((time.perf_counter()-started)*1000,1); atomic_json(path,evidence,helper.CREDENTIAL_VALUE)

def call_summary(calls):
 totals={"calls":len(calls),"calls_with_usage":0,"prompt_tokens":0,"completion_tokens":0,
         "total_tokens":0,"request_latency_ms":0}
 for call in calls:
  usage=call.get("usage") or (call.get("kev_response") or {}).get("usage")
  if isinstance(usage,dict):
   totals["calls_with_usage"]+=1
   for key,aliases in (("prompt_tokens",("prompt_tokens","input_tokens")),
                       ("completion_tokens",("completion_tokens","output_tokens")),
                       ("total_tokens",("total_tokens",))):
    value=next((usage.get(k) for k in aliases if isinstance(usage.get(k),int)),0)
    totals[key]+=value
  if isinstance(call.get("request_latency_ms"),(int,float)): totals["request_latency_ms"]+=call["request_latency_ms"]
 return totals

def setup_live(tree,database_url,index_root,mode,helper):
 os.environ.update({"LLM_MODE":"live","RETRIEVAL_MODE":mode,"DATABASE_URL":database_url,
  "RETRIEVAL_INDEX_DIR":str(index_root.resolve()),"INTERNAL_ENABLED":"true"})
 token="08trace-"+uuid.uuid4().hex; os.environ["INTERNAL_ADMIN_TOKEN"]=token
 from app.core.config import get_settings
 get_settings.cache_clear(); settings=get_settings()
 from app.llm.live_semantic_provider import LiveSemanticProvider
 from app.llm.openai_transport import OpenAICompatTransport
 role_transport=helper.CapturingTransport(float(settings.llm_timeout))
 provider=LiveSemanticProvider(settings,OpenAICompatTransport(settings,transport=role_transport))
 import app.llm.provider as provider_module
 provider_module.get_semantic_provider=lambda:provider
 from fastapi.testclient import TestClient
 from app.main import app
 manager=TestClient(app); client=manager.__enter__()
 from app.llm.kev_provider import KEV_TIMEOUT_SECONDS,get_kev_provider
 kev_provider=get_kev_provider(); kev_provider.client.close(); kev_transport=KevCapture(helper,KEV_TIMEOUT_SECONDS)
 kev_provider.client=httpx.Client(timeout=KEV_TIMEOUT_SECONDS,transport=kev_transport)
 import mercury.llm as mercury_llm
 from openai import OpenAI as RealOpenAI
 def openai_capture(**kwargs):
  http_client=httpx.Client(transport=role_transport,timeout=httpx.Timeout(float(settings.llm_timeout),connect=10.0),trust_env=False)
  return RealOpenAI(**kwargs,http_client=http_client)
 mercury_llm.OpenAI=openai_capture
 return client,manager,settings,token,role_transport.calls,kev_transport.calls,kev_provider
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("--tree",required=True); parser.add_argument("--output-dir",required=True)
 parser.add_argument("--fixture-source-tree"); parser.add_argument("--capture-helper")
 parser.add_argument("--database-url",required=True); parser.add_argument("--index-root",required=True)
 parser.add_argument("--retrieval-mode",choices=("hybrid","lexical"),default="hybrid")
 parser.add_argument("--cases-file"); parser.add_argument("--seed-report"); parser.add_argument("--build-report")
 args=parser.parse_args(); tree=Path(args.tree).resolve(); fixture_tree=Path(args.fixture_source_tree).resolve() if args.fixture_source_tree else tree
 capture_helper=Path(args.capture_helper).resolve() if args.capture_helper else tree/"work"/"ceres-next-agent-experience"/"04"/"collect_prompt_sample.py"
 output=Path(args.output_dir).resolve(); index=Path(args.index_root).resolve()
 if output.exists(): raise SystemExit("Evidence directory exists; choose a new path")
 output.mkdir(parents=True); evidence_path=output/"live-public-multiturn.json"
 if args.cases_file:
  case_path=Path(args.cases_file).resolve(); cases=json.loads(case_path.read_text(encoding="utf-8"))
  if not isinstance(cases,list) or not cases: raise ValueError("cases file must be a non-empty JSON list")
 else: case_path=None; cases=PUBLIC_CASES
 helper=module_from(capture_helper,"ceres_next_04_capture")
 evidence={"runner_version":"08-live-api-multiturn-v1","captured_at_utc":datetime.now(timezone.utc).isoformat(),
  "source":None,"case_source_sha256":sha(case_path) if case_path else "embedded-public-cases",
  "case_ids":[c["case_id"] for c in cases],"seed_report_path":str(Path(args.seed_report).resolve()) if args.seed_report else None,
  "build_report_path":str(Path(args.build_report).resolve()) if args.build_report else None,"requested_retrieval_mode":args.retrieval_mode,
  "runtime_identity":None,"model":None,"role_model_calls":[],"kev_calls":[],"cases":[],"steps":[],
  "human_review":{"agent_expression_review":"pending","user_acceptance":"not_recorded"}}
 manager=kev_provider=None; started=time.perf_counter(); identity=None
 try:
  evidence["source"]=source_manifest(tree,fixture_tree)
  evidence["runner_sha256"]=sha(Path(__file__).resolve())
  evidence["capture_helper_path"]=str(capture_helper)
  evidence["capture_helper_sha256"]=sha(capture_helper)
  for key,arg in (("seed_report",args.seed_report),("build_report",args.build_report)):
   if arg:
    report=Path(arg).resolve()
    if not report.is_file(): raise RuntimeError(f"Provenance report missing: {key}")
    evidence[key+"_sha256"]=sha(report)
  identity,settings=verify_runtime(tree,args.database_url,index,args.retrieval_mode); evidence["runtime_identity"]=identity
  client,manager,settings,token,role_calls,kev_calls,kev_provider=setup_live(tree,args.database_url,index,args.retrieval_mode,helper)
  evidence["role_model_calls"]=role_calls; evidence["kev_calls"]=kev_calls
  evidence["model"]={"role_model":settings.llm_model,"kev_model":"kev-latest","role_endpoint_origin_path":origin(settings.openai_base_url),
   "capture_boundary":"work/ceres-next-agent-experience/04/collect_prompt_sample.py","timeout_seconds":settings.llm_timeout}
  evidence["preflight_startup_ms"]=round((time.perf_counter()-started)*1000,1)
  for case in cases: run_case(client,case,role_calls,kev_calls,evidence,evidence_path,helper,token)
  evidence["model_call_summary"]={"role_model":call_summary(role_calls),"kev":call_summary(kev_calls)}
  bad=[c["case_id"] for c in evidence["cases"] if c["status"]!="captured"]
  evidence["status"]="captured" if not bad else "captured_with_failures"; evidence["failed_case_ids"]=bad
  evidence["elapsed_ms"]=round((time.perf_counter()-started)*1000,1)
 except Exception as exc:
  evidence["status"]="runner_error"; evidence["failure_type"]=type(exc).__name__; evidence["failure_message"]=str(exc)[:500]
  atomic_json(evidence_path,evidence,helper.CREDENTIAL_VALUE); raise
 finally:
  if manager is not None: manager.__exit__(None,None,None)
  if kev_provider is not None:
   from app.llm.kev_provider import get_kev_provider
   get_kev_provider.cache_clear()
 atomic_json(evidence_path,evidence,helper.CREDENTIAL_VALUE)
 print(json.dumps({"status":evidence["status"],"cases":len(evidence["cases"]),"failed_cases":evidence.get("failed_case_ids",[]),
  "role_model_calls":len(evidence["role_model_calls"]),"kev_calls":len(evidence["kev_calls"]),
  "retrieval_mode":identity["retrieval_mode"],"has_vectors":identity["has_vectors"],
  "hybrid_gate":identity["hybrid_gate"],"index_version":identity["index_version"]},ensure_ascii=False))
 return 0 if evidence["status"]=="captured" else 1
if __name__=="__main__": raise SystemExit(main())

