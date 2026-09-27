"""Internal debug API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.identity import verify_internal_token
from app.services.trace_service import BadcaseService, TraceService

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


def _require_internal(request: Request):
    if not verify_internal_token(request):
        raise AppError(403, "SESSION_FORBIDDEN", "Internal access denied")


@router.get("/traces")
def list_traces(request: Request, db: Session = Depends(get_db), limit: int = 50):
    _require_internal(request)
    return TraceService(db).list_traces(limit=limit)


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, request: Request, db: Session = Depends(get_db)):
    _require_internal(request)
    trace = TraceService(db).get_trace(trace_id)
    if not trace:
        raise AppError(404, "INVALID_INPUT", "Trace not found")
    return trace


class BadcaseCreate(BaseModel):
    trace_id: str
    category: str
    expected_behavior: str
    actual_behavior: str
    severity: str = "medium"


@router.post("/badcases")
def create_badcase(body: BadcaseCreate, request: Request, db: Session = Depends(get_db)):
    _require_internal(request)
    return BadcaseService(db).create(
        body.trace_id, body.category, body.expected_behavior, body.actual_behavior, body.severity
    )


@router.patch("/badcases/{badcase_id}")
def patch_badcase(badcase_id: str, status: str, request: Request, db: Session = Depends(get_db)):
    _require_internal(request)
    result = BadcaseService(db).update_status(badcase_id, status)
    if not result:
        raise AppError(404, "INVALID_INPUT", "Badcase not found")
    db.commit()
    return result


@router.get("/evaluation-reports")
def list_eval_reports(request: Request):
    _require_internal(request)
    from pathlib import Path

    reports_dir = Path(__file__).resolve().parents[3] / "evals" / "reports"
    if not reports_dir.exists():
        return []
    return [{"name": p.name, "path": str(p)} for p in sorted(reports_dir.glob("*.md"))]
