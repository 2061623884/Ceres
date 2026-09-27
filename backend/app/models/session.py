"""Guide session and task models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class GuideSession(Base):
    __tablename__ = "guide_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    message_seq: Mapped[int] = mapped_column(Integer, default=0)
    supply_store_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supply_zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    view_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    history_status: Mapped[str] = mapped_column(String(32), default="empty")
    #: Ordered dish candidates the server displayed, kept at session level so
    #: "the second one" resolves even when no purchase task exists yet.
    candidate_dishes_json: Mapped[str] = mapped_column(Text, default="[]")
    #: Dish the user explicitly picked out of the displayed candidates.
    selected_dish_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class GuideSemanticContext(Base):
    """Server-owned dialogue state, independent of a purchase task or history."""

    __tablename__ = "guide_semantic_contexts"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    context_json: Mapped[str] = mapped_column(Text, default="{}")


class GuideTask(Base):
    __tablename__ = "guide_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step: Mapped[str] = mapped_column(String(32), default="understanding")
    requirements_json: Mapped[str] = mapped_column(Text, default="{}")
    requirements_version: Mapped[int] = mapped_column(Integer, default=1)
    missing_constraints_json: Mapped[str] = mapped_column(Text, default="[]")
    candidate_set_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_products_json: Mapped[str] = mapped_column(Text, default="[]")
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_count: Mapped[int] = mapped_column(Integer, default=0)
    replacement_count: Mapped[int] = mapped_column(Integer, default=0)
    active_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_confirmed: Mapped[bool] = mapped_column(default=False)
    confirmation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cart_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    task_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supply_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_clarification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
