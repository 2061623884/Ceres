"""Store and offer models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Store(Base):
    __tablename__ = "stores"

    store_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_demo: Mapped[bool] = mapped_column(default=True)
    delivery_zone_id: Mapped[str] = mapped_column(String(64), default="zone-default")


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("store_id", "sku_id", name="uq_store_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    price_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    available_qty: Mapped[int] = mapped_column(Integer, default=99)
    sellable: Mapped[bool] = mapped_column(default=True)
    offer_version: Mapped[int] = mapped_column(Integer, default=1)
    is_demo: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DeliveryQuote(Base):
    __tablename__ = "delivery_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reachable: Mapped[bool] = mapped_column(default=True)
    eta_minutes: Mapped[int] = mapped_column(Integer, default=45)
    queried_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
