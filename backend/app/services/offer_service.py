"""Offer and pricing queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.store import Offer


class OfferService:
    def __init__(self, db: Session, store_id: str = "store-demo-01"):
        self.db = db
        self.store_id = store_id

    def get_offer(self, sku_id: str) -> Offer | None:
        return (
            self.db.query(Offer)
            .filter_by(store_id=self.store_id, sku_id=sku_id)
            .first()
        )

    def get_offers(self, sku_ids: list[str]) -> dict[str, Offer]:
        rows = (
            self.db.query(Offer)
            .filter(Offer.store_id == self.store_id, Offer.sku_id.in_(sku_ids))
            .all()
        )
        return {r.sku_id: r for r in rows}
