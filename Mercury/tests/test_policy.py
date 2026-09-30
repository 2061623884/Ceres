from mercury.policy import search_policies


def ids(result):
    return [p["policy_id"] for p in result["data"]]


def test_refund_arrival(db):
    assert "P-REF-02" in ids(search_policies("退款多久到账"))


def test_fresh_food_return(db):
    assert "P-RET-02" in ids(search_policies("生鲜能退货吗"))


def test_delivery_time(db):
    assert "P-DEL-01" in ids(search_policies("配送要多久"))


def test_category_without_hit_returns_whole_category(db):
    result = search_policies("随便问问", category="return")
    assert ids(result) == ["P-RET-01", "P-RET-02"]


def test_no_hit_returns_empty(db):
    result = search_policies("今天天气怎么样")
    assert result == {"ok": True, "data": [], "message": "未找到相关政策"}


def test_at_most_three_results(db):
    # 同时命中多条政策时最多返回 3 条
    assert len(search_policies("退款退货配送延迟到账生鲜")["data"]) == 3


def test_content_comes_from_policies_table(db):
    db("UPDATE policies SET content = ? WHERE policy_id = ?", ("测试改写后的到账说明", "P-REF-02"))
    hit = next(p for p in search_policies("退款多久到账")["data"] if p["policy_id"] == "P-REF-02")
    assert hit["content"] == "测试改写后的到账说明"
