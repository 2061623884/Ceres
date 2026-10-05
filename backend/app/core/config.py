"""Application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_mode: str = Field(default="live", alias="LLM_MODE")
    business_data_mode: str = Field(default="demo", alias="BUSINESS_DATA_MODE")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    memory_model: str = Field(default="", alias="MEMORY_MODEL")
    llm_timeout: float = Field(default=45.0, alias="LLM_TIMEOUT")
    llm_max_output_tokens: int = Field(default=1536, ge=256, le=8192, alias="LLM_MAX_OUTPUT_TOKENS")
    #: Max model calls per request: one understanding step, plus one grounded
    #: answer when a retrieve round ran. There is no repair loop.
    semantic_max_steps: int = Field(default=2, alias="SEMANTIC_MAX_STEPS")
    #: Read-only retrieval items allowed per lookup round.
    semantic_lookup_budget: int = Field(default=2, alias="SEMANTIC_LOOKUP_BUDGET")
    #: One semantic turn's own time budget, in seconds. It bounds the turn's
    #: cooperative check points — before and after each model call, around reads,
    #: before the proposal is executed, and before each plan mutation is
    #: persisted. It cannot interrupt a synchronous call that is already in
    #: flight, so it is a cooperative budget, not a hard wall-clock ceiling.
    semantic_turn_timeout_seconds: float = Field(
        default=90.0, alias="SEMANTIC_TURN_TIMEOUT_SECONDS"
    )
    #: Retrieval route selection. ``hybrid`` is the product default; ``lexical``
    #: is a deliberate deployment/offline-comparison mode, not a failure state.
    #: The model never changes this.
    retrieval_mode: str = Field(default="hybrid", alias="RETRIEVAL_MODE")
    #: Where published retrieval index versions live. Read-only at request time.
    #: **Empty means retrieval is not deployed here**, and the pre-index lookup
    #: path answers instead (reported as such). Setting it is the explicit
    #: deployment gate: once set, a missing or incompatible index is reported as
    #: ``unavailable`` rather than quietly served by the old path.
    retrieval_index_dir: str = Field(default="", alias="RETRIEVAL_INDEX_DIR")
    #: Embedding is a separate endpoint contract from chat: its own model, its
    #: own dimension, its own instruction. Deliberately not reused from the LLM
    #: fields above. These are read by the offline build CLI from the process
    #: environment; no dotenv file is loaded on its behalf.
    embedding_base_url: str = Field(default="", alias="EMBEDDING_BASE_URL")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="", alias="EMBEDDING_MODEL")
    embedding_revision: str = Field(default="", alias="EMBEDDING_REVISION")
    embedding_dimension: int = Field(default=1024, alias="EMBEDDING_DIMENSION")
    embedding_query_instruction: str = Field(
        default="", alias="EMBEDDING_QUERY_INSTRUCTION"
    )
    embedding_document_instruction: str = Field(
        default="", alias="EMBEDDING_DOCUMENT_INSTRUCTION"
    )
    embedding_timeout: float = Field(default=30.0, alias="EMBEDDING_TIMEOUT")
    source_database_path: str = Field(
        default="data/sale_guide.db", alias="SOURCE_DATABASE_PATH"
    )
    database_url: str = Field(
        default="sqlite:///data/runtime/sale_guide.sqlite3", alias="DATABASE_URL"
    )
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    frontend_port: int = Field(default=3000, alias="FRONTEND_PORT")
    internal_enabled: bool = Field(default=False, alias="INTERNAL_ENABLED")
    internal_admin_token: str = Field(default="", alias="INTERNAL_ADMIN_TOKEN")
    trace_retention_days: int = Field(default=7, alias="TRACE_RETENTION_DAYS")

    @property
    def root_dir(self) -> Path:
        return ROOT_DIR

    @property
    def source_db_path(self) -> Path:
        p = Path(self.source_database_path)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def runtime_db_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite:///"):
            rel = url.replace("sqlite:///", "")
            p = Path(rel)
            return p if p.is_absolute() else ROOT_DIR / p
        return ROOT_DIR / "data/runtime/sale_guide.sqlite3"

    def is_live_llm_configured(self) -> bool:
        return (
            self.llm_mode == "live"
            and bool(self.openai_api_key)
            and bool(self.openai_base_url)
            and bool(self.llm_model)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
