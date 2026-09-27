"""Export LangGraph topology as Mermaid, with optional Chinese display labels.

Node IDs stay English (runtime / tests unchanged); only presentation labels are localized.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Ensure ``app`` is importable when run as ``python scripts/export_graph_mermaid.py``.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.agent.graph.graph import get_graph

NODE_LABELS: dict[str, str] = {
    "load_context": "加载上下文",
    "understand": "语义理解",
    "retrieve": "只读检索",
    "mutation": "清单变更",
    "answer": "生成回答",
    "respond": "提交并响应",
}

EDGE_LABELS: dict[str, str] = {
    "end": "结束",
    "retrieve": "只读检索",
    "mutation": "清单变更",
    "answer": "生成回答",
}

START_LABEL = "开始"
END_LABEL = "结束"


def _localize_nodes(mermaid: str) -> str:
    for node_id, label in NODE_LABELS.items():
        mermaid = re.sub(
            rf"\b{re.escape(node_id)}\({re.escape(node_id)}\)",
            f'{node_id}["{label}"]',
            mermaid,
        )
    mermaid = re.sub(
        r"__start__\(\[<p>__start__</p>\]\)",
        f'__start__(["{START_LABEL}"])',
        mermaid,
    )
    mermaid = re.sub(
        r"__end__\(\[<p>__end__</p>\]\)",
        f'__end__(["{END_LABEL}"])',
        mermaid,
    )
    return mermaid


def _edge_label_for_route(route_key: str, target: str) -> str:
    if route_key == "end":
        return END_LABEL if target == "__end__" else "拒绝"
    return EDGE_LABELS.get(route_key, route_key)


def _localize_edge_labels(mermaid: str) -> str:
    lines: list[str] = []
    for line in mermaid.splitlines():
        match = re.match(
            r"^(\s*)(\w+)\s+-\.\s*&nbsp;(\w+)&nbsp;\s*\.->\s+(\w+);$",
            line,
        )
        if match:
            indent, source, route_key, target = match.groups()
            label = _edge_label_for_route(route_key, target)
            line = f"{indent}{source} -.->|{label}| {target};"
        lines.append(line)
    return "\n".join(lines)


def localize_mermaid(mermaid: str) -> str:
    mermaid = _localize_nodes(mermaid)
    mermaid = _localize_edge_labels(mermaid)
    # Unlabeled conditional edges: infer label from target node id.
    lines: list[str] = []
    for line in mermaid.splitlines():
        match = re.match(r"^(\s*)(\w+)\s+-\.->\s+(\w+);$", line)
        if match:
            source, target = match.group(2), match.group(3)
            label = EDGE_LABELS.get(target)
            if label:
                line = f"{match.group(1)}{source} -.->|{label}| {target};"
        lines.append(line)
    return "\n".join(lines)


def export_mermaid(*, localized: bool = True) -> str:
    compiled = get_graph()
    mermaid = compiled.get_graph().draw_mermaid()
    if localized:
        mermaid = localize_mermaid(mermaid)
    return mermaid


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Sale-guide LangGraph as Mermaid.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write to file instead of stdout.",
    )
    parser.add_argument(
        "--english",
        action="store_true",
        help="Keep LangGraph default English labels.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Wrap in a Markdown mermaid fence (best for Ctrl+Shift+V preview).",
    )
    parser.add_argument(
        "--strip-styles",
        action="store_true",
        help="With --markdown, drop classDef lines only (keeps layout structure).",
    )
    args = parser.parse_args()

    mermaid = export_mermaid(localized=not args.english)
    if args.markdown:
        body = _to_markdown_body(mermaid, strip_styles=args.strip_styles)
        title = "Sale-guide LangGraph（中文版）" if not args.english else "Sale-guide LangGraph"
        mermaid = (
            f"# {title}\n\n"
            "在 Cursor 中打开本文件，按 `Ctrl+Shift+V` 预览。\n\n"
            f"```mermaid\n{body}\n```\n"
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(mermaid + "\n", encoding="utf-8")
    else:
        print(mermaid)
    return 0


def _to_markdown_body(mermaid: str, *, strip_styles: bool = False) -> str:
    """Wrap the LangGraph export with minimal edits so layout matches mermaid.live.

    Previous hand-written markdown rewrote ``-.->`` as ``-->`` and dropped the
    upfront node block + frontmatter, which produced a completely different layout.
    """
    if not strip_styles:
        return mermaid.strip()
    lines: list[str] = []
    for line in mermaid.splitlines():
        if line.strip().startswith("classDef "):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


if __name__ == "__main__":
    raise SystemExit(main())
