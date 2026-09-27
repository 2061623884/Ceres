"""Anonymous session identity via HttpOnly cookie."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.models.session import Owner

COOKIE_NAME = "sg_owner_id"


def get_or_create_owner(request: Request, response: Response, db: Session) -> str:
    owner_id = request.cookies.get(COOKIE_NAME)
    if owner_id:
        existing = db.get(Owner, owner_id)
        if existing:
            return owner_id
    owner_id = f"owner-{uuid.uuid4().hex[:16]}"
    db.add(Owner(id=owner_id, created_at=datetime.now(timezone.utc)))
    db.commit()
    response.set_cookie(
        key=COOKIE_NAME,
        value=owner_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 30,
    )
    return owner_id


def verify_internal_token(request: Request) -> bool:
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.internal_enabled:
        return False
    token = request.headers.get("X-Internal-Token", "")
    expected = settings.internal_admin_token
    if not expected:
        return False
    return secrets.compare_digest(token, expected)
