"""Persistent simulated orders share Mercury's order facts."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("owners.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="paid")
    total_fen: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat())
    delivered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(256))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_fen: Mapped[int] = mapped_column(Integer)
    returnable: Mapped[int] = mapped_column(Integer, default=1)


class MercurySession(Base):
    __tablename__ = "mercury_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"), index=True)
    selected_order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.order_id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat())


class OrderDelivery(Base):
    __tablename__ = "deliveries"

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    latest_description: Mapped[str] = mapped_column(Text)
    eta: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40))


class OrderRefund(Base):
    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    amount_fen: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(40))


class OrderReturn(Base):
    __tablename__ = "returns"

    return_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("order_items.item_id"))
    refund_amount_fen: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(40))


class AfterSalesPolicy(Base):
    __tablename__ = "policies"

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    keywords: Mapped[str] = mapped_column(Text)
