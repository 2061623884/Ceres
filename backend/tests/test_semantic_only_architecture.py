"""One decision chain, no selector, no fallback route.

Two kinds of assertion live here:

* **Static** — the module graph. No runtime module may import the retired
  tool-call chain, no configuration may select a pipeline, and the shared
  structural validator has exactly one owner.
* **Live** — every entry page (home / category / search / product / cart) and
  every session shape runs the same chain: the scripted semantic provider is
  asked, and nothing else is.

These are architecture constraints, not behaviour assertions: behaviour is
covered by ``test_semantic_pipeline.py`` and the acceptance suites.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from support import create_session, post_turn
from support.semantic_agent import reply_only

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

#: The retired decision chain, its transport and its node-output schemas must stay
#: absent from the runtime.
RETIRED = (
    "app.agent.controlled_agent",
    "app.agent.decision_policy",
    "app.agent.turn_interpreter",
    "app.agent.answer_generator",
    "app.agent.query_builder",
    "app.agent.search_request",
    "app.agent.intent_normalize",
    "app.agent.candidate_selection",
    "app.agent.constraint_extract",
    "app.agent.deterministic_fulfillment",
    "app.agent.modification",
    "app.agent.tool_policy",
    "app.agent.tools.gate",
    "app.llm.agent_interface",
    "app.llm.live_agent_provider",
    "app.llm.live_provider",
    "app.llm.node_schemas",
    "app.llm.text_signals",
)
RETIRED_FILES = {f"{name.replace('.', '/')}.py" for name in RETIRED}


def _runtime_sources() -> list[Path]:
    return [
        path
        for path in sorted(APP_ROOT.rglob("*.py"))
        if str(path.relative_to(BACKEND_ROOT)).replace("\\", "/") not in RETIRED_FILES
    ]


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_no_runtime_module_imports_the_retired_chain():
    """Import closure, not just direct imports: the boundary must really hold."""
    offenders: list[str] = []
    for path in _runtime_sources():
        for name in _imported_modules(path):
            if any(name == banned or name.startswith(banned + ".") for banned in RETIRED):
                offenders.append(f"{path.relative_to(BACKEND_ROOT)} imports {name}")
    assert offenders == [], "仍有运行模块依赖已退役链路: " + "; ".join(offenders)


def test_the_retired_chain_is_unreachable_from_the_turn_entry():
    """The production turn entry must not reach it transitively either."""
    import subprocess
    import sys

    program = (
        "import sys\n"
        "import app.services.graph_turn_service, app.agent.turn_primitives, app.agent.tools.change_plan\n"
        "banned = %r\n"
        "leaked = sorted({m for m in sys.modules "
        "if any(m == b or m.startswith(b + '.') for b in banned)})\n"
        "print('|'.join(leaked))\n" % (RETIRED,)
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"回合入口传递依赖泄漏: {result.stdout.strip()}"


def test_the_only_provider_factory_is_the_semantic_one():
    """A factory for the old providers would be a way back into the old chain."""
    from app.llm import provider

    assert callable(provider.get_semantic_provider)
    assert not hasattr(provider, "get_agent_provider")
    assert not hasattr(provider, "get_llm_provider")


def test_the_tools_package_does_not_export_the_tool_gate():
    import app.agent.tools as tools

    assert not hasattr(tools, "ToolGate")
    # The gate's search schema and its call budget went with it; only the plan
    # tool's own schema is exported now.
    for retired_export in (
        "SEARCH_DISHES_INPUT_SCHEMA",
        "ALLOWED_TOOL_NAMES",
        "MAX_TOOL_CALLS_PER_TURN",
    ):
        assert not hasattr(tools, retired_export), retired_export


def test_the_shared_validator_has_one_owner():
    """``validate_json_object`` belongs to the validator module, not the gate."""
    from app.agent.tools.validation import validate_json_object

    assert callable(validate_json_object)
    assert not (APP_ROOT / "agent" / "tools" / "gate.py").exists()
    change_plan = (APP_ROOT / "agent" / "tools" / "change_plan.py").read_text(encoding="utf-8")
    assert "from app.agent.tools.validation import validate_json_object" in change_plan
    assert "from app.agent.tools.gate import" not in change_plan


def test_retired_runtime_files_are_removed():
    assert [name for name in RETIRED_FILES if (BACKEND_ROOT / name).exists()] == []


def test_no_configuration_can_select_a_pipeline():
    config = (APP_ROOT / "core" / "config.py").read_text(encoding="utf-8")
    assert "semantic_pipeline_mode" not in config
    assert "SEMANTIC_PIPELINE_MODE" not in config
    env_example = (BACKEND_ROOT.parent / ".env.example").read_text(encoding="utf-8")
    assert "SEMANTIC_PIPELINE_MODE" not in env_example


def test_production_turn_entry_has_no_legacy_orchestration():
    guide = (APP_ROOT / "api" / "guide.py").read_text(encoding="utf-8")
    stream = (APP_ROOT / "services" / "turn_stream_service.py").read_text(encoding="utf-8")
    assert "GuideWorkflow" not in guide
    assert "GuideWorkflow" not in stream
    assert "run_loop" not in guide
    assert "run_loop" not in stream
    # The unique chain is guide -> TurnStreamService -> GraphTurnService: the API
    # layer only names the SSE service, and the SSE service names the turn service.
    assert "TurnStreamService" in guide
    assert "GraphTurnService" not in guide
    assert "TurnStreamService(" in guide
    assert "GraphTurnService" in stream


# ------------------------------------------------------------------ live turns


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


@pytest.mark.parametrize(
    "page,category_id",
    [
        ("home", None),
        ("category", "baking"),
        ("search", None),
        ("product", None),
        ("cart", None),
    ],
)
def test_every_entry_page_runs_the_one_chain(client, semantic_provider, page, category_id):
    """A page is context, never a route: each one reaches the same provider."""
    provider = semantic_provider([reply_only("你好，想吃点什么？")])
    sid = create_session(client, page=page, category_id=category_id)

    response = turn(client, sid, "你好")
    assert response.status_code == 200, response.text
    assert provider.remaining() == 0, f"{page} 页未进入唯一决策链"


@pytest.mark.parametrize("page,category_id", [("category", "baking"), ("search", None)])
def test_the_entry_page_reaches_the_model_as_context(
    client, semantic_provider, page, category_id
):
    """The page travels with the turn now that it is not a branch of its own."""
    provider = semantic_provider([reply_only("好的。")])
    sid = create_session(client, page=page, category_id=category_id)

    assert turn(client, sid, "你好").status_code == 200
    entry = provider.requests[0]["entry_context"]
    assert entry.get("page") == page
    if category_id:
        assert entry.get("category_id") == category_id


def test_a_follow_up_turn_on_the_same_session_runs_the_same_chain(
    client, semantic_provider
):
    """The second turn is not served by a different route than the first."""
    sid = create_session(client)
    first = semantic_provider([reply_only("先记下了。")])
    assert turn(client, sid, "你好").status_code == 200
    assert first.remaining() == 0

    second = semantic_provider([reply_only("我没有加购记录。")])
    body = turn(client, sid, "刚才买了什么").json()
    assert second.remaining() == 0
    assert body["plan_effect"] == "keep"
