"""A themed product selection remains the selected object across public chat turns."""

from test_v3_routing_handoff import events, send

from support.semantic_agent import reply_only


ACTIVITY_ID = "green_reset"
PRODUCT_ID = "demo:green-reset-avocado-salad"


def _open_activity_chat(client):
    guide_response = client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "activity",
                "activity_id": ACTIVITY_ID,
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    )
    assert guide_response.status_code == 200, guide_response.text
    guide_session_id = guide_response.json()["session_id"]
    mercury_session_id = client.post("/api/v1/mercury/sessions").json()["session_id"]
    response = client.post(
        "/api/v1/chat/openings",
        json={
            "guide_session_id": guide_session_id,
            "mercury_session_id": mercury_session_id,
            "role": "keke",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _terminal(response):
    return next(
        event["payload"]
        for event in reversed(events(response))
        if event.get("type") == "turn.completed"
    )


def test_activity_and_selected_sku_context_survive_followup_turns(
    client, kev_api, semantic_provider
):
    def service_requests():
        return [
            row["request"]
            for row in kev_api["calls"]
            if "service" in row["request"]["questions"]
        ]

    kev_api["choices"]["capability"] = "chat"
    semantic_provider(
        [
            reply_only("这是 GREEN RESET｜今天轻一点专题。"),
            reply_only("可以看看这份成品沙拉。"),
            reply_only("我继续按这款活动商品为你查。"),
        ]
    )
    chat = _open_activity_chat(client)

    activity_response = send(
        client,
        chat,
        "GREEN RESET活动里有哪些限定成品？",
        "activity-context",
    )
    assert activity_response.status_code == 200
    activity_terminal = _terminal(activity_response)
    activity_state = service_requests()[0]["state"]
    assert activity_state["selected_object"]["view"]["page"] == "activity"
    assert activity_state["selected_object"]["view"]["activity_id"] == ACTIVITY_ID

    product_view = {
        "page": "product",
        "product_id": PRODUCT_ID,
        "activity_id": ACTIVITY_ID,
    }
    product_response = send(
        client,
        chat,
        "GREEN RESET活动里我想选牛油果成品沙拉。",
        "activity-product-context",
        expected_state_version=activity_terminal["state_version"],
        expected_session_version=activity_terminal["session_version"],
        view_context=product_view,
    )
    assert product_response.status_code == 200
    product_terminal = _terminal(product_response)
    product_state = service_requests()[1]["state"]
    assert product_state["selected_object"]["view"]["page"] == "product"
    assert product_state["selected_object"]["view"]["product_id"] == PRODUCT_ID
    assert product_state["selected_object"]["view"]["activity_id"] == ACTIVITY_ID

    followup = send(
        client,
        chat,
        "这款商品的报价是什么？",
        "activity-product-followup",
        expected_state_version=product_terminal["state_version"],
        expected_session_version=product_terminal["session_version"],
    )
    assert followup.status_code == 200
    followup_state = service_requests()[2]["state"]
    assert followup_state["selected_object"]["view"] == product_state["selected_object"]["view"]


def test_theme_finished_goods_have_simulated_sellable_offers(client):
    for sku_id in ("demo:green-reset-avocado-salad", "demo:green-reset-fruit-platter"):
        response = client.get(f"/api/v1/products/{sku_id}")
        assert response.status_code == 200
        product = response.json()
        assert product["sku_id"] == sku_id
        assert product["sellable"] is True
        assert product["price_fen"] > 0
        assert product["ingredient_ids"] == []
