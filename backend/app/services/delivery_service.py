"""Delivery capability queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.store import DeliveryQuote


class DeliveryService:
    def __init__(self, db: Session):
        self.db = db

    def get_quote(self, store_id: str, zone_id: str = "zone-default") -> dict:
        quote = (
            self.db.query(DeliveryQuote)
            .filter_by(store_id=store_id, zone_id=zone_id)
            .first()
        )
        if not quote:
            return {"reachable": False, "eta_minutes": None, "zone_id": zone_id}
        return {
            "reachable": quote.reachable,
            "eta_minutes": quote.eta_minutes,
            "zone_id": quote.zone_id,
        }

    def check_delivery(self, store_id: str, zone_id: str = "zone-default") -> bool:
        return self.get_quote(store_id, zone_id).get("reachable", False)
