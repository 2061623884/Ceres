#!/usr/bin/env python3
"""Offline retrieval index builder: projection -> lexical + vector -> publish.

Never runs on the request path. Reads only the snapshot named by the S1 handoff
(plus the frozen ingredient dictionary), builds into a *new* directory, verifies
it, and only then moves the ``current`` pointer. If anything fails, the live
index is exactly what it was.

    python scripts/build_retrieval_index.py build
    python scripts/build_retrieval_index.py build --no-embed
    python scripts/build_retrieval_index.py verify --version idx-abc123
    python scripts/build_retrieval_index.py list
    python scripts/build_retrieval_index.py rollback --to idx-abc123

Credentials default to the process environment (``EMBEDDING_*``). An explicit
``build --env-file .env`` uses that file with environment overrides. Never prints a key.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.llm.embedding import (  # noqa: E402
    EmbeddingContract,
    EmbeddingUnavailable,
    HttpEmbeddingProvider,
    validate_and_normalize,
)
from app.services.retrieval_index import (  # noqa: E402
    INDEX_DB_NAME,
    MANIFEST_NAME,
    IndexUnavailable,
    embedding_contract_key,
    index_version_for,
    list_versions,
    load_index,
    publish,
    read_manifest,
    read_pointer,
    stage_and_commit,
    unpack_vector,
)
from app.services.retrieval_projection import build_projection  # noqa: E402

DEFAULT_HANDOFF = ROOT / "verification" / "data-completion" / "handoff.json"
DEFAULT_INDEX_ROOT = ROOT / "data" / "retrieval_index"
EMBED_BATCH = 32


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_handoff(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _resolve_candidate_db(args: argparse.Namespace) -> Path:
    if args.candidate_db:
        return Path(args.candidate_db)
    handoff = _load_handoff(Path(args.handoff))
    configured = handoff.get("candidate_db_path")
    if not configured:
        raise SystemExit(
            "no --candidate-db given and the handoff has no candidate_db_path; "
            "pass the S1 candidate snapshot explicitly"
        )
    return Path(configured)


# --------------------------------------------------------------------- vectors


def _embedding_provider(args: argparse.Namespace) -> Any | None:
    if args.no_embed:
        return None
    try:
        if getattr(args, "env_file", None):
            from app.core.config import Settings
            env_file = Path(args.env_file).resolve()
            if not env_file.is_file():
                raise SystemExit(f"environment file not found: {env_file}")
            return HttpEmbeddingProvider.from_settings(Settings(_env_file=env_file))
        return HttpEmbeddingProvider.from_env()
    except EmbeddingUnavailable as exc:
        raise SystemExit(
            f"embedding unavailable ({exc.code}); configure EMBEDDING_* or pass "
            "--env-file .env. For a deliberate lexical-only build use --no-embed."
        ) from None


def _embed_documents(
    docs: list[Any],
    provider: Any,
    *,
    reuse: dict[str, list[float]],
) -> tuple[dict[str, list[float]], int]:
    """Embed only what changed; reuse vectors whose document text is unchanged."""
    vectors: dict[str, list[float]] = dict(reuse)
    pending = [doc for doc in docs if doc.doc_id not in vectors]
    if not pending:
        return vectors, 0
    contract: EmbeddingContract = provider.contract
    embedded = 0
    for start in range(0, len(pending), EMBED_BATCH):
        batch = pending[start : start + EMBED_BATCH]
        # The provider owns instruction formatting on both documents and queries.
        texts = [doc.text for doc in batch]
        raw = provider.embed(texts, kind="document")
        checked = validate_and_normalize(raw, contract)
        if len(checked) != len(batch):
            raise SystemExit(
                f"provider returned {len(checked)} vectors for {len(batch)} documents"
            )
        for doc, vector in zip(batch, checked):
            vectors[doc.doc_id] = vector
        embedded += len(batch)
        print(f"[build] embedded {embedded}/{len(pending)}", flush=True)
    return vectors, embedded


def _reusable_vectors(
    *,
    index_root: Path,
    projection_docs: list[Any],
    contract: EmbeddingContract | None,
) -> dict[str, list[float]]:
    """Reuse vectors from the published index when the contract still matches.

    The document hash is the reuse key, so a changed text is re-embedded and an
    unchanged one is not. Without a contract match nothing is reused: a vector
    from a different model or instruction is not a vector from this one.
    """
    if contract is None:
        return {}
    try:
        index = load_index(index_root)
    except IndexUnavailable:
        return {}
    try:
        stored = index.embedding_contract
        if not stored or embedding_contract_key(stored) != embedding_contract_key(contract.as_dict()):
            return {}
        reused: dict[str, list[float]] = {}
        for doc in projection_docs:
            if index.doc_hashes.get(doc.doc_id) != doc.static_hash:
                continue
            vector = index.vector_for(doc.doc_id)
            if vector is not None:
                reused[doc.doc_id] = vector
        return reused
    except ValueError:
        return {}
    finally:
        index.close()


# ---------------------------------------------------------------------- verify


def verify_version_in(
    version_dir: Path,
    projection: Any,
    contract_dict: dict[str, Any] | None,
) -> dict[str, Any]:
    """Verify a *staged* directory against the projection that produced it.

    Staging has no ``current.json`` to resolve, and it has not been committed
    yet, so it is verified against the in-memory projection: every document's
    recomputed static hash and the manifest's counts must match what was just
    built, and — when the run embedded — every document must have a vector under
    the declared contract.
    """
    problems: list[str] = []
    db_path = version_dir / INDEX_DB_NAME
    if not db_path.is_file():
        return {"version": version_dir.name, "passed": False, "problems": ["missing index.sqlite3"]}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        counts = connection.execute(
            "SELECT (SELECT COUNT(*) FROM docs) AS docs, "
            "(SELECT COUNT(*) FROM docs_fts) AS fts, "
            "(SELECT COUNT(*) FROM embeddings) AS vectors"
        ).fetchone()
        if counts["docs"] != len(projection.docs):
            problems.append(f"docs table has {counts['docs']} rows, projection has {len(projection.docs)}")
        if counts["fts"] != counts["docs"]:
            problems.append(f"fts rows {counts['fts']} != docs rows {counts['docs']}")
        stored = {
            row["doc_id"]: row["static_hash"]
            for row in connection.execute("SELECT doc_id, static_hash FROM docs")
        }
        if stored != dict(projection.doc_hashes):
            missing = sorted(set(projection.doc_hashes) - set(stored))[:3]
            extra = sorted(set(stored) - set(projection.doc_hashes))[:3]
            problems.append(f"stored document hashes differ (missing={missing}, extra={extra})")
        if contract_dict:
            if counts["vectors"] != counts["docs"]:
                problems.append(
                    f"embeddings rows {counts['vectors']} != docs rows {counts['docs']}"
                )
            expected_key = embedding_contract_key(contract_dict)
            for row in connection.execute(
                "SELECT doc_id, dimension, contract_key, vector FROM embeddings LIMIT 5"
            ):
                if row["contract_key"] != expected_key:
                    problems.append(f"vector contract key mismatch for {row['doc_id']}")
                    break
                if row["dimension"] != contract_dict.get("dimension"):
                    problems.append(f"vector dimension mismatch for {row['doc_id']}")
                    break
                norm = sum(v * v for v in unpack_vector(row["vector"])) ** 0.5
                if abs(norm - 1.0) > 1e-3:
                    problems.append(f"vector not normalized for {row['doc_id']} (norm={norm:.5f})")
                    break
    finally:
        connection.close()
    manifest_path = version_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        problems.append("missing manifest.json")
    return {"version": version_dir.name, "passed": not problems, "problems": problems}


def verify_version(index_root: Path, version: str) -> dict[str, Any]:
    """Structural verification of one version directory. Returns findings."""
    problems: list[str] = []
    version_dir = index_root / version
    try:
        manifest = read_manifest(version_dir)
    except IndexUnavailable as exc:
        return {"version": version, "passed": False, "problems": [exc.message]}
    db_path = version_dir / INDEX_DB_NAME
    if not db_path.is_file():
        return {"version": version, "passed": False, "problems": [f"missing {INDEX_DB_NAME}"]}
    index = load_index(index_root, version=version)
    try:
        counts = index.connection().execute(
            "SELECT (SELECT COUNT(*) FROM docs) AS docs, "
            "(SELECT COUNT(*) FROM docs_fts) AS fts, "
            "(SELECT COUNT(*) FROM embeddings) AS vectors"
        ).fetchone()
        expected = int(manifest.get("counts", {}).get("docs") or 0)
        if counts["docs"] != expected:
            problems.append(f"docs table has {counts['docs']} rows, manifest says {expected}")
        if counts["fts"] != counts["docs"]:
            problems.append(f"fts rows {counts['fts']} != docs rows {counts['docs']}")
        doc_hashes = manifest.get("doc_hashes") or {}
        if len(doc_hashes) != counts["docs"]:
            problems.append("manifest doc_hashes do not cover every document")
        rows = index.connection().execute("SELECT doc_id, static_hash FROM docs").fetchall()
        for row in rows:
            if doc_hashes.get(row["doc_id"]) != row["static_hash"]:
                problems.append(f"doc hash mismatch for {row['doc_id']}")
                break
        contract = index.embedding_contract
        if contract:
            if counts["vectors"] != counts["docs"]:
                problems.append(
                    f"embeddings rows {counts['vectors']} != docs rows {counts['docs']}"
                )
            expected_key = embedding_contract_key(contract)
            from app.services.retrieval_index import unpack_vector

            for row in index.connection().execute(
                "SELECT doc_id, dimension, contract_key, vector FROM embeddings LIMIT 5"
            ).fetchall():
                if row["contract_key"] != expected_key:
                    problems.append(f"vector contract key mismatch for {row['doc_id']}")
                    break
                if row["dimension"] != contract.get("dimension"):
                    problems.append(f"vector dimension mismatch for {row['doc_id']}")
                    break
                vector = unpack_vector(row["vector"])
                norm = sum(v * v for v in vector) ** 0.5
                if abs(norm - 1.0) > 1e-3:
                    problems.append(f"vector not normalized for {row['doc_id']} (norm={norm:.5f})")
                    break
    finally:
        index.close()
    return {
        "version": version,
        "passed": not problems,
        "problems": problems,
        "counts": dict(counts) if counts else {},
        "manifest_id": manifest.get("manifest_id"),
    }


# ----------------------------------------------------------------------- build


def cmd_build(args: argparse.Namespace) -> int:
    index_root = Path(args.index_root)
    candidate_db = _resolve_candidate_db(args)
    handoff = _load_handoff(Path(args.handoff))
    if not candidate_db.is_file():
        raise SystemExit(f"candidate snapshot not found: {candidate_db}")
    started = time.monotonic()

    projection, dictionary = build_projection(
        candidate_db, snapshot_label=args.label or candidate_db.name
    )
    print(
        f"[build] projection: {len(projection.of_kind('dish'))} dishes, "
        f"{len(projection.of_kind('sku'))} skus, "
        f"snapshot_hash={projection.snapshot_hash}"
    )

    handoff_hash = str(handoff.get("fixture_projection_hash") or "")
    handoff_match = bool(handoff_hash) and handoff_hash in projection.snapshot_hash
    if handoff_hash and not handoff_match:
        print(
            "[build] NOTE: the handoff fixture_projection_hash does not match this build's "
            "projection hash. The handoff records no algorithm for it, so this is reported "
            "as unverified provenance rather than silently accepted."
        )

    provider = _embedding_provider(args)
    contract: EmbeddingContract | None = getattr(provider, "contract", None)
    contract_dict = contract.as_dict() if contract else None

    reuse: dict[str, list[float]] = {}
    if provider is not None and args.reuse:
        reuse = _reusable_vectors(
            index_root=index_root, projection_docs=projection.docs, contract=contract
        )
        if reuse:
            print(f"[build] reusing {len(reuse)} vectors from the published index")

    vectors = None
    embedded = 0
    if provider is not None:
        vectors, embedded = _embed_documents(projection.docs, provider, reuse=reuse)
        if len(vectors) != len(projection.docs):
            raise SystemExit("vector count does not cover every document; refusing to publish")

    version = index_version_for(projection, contract_dict)
    if args.dry_run:
        print(f"[build] dry run: would publish {version}")
        return 0

    from app.services.retrieval_index import write_index

    audit_only = {
        "candidate_db_path": str(candidate_db),
        "handoff_path": str(Path(args.handoff)) if args.handoff else None,
        "handoff_fixture_projection_hash": handoff_hash or None,
        "handoff_projection_hash_match": handoff_match,
        "handoff_projection_hash_algorithm": (
            "not documented in the repo; reported as unverified provenance"
        ),
        "built_at": _now(),
        "vectors_reused": len(reuse),
        "vectors_embedded": embedded,
        "index_root": str(index_root),
    }
    # Build into a unique staging directory, verify it there, and only then make
    # it the immutable <version> directory. A live version is never overwritten
    # in place: on Windows its file may be held by a reader, and half-written
    # index is worse than a failed build.
    def _build(staging: Path) -> None:
        manifest = write_index(
            target_dir=staging,
            projection=projection,
            dictionary=dictionary,
            embedding=contract_dict,
            vectors=vectors,
            reused={doc_id: "reused" for doc_id in reuse} or None,
            audit_only=audit_only,
        )
        print(f"[build] staged manifest_id={manifest['manifest_id']}")

    version_dir, report = stage_and_commit(
        index_root=index_root,
        version=version,
        build=_build,
        verify=lambda staging: verify_version_in(staging, projection, contract_dict),
    )
    if not report.get("passed"):
        print(
            "[build] verification FAILED. The current pointer was not touched and no "
            f"version directory was published: {report.get('problems')}"
        )
        return 1
    print(f"[build] committed immutable version {version_dir.name}")
    publish(index_root, version)
    elapsed = time.monotonic() - started
    print(f"[build] published {version} in {elapsed:.1f}s")
    print(json.dumps({"version": version, "verify": report, "audit_only": audit_only},
                     ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(
                {
                    "generated_at": _now(),
                    "version": version,
                    "verify": report,
                    "audit_only": audit_only,
                    "manifest": read_manifest(index_root / version),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


# -------------------------------------------------------------------- commands


def cmd_verify(args: argparse.Namespace) -> int:
    index_root = Path(args.index_root)
    version = args.version or read_pointer(index_root)
    if not version:
        print("[verify] no current index pointer and no --version given")
        return 1
    report = verify_version(index_root, version)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def cmd_list(args: argparse.Namespace) -> int:
    index_root = Path(args.index_root)
    current = read_pointer(index_root)
    versions = list_versions(index_root)
    print(f"index root: {index_root}")
    print(f"current   : {current or '(none)'}")
    for version in versions:
        manifest = read_manifest(index_root / version)
        marker = "*" if version == current else " "
        print(
            f" {marker} {version}  docs={manifest.get('counts', {}).get('docs')}  "
            f"embedding={(manifest.get('embedding') or {}).get('model') or 'none'}"
        )
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    """Move the pointer back to an existing, structurally healthy version.

    Refuses to roll back to something that does not verify: a rollback that
    swaps one broken index for another is worse than a clear failure.
    """
    index_root = Path(args.index_root)
    target = args.to
    if target not in list_versions(index_root):
        print(f"[rollback] version {target} is not present under {index_root}")
        return 1
    report = verify_version(index_root, target)
    if not report["passed"]:
        print(f"[rollback] refusing: {target} does not verify: {report['problems']}")
        return 1
    # The target must load under the current contract rules (schema version,
    # tokenizer, and the content hashes recomputed from what is stored). A
    # version that only *looks* healthy is not a rollback target.
    try:
        target_index = load_index(index_root, version=target)
        target_snapshot = target_index.snapshot_hash
        target_index.close()
    except IndexUnavailable as exc:
        print(f"[rollback] refusing: {target} is not loadable ({exc.code}): {exc.message}")
        return 1
    previous = read_pointer(index_root)
    previous_snapshot = None
    if previous:
        try:
            prev_index = load_index(index_root, version=previous)
            previous_snapshot = prev_index.snapshot_hash
            prev_index.close()
        except IndexUnavailable:
            previous_snapshot = None
    if (
        previous_snapshot
        and target_snapshot != previous_snapshot
        and not args.allow_corpus_change
    ):
        # Rolling back onto a different static projection changes which corpus
        # is being served. That is sometimes exactly what an operator wants
        # after a bad data batch, so it is allowed — but never by accident.
        print(
            "[rollback] refusing: target was built from a different static projection "
            f"({target_snapshot} != {previous_snapshot}). "
            "Pass --allow-corpus-change if serving the older corpus is intended."
        )
        return 1
    publish(index_root, target)
    print(
        f"[rollback] current {previous} -> {target} "
        f"(projection_snapshot_hash={target_snapshot})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_retrieval_index.py",
        description=(
            "Build, verify, list and roll back the offline retrieval index. "
            "Reads only the S1 candidate snapshot; never writes to a business database."
        ),
    )
    parser.add_argument(
        "--index-root", default=str(DEFAULT_INDEX_ROOT),
        help="index root directory (default: data/retrieval_index)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build one new index version and publish it")
    build.add_argument("--candidate-db", default=None,
                       help="S1 snapshot sqlite path (default: handoff candidate_db_path)")
    build.add_argument("--handoff", default=str(DEFAULT_HANDOFF),
                       help="path to the S1 handoff JSON (default: verification/data-completion/handoff.json)")
    build.add_argument("--label", default="", help="snapshot label recorded in the manifest")
    build.add_argument("--no-embed", action="store_true",
                       help="build the lexical index only; the vector route then degrades with a real reason")
    build.add_argument("--env-file", default=None,
                       help="explicit dotenv file for embedding configuration; environment overrides it")
    build.add_argument("--no-reuse", dest="reuse", action="store_false", default=True,
                       help="do not reuse vectors from the published index")
    # A version directory is immutable once committed: the version name is a
    # function of the projection and the embedding contract, so an existing one
    # already *is* this build. There is deliberately no --force.
    build.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    build.add_argument("--report", default=None, help="write a JSON build report to this path")
    build.set_defaults(func=cmd_build)

    verify = sub.add_parser("verify", help="structurally verify one index version")
    verify.add_argument("--version", default=None, help="version to verify (default: current pointer)")
    verify.set_defaults(func=cmd_verify)

    listing = sub.add_parser("list", help="list index versions and the current pointer")
    listing.set_defaults(func=cmd_list)

    rollback = sub.add_parser("rollback", help="point current back at an existing healthy version")
    rollback.add_argument("--to", required=True, help="version to roll back to")
    rollback.add_argument(
        "--allow-corpus-change", action="store_true",
        help="permit rolling back onto a different static projection (older corpus)",
    )
    rollback.set_defaults(func=cmd_rollback)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
