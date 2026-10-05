"""Owner-scoped reads of immutable purchase facts."""

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.order import Order, OrderItem


class OrderService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    def _serialize(self, order: Order) -> dict:
        items = self.db.query(OrderItem).filter_by(order_id=order.order_id).order_by(OrderItem.item_id).all()
        return {"order_id": order.order_id, "status": order.status, "created_at": order.created_at,
                "delivered_at": order.delivered_at, "total_fen": order.total_fen,
                "items": [{"item_id": i.item_id, "sku_id": i.sku_id, "product_name": i.product_name,
                           "quantity": i.quantity, "unit_price_fen": i.unit_price_fen,
                           "returnable": bool(i.returnable)} for i in items]}

    def list_orders(self) -> list[dict]:
        orders = self.db.query(Order).filter_by(user_id=self.owner_id).order_by(Order.created_at.desc()).limit(10).all()
        return [self._serialize(order) for order in orders]

    def get_order(self, order_id: str) -> dict:
        order = self.db.query(Order).filter_by(order_id=order_id, user_id=self.owner_id).first()
        if order is None:
            raise AppError(404, "ORDER_NOT_FOUND", "没有找到这个订单")
        return self._serialize(order)
