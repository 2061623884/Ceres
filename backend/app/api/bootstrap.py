"""Bootstrap and health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.identity import get_or_create_owner

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    from app.services.retrieval_readiness import retrieval_readiness
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "llm_mode": settings.llm_mode,
        "llm_configured": settings.is_live_llm_configured(),
        "retrieval": retrieval_readiness(db),
        "business_data_mode": settings.business_data_mode,
    }


@router.get("/api/v1/bootstrap")
def bootstrap(request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    owner_id = get_or_create_owner(request, response, db)
    db.commit()
    return {
        "owner_id": owner_id,
        "store_id": "store-demo-01",
        "delivery_zone_id": "zone-default",
        "llm_mode": settings.llm_mode,
        "business_data_mode": settings.business_data_mode,
        "demo_notice": "演示门店，价格、库存及配送为模拟数据",
    }
