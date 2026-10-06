"""Pytest fixtures."""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("LLM_MODE", "live")
os.environ.setdefault("BUSINESS_DATA_MODE", "demo")


@pytest.fixture
def kev_api(monkeypatch):
    """Stub only the external Kev HTTP boundary used by controlled guide tests."""
    import httpx

    choices = {"service": "stay_current", "capability": "chat"}
    calls = []
    original_post = httpx.Client.post

    def post(client, url, *args, **kwargs):
        if not str(url).rstrip("/").endswith("/v1/systemone"):
            return original_post(client, url, *args, **kwargs)

        payload = kwargs["json"]
        question, spec = next(iter(payload["questions"].items()))
        if (
            question == "service"
            and httpx.URL(str(url)).host == "kev-controlled.invalid"
        ):
            return original_post(client, url, *args, **kwargs)
        labels = list(spec["criteria"])
        selected = choices[question]
        probabilities = {
            label: 1.0 if label == selected else 0.0 for label in labels
        }
        raw = {
            "model": "kev-latest",
            "answers": {
                question: {
                    "type": "choice",
                    "choice": selected,
                    "probabilities": probabilities,
                }
            },
        }
        calls.append({"request": payload, "response": raw})
        return httpx.Response(
            200,
            json=raw,
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    return {"choices": choices, "calls": calls}


@pytest.fixture
def internal_trace_headers(monkeypatch):
    """Enable the existing internal trace read API with an ephemeral test token."""
    token = secrets.token_urlsafe(18)
    monkeypatch.setenv("INTERNAL_ENABLED", "true")
    monkeypatch.setenv("INTERNAL_ADMIN_TOKEN", token)
    return {"X-Internal-Token": token}


@pytest.fixture()
def offline_providers(monkeypatch):
    """The generic test double, installed on the one provider factory.

    The name is kept because the suites already request it; what it installs is
    the **semantic** stand-in (``support.reactive_semantic``), which follows
    retrieve → add → answer through the real loop, read port and executor. A
    suite that only needs "a real plan on screen" keeps working without scripting
    every turn.

    It deliberately accepts no script: a retired ``ScriptedTurn`` list cannot be
    honoured by the one chain, and silently ignoring it would let a test assert
    against a route that no longer exists. Scripted turns now go through
    ``semantic_provider`` in the proposal protocol.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from support.reactive_semantic import ReactiveSemanticProvider

    def _install(*args, **kwargs):
        if args or kwargs:
            raise AssertionError(
                "offline_providers 不再接受旧协议脚本：该链已退役。"
                "请改用 semantic_provider([...]) 显式写出语义提案"
                "（support.semantic_agent 提供 lookup_then_add_id 等构造器）。"
            )
        provider = ReactiveSemanticProvider()
        monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)
        return provider

    return _install


@pytest.fixture()
def semantic_provider(monkeypatch):
    """Install a scripted provider for the one decision chain.

    ``_install(proposals)`` returns the provider so a test can inspect the
    requests the loop actually sent. It patches ``get_semantic_provider`` — the
    only provider factory the runtime still has.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from support.semantic_agent import ScriptedSemanticProvider

    def _install(proposals):
        provider = ScriptedSemanticProvider(proposals)
        monkeypatch.setattr(
            "app.llm.provider.get_semantic_provider", lambda: provider
        )
        return provider

    return _install


@pytest.fixture()
def reactive_agent(monkeypatch):
    """Install the generic semantic stand-in and hand it back.

    Same object as ``offline_providers`` installs, returned directly so an
    autouse fixture can request it in one line (``def _offline_agent(reactive_agent):
    return reactive_agent``). It is the *model* that is simulated here — never the
    loop, the executor or a business rule.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from support.reactive_semantic import ReactiveSemanticProvider

    provider = ReactiveSemanticProvider()
    monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)
    return provider


@pytest.fixture()
def test_db_url(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    return f"sqlite:///{db_path}"


@pytest.fixture()
def source_database_path():
    return ROOT / "data" / "sale_guide.db"


@pytest.fixture()
def client(test_db_url, monkeypatch, source_database_path, kev_api):
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setenv("SOURCE_DATABASE_PATH", str(source_database_path))

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core import database as db_module
    from app.core.database import Base
    from app.models import cart, catalog, conversation, session as session_models, store, trace  # noqa: F401

    engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    db_module.engine = engine
    db_module.SessionLocal = TestSession

    # Seed minimal data
    import sys
    sys.path.insert(0, str(ROOT))
    db = TestSession()
    from scripts.seed_runtime import (
        ensure_catalog_schema,
        ensure_metadata_schema,
        ensure_purchase_template_schema,
        seed_chinese_dish_templates,
        seed_demo_products,
        seed_from_source,
        seed_reviews,
        seed_store_offers,
        seed_templates,
    )

    ensure_purchase_template_schema(engine)
    ensure_metadata_schema(engine)
    ensure_catalog_schema(engine)

    settings = get_settings()
    seed_from_source(db, settings)
    seed_demo_products(db)
    seed_reviews(db)
    seed_store_offers(db)
    seed_templates(db)
    seed_chinese_dish_templates(db)
    db.commit()
    db.close()

    from app.main import app

    app.dependency_overrides[db_module.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture()
def db_session(test_db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setenv("SOURCE_DATABASE_PATH", str(ROOT / "data" / "sale_guide.db"))

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core.database import Base
    from app.models import cart, catalog, conversation, session as session_models, store, trace  # noqa: F401

    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    import sys

    sys.path.insert(0, str(ROOT))
    db = TestSession()
    from scripts.seed_runtime import (
        ensure_catalog_schema,
        ensure_metadata_schema,
        ensure_purchase_template_schema,
        seed_chinese_dish_templates,
        seed_demo_products,
        seed_from_source,
        seed_reviews,
        seed_store_offers,
        seed_templates,
    )

    ensure_purchase_template_schema(engine)
    ensure_metadata_schema(engine)
    ensure_catalog_schema(engine)
    settings = get_settings()
    seed_from_source(db, settings)
    seed_demo_products(db)
    seed_reviews(db)
    seed_store_offers(db)
    seed_templates(db)
    seed_chinese_dish_templates(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()
        get_settings.cache_clear()
