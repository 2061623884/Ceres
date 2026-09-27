#!/usr/bin/env python3
"""Author the retrieval annotation set and lint it.

Run once to (re)generate ``verification/rag/annotation-set.json``; keep it in the
repo so the set can be reproduced and re-linted, not just trusted.

The two labelling rules this enforces, because getting them wrong is how an
evaluation flatters itself:

* ``answerable`` is true exactly when a correct answer exists in the corpus, and
  ``gold_ids`` is then that entire set. A constraint query whose only named dish
  is excluded is *not* answerable, and the correct result is no hit at all —
  never a similar dish.
* An attribute the corpus carries no evidence for is not "satisfied". Those
  queries are answerable=false with ``expected_unknown`` naming the dimensions
  the answer must admit to not knowing.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ingredient_catalog import ingredient_name_zh  # noqa: E402
from app.services.retrieval_projection import build_projection  # noqa: E402

SNAPSHOT = ROOT / "verification" / "data-completion" / "candidate_runtime.sqlite3"
OUT = ROOT / "verification" / "rag" / "annotation-set.json"

ALL_CATEGORIES = {
    "exact",
    "alias",
    "lexical",
    "constraint_conflict",
    "constraint_ok",
    "no_answer",
    "unknown_attributes",
}


def split_of(index: int) -> str:
    """One dish id belongs to exactly one split.

    The partition is by entity, so a paraphrase of a dish can never be tuned on
    in dev and then reported on in holdout — that would leak the tuning straight
    into the number being reported.
    """
    return "dev" if index % 3 == 0 else "holdout"


def main() -> int:
    projection, _dictionary = build_projection(SNAPSHOT, snapshot_label="s1-candidate")
    dishes = projection.of_kind("dish")
    skus = projection.of_kind("sku")

    entries: list[dict] = []
    counter = {"n": 0}

    def add(**entry) -> None:
        counter["n"] += 1
        entry.setdefault("entity_kind", "dish")
        entry.setdefault("relevance", 1)
        entry.setdefault("constraints", {})
        entry.setdefault("expected_unknown", [])
        entry.setdefault("answerable", True)
        entry.setdefault("gold_ids", [])
        entry["id"] = "q%03d" % counter["n"]
        entries.append(entry)

    def take(pool, split, k):
        return [item for item in pool if split_of(item[0]) == split][:k]

    exact = [(i, d) for i, d in enumerate(dishes) if d.name]
    alias_pool = []
    for i, dish in enumerate(dishes):
        for alias in dish.payload.get("aliases") or []:
            if alias and alias != dish.name:
                alias_pool.append((i, dish, alias))
                break
    lexical = [
        (i, d)
        for i, d in enumerate(dishes)
        if len([x for x in (d.payload.get("required_ingredient_ids") or []) if ingredient_name_zh(x)]) >= 2
    ]

    for i, dish in take(exact, "dev", 4):
        add(query=dish.name, gold_ids=[dish.target_id], category="exact", split="dev")
    for i, dish in take(exact, "holdout", 10):
        add(query=dish.name, gold_ids=[dish.target_id], category="exact", split="holdout")
    for i, dish, alias in take(alias_pool, "dev", 3):
        add(query=alias, gold_ids=[dish.target_id], category="alias", split="dev")
    for i, dish, alias in take(alias_pool, "holdout", 10):
        add(query=alias, gold_ids=[dish.target_id], category="alias", split="holdout")
    for i, dish in take(lexical, "dev", 3):
        names = [x for x in (ingredient_name_zh(y) for y in dish.payload["required_ingredient_ids"]) if x][:2]
        add(query="有" + "和".join(names) + "能做什么", gold_ids=[dish.target_id],
            category="lexical", split="dev")
    for i, dish in take(lexical, "holdout", 8):
        names = [x for x in (ingredient_name_zh(y) for y in dish.payload["required_ingredient_ids"]) if x][:2]
        add(query="想做点" + "和".join(names) + "的菜", gold_ids=[dish.target_id],
            category="lexical", split="holdout")

    def has_ingredient(dish, ingredient_id: str) -> bool:
        return (
            ingredient_id in (dish.payload.get("all_ingredient_ids") or [])
            or ingredient_id in (dish.payload.get("pantry_items") or [])
        )

    for ingredient_id in ("egg", "pork"):
        for split, count in (("dev", 1), ("holdout", 2)):
            picked = [d for i, d in enumerate(dishes) if split_of(i) == split and has_ingredient(d, ingredient_id)][:count]
            for dish in picked:
                # The named dish is excluded, so no correct answer exists. The
                # right behaviour is an explicit conflict with no hits.
                add(query=dish.name, category="constraint_conflict", split=split,
                    answerable=False, constraints={"excluded_ingredients": [ingredient_id]})
        for split, count in (("dev", 1), ("holdout", 4)):
            picked = [d for i, d in enumerate(dishes) if split_of(i) == split and not has_ingredient(d, ingredient_id)][:count]
            for dish in picked:
                # The named dish does not contain the excluded id, so it is a
                # real answer and must be found — this is the case that catches a
                # filter which over-excludes.
                add(query=dish.name, gold_ids=[dish.target_id], category="constraint_ok",
                    split=split, constraints={"excluded_ingredients": [ingredient_id]})

    for query in ("月亮陨石炖菜", "qwzxvbnm"):
        add(query=query, category="no_answer", split="dev", answerable=False)
    for query in ("外星人炒饭", "完全不存在的一道菜", "zzzqqq", "999999"):
        add(query=query, category="no_answer", split="holdout", answerable=False)

    add(query="清淡不辣的快手菜", category="unknown_attributes", split="dev",
        answerable=False, expected_unknown=["taste", "cook_minutes"])
    add(query="二十分钟能做完的菜", category="unknown_attributes", split="holdout",
        answerable=False, expected_unknown=["cook_minutes"])
    add(query="低脂低卡的家常菜", category="unknown_attributes", split="holdout",
        answerable=False, expected_unknown=["nutrition"])

    names = list(dict.fromkeys(s.name for s in skus if s.name))[:10]
    for position, name in enumerate(names):
        add(query=name, gold_ids=[s.target_id for s in skus if s.name == name], entity_kind="sku", category="exact",
            split="dev" if position % 4 == 0 else "holdout")

    # Mechanical typo probes stay in the same entity family as their exact form.
    for split in ("dev", "holdout"):
        entry = next(e for e in entries if e["split"] == split and e["category"] == "exact" and e["entity_kind"] == "dish")
        name = entry["query"]
        entry["query"] = name[:-1] + "错"
        entry["category"] = "fuzzy"

    problems = lint(entries)
    payload = {
        "version": "rag-anno-v3",
        "review_status": "automatically_derived_provisional_labels_require_human_review",
        "created_at": "2026-09-19",
        "semantics": {
            "answerable": "a correct answer exists in this corpus; gold_ids is exactly that set",
            "gold_ids": "every correct answer id; empty exactly when answerable is false",
            "relevance": "binary: every gold id is an equally correct answer",
            "constraint_conflict": "the only named dish is excluded; correct output is no hit, never a similar dish",
            "unknown_attributes": "the corpus has no evidence for this attribute; correct output is an explicit unknown",
            "split_rule": "split is assigned per dish id, so no entity's paraphrase crosses splits",
        },
        "snapshot": {
            "candidate_db_path": SNAPSHOT.as_posix(),
            "projection_snapshot_hash": projection.snapshot_hash,
            "dish_count": len(dishes),
            "sku_count": len(skus),
        },
        "splits": {"dev": "tuning only", "holdout": "reported only, never tuned on"},
        "lint": {"passed": not problems, "problems": problems},
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("entries", len(entries), dict(collections.Counter(e["split"] for e in entries)))
    print("categories", dict(collections.Counter(e["category"] for e in entries)))
    print("lint passed:", not problems, problems[:5])
    return 0 if not problems else 1


def lint(entries: list[dict]) -> list[str]:
    """Structural checks that a hand edit could otherwise quietly break."""
    problems: list[str] = []
    owner: dict[str, str] = {}
    for entry in entries:
        for gold in entry["gold_ids"]:
            if gold in owner and owner[gold] != entry["split"]:
                problems.append(f"gold {gold} crosses splits: {owner[gold]} / {entry['split']}")
            owner[gold] = entry["split"]
        if bool(entry["answerable"]) != bool(entry["gold_ids"]):
            problems.append(f"{entry['id']}: answerable={entry['answerable']} with gold={entry['gold_ids']}")
        if not entry["query"].strip() and entry["category"] != "no_answer":
            problems.append(f"{entry['id']}: empty query outside the no_answer category")
        if entry["expected_unknown"] and entry["answerable"]:
            problems.append(f"{entry['id']}: an answerable query cannot expect an unknown dimension")
    for split in ("dev", "holdout"):
        covered = {e["category"] for e in entries if e["split"] == split}
        missing = ALL_CATEGORIES - covered
        if missing:
            problems.append(f"{split} does not cover categories: {sorted(missing)}")
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
