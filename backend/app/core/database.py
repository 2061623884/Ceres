"""Database session management."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_path_from_url(url: str) -> Path | None:
    if url.startswith("sqlite:///"):
        rel = url.replace("sqlite:///", "")
        settings = get_settings()
        p = Path(rel)
        return p if p.is_absolute() else settings.root_dir / p
    return None


def create_db_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    if url.startswith("sqlite"):
        path = _sqlite_path_from_url(url)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            url = "sqlite:///" + path.resolve().as_posix()
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # Live LLM holds the request briefly; WAL + busy timeout let concurrent
            # create_task / stream retry proceed instead of hard-locking.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


engine = create_db_engine()
# Keep ORM instances usable after mid-turn commit (release lock during LLM I/O).
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _duplicate_cart_operations(bind) -> list[tuple[str, str, int]]:
    with bind.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT owner_id, idempotency_key, COUNT(*) AS cnt
                FROM cart_operations
                GROUP BY owner_id, idempotency_key
                HAVING cnt > 1
                """
            )
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def ensure_runtime_schema(bind=None) -> None:
    """SQLite create_all does not alter existing tables; patch schema drift."""
    bind = bind or engine
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    for table in ("catalog_products", "purchase_templates"):
        if table not in tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "metadata_json" not in cols:
            with bind.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN metadata_json TEXT DEFAULT '{{}}'")
                )

    if "guide_sessions" in tables:
        cols = {c["name"] for c in inspector.get_columns("guide_sessions")}
        with bind.begin() as conn:
            for col, ddl in [
                ("session_version", "INTEGER DEFAULT 0"),
                ("message_seq", "INTEGER DEFAULT 0"),
                ("supply_store_id", "VARCHAR(64)"),
                ("supply_zone_id", "VARCHAR(64)"),
                ("view_context_json", "TEXT"),
                ("history_status", "VARCHAR(32) DEFAULT 'empty'"),
                ("candidate_dishes_json", "TEXT DEFAULT '[]'"),
                ("selected_dish_id", "VARCHAR(64)"),
            ]:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE guide_sessions ADD COLUMN {col} {ddl}"))

    if "guide_tasks" in tables:
        cols = {c["name"] for c in inspector.get_columns("guide_tasks")}
        with bind.begin() as conn:
            if "active_template_id" not in cols:
                conn.execute(
                    text("ALTER TABLE guide_tasks ADD COLUMN active_template_id VARCHAR(64)")
                )
            for col, ddl in [
                ("task_context_json", "TEXT"),
                ("supply_context_json", "TEXT"),
                ("pending_clarification_json", "TEXT"),
                ("root_task_id", "VARCHAR(64)"),
                ("source_task_id", "VARCHAR(64)"),
            ]:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE guide_tasks ADD COLUMN {col} {ddl}"))

    if "turn_request_records" in tables:
        # Request-level idempotency needs only the reservation fencing columns;
        # the request identity unique constraint comes from the model metadata.
        # The legacy run/step/alias/commit-key columns and indexes are left
        # exactly as they are on an existing database and are no longer created,
        # scanned or managed here.
        cols = {c["name"] for c in inspector.get_columns("turn_request_records")}
        with bind.begin() as conn:
            for col, ddl in [
                ("lease_token", "VARCHAR(64)"),
                ("lease_expires_at", "DATETIME"),
            ]:
                if col not in cols:
                    conn.execute(
                        text(f"ALTER TABLE turn_request_records ADD COLUMN {col} {ddl}")
                    )

    if "guide_operations" in tables:
        cols = {c["name"] for c in inspector.get_columns("guide_operations")}
        with bind.begin() as conn:
            for col, ddl in [
                ("attempt", "INTEGER DEFAULT 1"),
                ("lease_until", "DATETIME"),
                ("updated_at", "DATETIME"),
            ]:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE guide_operations ADD COLUMN {col} {ddl}"))

    if "trace_events" in tables:
        cols = {c["name"] for c in inspector.get_columns("trace_events")}
        if "event_id" not in cols:
            with bind.begin() as conn:
                conn.execute(text("ALTER TABLE trace_events ADD COLUMN event_id VARCHAR(64)"))
                conn.execute(
                    text(
                        "UPDATE trace_events SET event_id = 'evt-' || rowid "
                        "WHERE event_id IS NULL OR event_id = ''"
                    )
                )

    inspector = inspect(bind)
    if "business_events" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("business_events")}
        with bind.begin() as conn:
            if "client_event_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE business_events ADD COLUMN client_event_id VARCHAR(128)"
                    )
                )
            if "source" not in cols:
                conn.execute(
                    text("ALTER TABLE business_events ADD COLUMN source VARCHAR(32) DEFAULT 'server'")
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_business_events_client_event_id "
                    "ON business_events (client_event_id)"
                )
            )

    if "cart_operations" in inspector.get_table_names():
        dupes = _duplicate_cart_operations(bind)
        if dupes:
            sample = ", ".join(f"{owner}/{key}({cnt})" for owner, key, cnt in dupes[:3])
            raise RuntimeError(
                "Duplicate cart_operations idempotency keys detected before unique index migration: "
                f"{sample}. Run scripts/migrate_duplicate_ops.py to reconcile."
            )
        with bind.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_op_idempotency "
                    "ON cart_operations (owner_id, idempotency_key)"
                )
            )


def refresh_demo_product_images(bind=None) -> None:
    """Keep demo SKU photos in sync with fixtures without a full re-seed."""
    import json

    bind = bind or engine
    inspector = inspect(bind)
    if "catalog_products" not in inspector.get_table_names():
        return
    fixtures = get_settings().root_dir / "data" / "fixtures" / "demo-products.json"
    if not fixtures.is_file():
        return
    products = json.loads(fixtures.read_text(encoding="utf-8")).get("products", [])
    with bind.begin() as conn:
        for product in products:
            sku_id = product.get("sku_id")
            image_path = product.get("image_path")
            if not sku_id or not image_path:
                continue
            conn.execute(
                text(
                    "UPDATE catalog_products SET image_path = :image_path WHERE sku_id = :sku_id"
                ),
                {"image_path": image_path, "sku_id": sku_id},
            )


def init_db() -> None:
    from app.models import cart, catalog, conversation, memory, session as session_models, store, trace  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    refresh_demo_product_images()
