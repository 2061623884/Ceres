"""Local retrieval readiness, not a remote provider liveness claim."""
from app.services.retrieval_service import RetrievalService


def retrieval_readiness(db) -> dict:
    service = RetrievalService(db, store_id="store-demo-01", delivery_zone_id="zone-default")
    result = {"status": "unavailable", "mode": service.mode,
              "index_version": None, "embedding_model": None,
              "remote_checked": False, "reason": None}
    try:
        if not service.index_configured:
            return {**result, "reason": "RETRIEVAL_NOT_CONFIGURED"}
        index = service._load()
        if index is None:
            return {**result, "reason": "INDEX_UNAVAILABLE"}
        result.update(index_version=index.version, counts=index.manifest.get("counts"),
                      embedding_model=(index.embedding_contract or {}).get("model"))
        if not service.describes_runtime_db():
            return {**result, "reason": "INDEX_STALE"}
        if service.mode == "lexical":
            return {**result, "status": "ready"}
        if service.mode != "hybrid":
            return {**result, "reason": "INVALID_RETRIEVAL_MODE"}
        if not index.has_vectors():
            return {**result, "status": "degraded", "reason": "VECTOR_INDEX_MISSING"}
        if service._provider() is None:
            return {**result, "status": "degraded", "reason": "EMBEDDING_NOT_CONFIGURED"}
        service._require_contract_match(index.embedding_contract)
        return {**result, "status": "ready"}
    except Exception as exc:
        # Expose a code only: never paths, credentials or arbitrary HTTP errors.
        return {**result, "status": "degraded", "reason": getattr(exc, "code", "INDEX_UNAVAILABLE")}
    finally:
        if service._index is not None:
            service._index.close()
