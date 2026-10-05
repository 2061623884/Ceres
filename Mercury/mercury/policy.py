"""政策检索：统计政策关键词在问句中的命中数。"""

from contextlib import closing

from mercury.db import connect


def search_policies(query, category=None, limit=3) -> dict:
    query = query or ""
    with closing(connect()) as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM policies WHERE category = ? ORDER BY policy_id", (category,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM policies ORDER BY policy_id").fetchall()

    hits = rank_policies(rows, query, category, limit)
    if not hits:
        return {"ok": True, "data": [], "message": "未找到相关政策"}
    return {"ok": True, "data": hits}


def rank_policies(rows, query, category, limit):
    """Keep policy selection consistent in integrated and standalone chats."""
    scored = []
    for r in rows:
        score = sum(1 for kw in r["keywords"].split(",") if kw.strip() and kw.strip() in query)
        # The shopping question "不喜欢能退吗" names a return rule without
        # using the noun "退货"; include its exclusions alongside its deadline.
        if r["category"] == "return" and any(term in query for term in ("能退", "退吗", "不喜欢")):
            score += 1
        if score > 0:
            scored.append((score, r))
    # 得分降序；同分时保持 policy_id 升序（rows 已按 policy_id 排序，sort 是稳定的）
    scored.sort(key=lambda x: -x[0])
    hits = [r for _, r in scored[:limit]]

    if not hits and category:
        hits = rows  # 指定了类别但全部 0 分：返回该类全部政策

    if not hits:
        return []
    return [
            {"policy_id": r["policy_id"], "category": r["category"], "title": r["title"], "content": r["content"]}
            for r in hits
        ]
