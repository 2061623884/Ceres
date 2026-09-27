"""Schema validation tests."""

import pytest
from pydantic import ValidationError

from app.schemas.guide import TurnRequest
from app.schemas.cart import CartItemAddRequest


def test_turn_requires_expected_task_id_field():
    req = TurnRequest(
        request_id="r1",
        message="hello",
        expected_task_id=None,
        expected_state_version=0,
    )
    assert req.expected_task_id is None


def test_turn_rejects_negative_version():
    with pytest.raises(ValidationError):
        TurnRequest(
            request_id="r1",
            message="hello",
            expected_task_id=None,
            expected_state_version=-1,
        )


def test_cart_quantity_bounds():
    with pytest.raises(ValidationError):
        CartItemAddRequest(sku_id="demo:x", quantity=0)
