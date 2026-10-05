"""The current anonymous owner's persistent simulated orders."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import get_or_create_owner
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.get("")
def list_orders(request: Request, response: Response, db: Session = Depends(get_db)):
    owner_id = get_or_create_owner(request, response, db)
    return {"items": OrderService(db, owner_id).list_orders()}


@router.get("/{order_id}")
def get_order(order_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    owner_id = get_or_create_owner(request, response, db)
    return OrderService(db, owner_id).get_order(order_id)
