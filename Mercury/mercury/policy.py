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

    scored = []
    for r in rows:
        score = sum(1 for kw in r["keywords"].split(",") if kw.strip() and kw.strip() in query)
        if score > 0:
            scored.append((score, r))
    # 得分降序；同分时保持 policy_id 升序（rows 已按 policy_id 排序，sort 是稳定的）
    scored.sort(key=lambda x: -x[0])
    hits = [r for _, r in scored[:limit]]

    if not hits and category:
        hits = rows  # 指定了类别但全部 0 分：返回该类全部政策

    if not hits:
        return {"ok": True, "data": [], "message": "未找到相关政策"}
    return {
        "ok": True,
        "data": [
            {"policy_id": r["policy_id"], "category": r["category"], "title": r["title"], "content": r["content"]}
            for r in hits
        ],
    }
