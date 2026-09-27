"""The derived retrieval index: FTS5 lexical table + float32 vectors.

One SQLite file per index version, plus a manifest, plus a ``current.json``
pointer. The pointer is the only thing swapped on publish, and it is swapped
with ``os.replace`` — so a build that dies half way leaves the live index exactly
as it was, and a rollback is a pointer write rather than a restore.

Nothing here runs on the request path except :func:`load_index`, which is
read-only. Building writes only inside the index root.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.services.retrieval_projection import (
    LEXICAL_TOKENIZER_VERSION,
    SCHEMA_VERSION,
    TEXT_TEMPLATE_VERSION,
    Projection,
    query_terms,
    tokenized_text,
)

MANIFEST_NAME = "manifest.json"
POINTER_NAME = "current.json"
INDEX_DB_NAME = "index.sqlite3"

#: Bumped whenever the *stored* shape changes (not just the code): the pointer
#: version name is derived from it, so an index written by an older layout can
#: never be mistaken for a current one.
INDEX_SCHEMA_VERSION = 3
#: A vector row is only reused when the whole embedding contract matches, not
#: just the model name: dimension, normalization and both instructions decide
#: whether two vectors are even comparable.
EMBEDDING_CONTRACT_KEYS = (
    "model",
    "revision",
    "dimension",
    "dtype",
    "normalize",
    "query_instruction",
    "document_instruction",
    "text_template_version",
)


class IndexUnavailable(RuntimeError):
    """The index is missing, unreadable, or not the shape this code expects."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------ float32 math


def normalize_vector(values: Iterable[float]) -> list[float]:
    """Unit-normalize, or refuse. A zero vector has no direction to compare."""
    items = [float(v) for v in values]
    norm = math.sqrt(sum(v * v for v in items))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("vector has no finite non-zero norm")
    return [v / norm for v in items]


def validate_vector(values: Any, *, dimension: int) -> list[float]:
    """Strict shape check: right length, all finite, normalized to unit length.

    Anything else is a broken provider or a corrupt row, and both must be
    reported rather than silently scored as a poor match.
    """
    if not isinstance(values, (list, tuple)):
        raise ValueError("vector must be a list of floats")
    if len(values) != dimension:
        raise ValueError(f"vector dimension {len(values)} != contract dimension {dimension}")
    out: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("vector contains a non-numeric value") from None
        if not math.isfinite(number):
            raise ValueError("vector contains a non-finite value")
        out.append(number)
    norm = math.sqrt(sum(v * v for v in out))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("vector has no finite non-zero norm")
    if abs(norm - 1.0) > 1e-3:
        raise ValueError(f"vector is not normalized (norm={norm:.6f})")
    return out


def pack_vector(values: list[float]) -> bytes:
    return array("f", values).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def cosine(left: list[float], right: list[float]) -> float:
    """Exact cosine. Both operands are stored normalized, so this is a dot product."""
    if len(left) != len(right):
        raise ValueError("dimension mismatch")
    return sum(a * b for a, b in zip(left, right))


def embedding_contract_key(contract: dict[str, Any]) -> str:
    return json.dumps(
        {key: contract.get(key) for key in EMBEDDING_CONTRACT_KEYS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


# -------------------------------------------------------------------- manifest


def build_manifest(
    *,
    projection: Projection,
    dictionary: dict[str, Any],
    embedding: dict[str, Any] | None,
    index_version: str,
    audit_only: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The manifest is what makes an index auditable after the fact."""
    manifest: dict[str, Any] = {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "projection_snapshot_hash": projection.snapshot_hash,
        "projection_snapshot": dict(projection.snapshot),
        "lexical_tokenizer_version": LEXICAL_TOKENIZER_VERSION,
        "text_template_version": projection.snapshot.get("text_template_version"),
        #: Content hashes, not version strings. A version string can be declared
        #: without being true; these are recomputed from what is actually stored.
        "content_hashes": {
            "ingredient_maps_hash": _sha256_of(json.dumps(frozen_ingredient_maps(), ensure_ascii=False, sort_keys=True)),
            "dictionary_hash": _sha256_of(
                json.dumps(_serializable_dictionary(dictionary), ensure_ascii=False, sort_keys=True)
            ),
            "text_template_hash": _sha256_of(
                json.dumps(
                    {
                        "template": TEXT_TEMPLATE_VERSION,
                        "docs": [
                            [doc.doc_id, doc.text] for doc in projection.docs
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        },
        "doc_hashes": dict(projection.doc_hashes),
        "embedding": dict(embedding) if embedding else None,
        "counts": {
            "docs": len(projection.docs),
            "dishes": len(projection.of_kind("dish")),
            "skus": len(projection.of_kind("sku")),
        },
        "audit_only": dict(audit_only or {}),
    }
    manifest["manifest_id"] = "sha256:" + _manifest_id(manifest)
    return manifest


def _sha256_of(payload: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _serializable_dictionary(dictionary: dict[str, Any]) -> dict[str, Any]:
    """The dictionary as it is stored, so its hash can be recomputed exactly."""
    return {
        **dictionary,
        "single_chars": sorted(dictionary.get("single_chars") or []),
        "by_length": {
            str(length): list(terms)
            for length, terms in (dictionary.get("by_length") or {}).items()
        },
        "single_char_expansions": {
            char: list(terms)
            for char, terms in (dictionary.get("single_char_expansions") or {}).items()
        },
    }


def _manifest_id(manifest: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps(
        {k: v for k, v in manifest.items() if k != "manifest_id"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def index_version_for(projection: Projection, embedding: dict[str, Any] | None) -> str:
    """A version name that changes whenever anything that matters changes."""
    digest = _manifest_id(
        {
            "projection": projection.snapshot_hash,
            "embedding": embedding or {},
            "lexical": LEXICAL_TOKENIZER_VERSION,
            "schema": INDEX_SCHEMA_VERSION,
        }
    )[:16]
    return f"idx-{digest}"


# ----------------------------------------------------------------------- write


def frozen_ingredient_maps() -> dict[str, dict[str, str]]:
    """The canonical ingredient names/aliases, frozen into the index.

    Resolved at **build** time and stored in the index, so the request path
    never re-reads the mutable fixture. An exclusion the shopper states is
    resolved against the same dictionary the index was built from.
    """
    from app.services.ingredient_catalog import load_ingredient_catalog

    catalog = load_ingredient_catalog()
    names = {
        ingredient_id: str(item.get("name_zh") or ingredient_id)
        for ingredient_id, item in catalog["ingredients"].items()
    }
    aliases: dict[str, str] = {}
    for ingredient_id, item in catalog["ingredients"].items():
        aliases[str(item.get("name_zh") or ingredient_id)] = ingredient_id
        aliases[ingredient_id] = ingredient_id
        for alias in item.get("aliases") or []:
            aliases[str(alias)] = ingredient_id
    return {"names": names, "aliases": aliases}


def write_index(
    *,
    target_dir: Path,
    projection: Projection,
    dictionary: dict[str, Any],
    embedding: dict[str, Any] | None,
    vectors: dict[str, list[float]] | None,
    reused: dict[str, str] | None = None,
    audit_only: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one complete index version into a **fresh, empty** directory.

    A published version directory is immutable. Rewriting one in place would
    delete a file a reader may currently hold — on Windows that is a
    ``PermissionError`` at best and a half-written index at worst. Callers build
    into staging via :func:`stage_and_commit`; this refuses to clobber.
    """
    if (target_dir / INDEX_DB_NAME).exists():
        raise IndexUnavailable(
            "INDEX_EXISTS",
            f"refusing to overwrite the existing immutable index at {target_dir}",
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    db_path = target_dir / INDEX_DB_NAME
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE docs (doc_id TEXT PRIMARY KEY, kind TEXT, target_id TEXT, "
            "name TEXT, text TEXT, tokens TEXT, payload_json TEXT, static_hash TEXT)"
        )
        connection.execute("CREATE INDEX idx_docs_kind ON docs(kind)")
        connection.execute(
            "CREATE VIRTUAL TABLE docs_fts USING fts5(tokens, doc_id UNINDEXED, tokenize='unicode61')"
        )
        connection.execute(
            "CREATE TABLE embeddings (doc_id TEXT PRIMARY KEY, dimension INTEGER, "
            "contract_key TEXT, vector BLOB)"
        )
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        contract_key = embedding_contract_key(embedding) if embedding else None
        for doc in projection.docs:
            connection.execute(
                "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?)",
                (
                    doc.doc_id,
                    doc.kind,
                    doc.target_id,
                    doc.name,
                    doc.text,
                    tokenized_text(doc.text, dictionary),
                    json.dumps(doc.payload, ensure_ascii=False, sort_keys=True),
                    projection.doc_hashes[doc.doc_id],
                ),
            )
            connection.execute(
                "INSERT INTO docs_fts (tokens, doc_id) VALUES (?, ?)",
                (tokenized_text(doc.text, dictionary), doc.doc_id),
            )
        if vectors:
            for doc_id, vector in vectors.items():
                connection.execute(
                    "INSERT INTO embeddings VALUES (?,?,?,?)",
                    (doc_id, len(vector), contract_key, pack_vector(vector)),
                )
        connection.execute(
            "INSERT INTO meta VALUES ('dictionary', ?)",
            (
                json.dumps(
                    _serializable_dictionary(dictionary), ensure_ascii=False, sort_keys=True
                ),
            ),
        )
        connection.execute(
            "INSERT INTO meta VALUES ('ingredient_maps', ?)",
            (json.dumps(frozen_ingredient_maps(), ensure_ascii=False, sort_keys=True),),
        )
        connection.execute(
            "INSERT INTO meta VALUES ('manifest', ?)",
            (json.dumps(build_manifest(
                projection=projection,
                dictionary=dictionary,
                embedding=embedding,
                index_version=target_dir.name,
                audit_only=audit_only,
            ), ensure_ascii=False, sort_keys=True),),
        )
        if reused:
            connection.execute(
                "INSERT INTO meta VALUES ('reused_vectors', ?)",
                (json.dumps(reused, ensure_ascii=False, sort_keys=True),),
            )
        connection.commit()
    finally:
        connection.close()

    manifest = read_manifest(target_dir)
    (target_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def stage_and_commit(
    *,
    index_root: Path,
    version: str,
    build: Any,
    verify: Any,
) -> tuple[Path, Any]:
    """Build into unique staging, verify, then commit atomically as ``version``.

    Order matters and is the whole point:

    1. build in ``<root>/.staging-<random>`` — the live index is untouched;
    2. verify the staged copy (counts, hashes, contract);
    3. only then ``os.replace`` it into ``<root>/<version>``.

    A version name is derived from the projection and the embedding contract, so
    an existing ``<root>/<version>`` already *is* this build. Staging is then
    discarded rather than overwriting an immutable directory.
    """
    import uuid

    index_root.mkdir(parents=True, exist_ok=True)
    staging = index_root / f".staging-{uuid.uuid4().hex[:12]}"
    try:
        build(staging)
        report = verify(staging)
        if isinstance(report, dict) and not report.get("passed", True):
            raise IndexUnavailable(
                "INDEX_VERIFY_FAILED",
                f"staged index failed verification: {report.get('problems')}",
            )
        final = index_root / version
        if final.exists():
            # Identical content by construction; keep the immutable original.
            shutil.rmtree(staging, ignore_errors=True)
            return final, report
        os.replace(staging, final)
        return final, report
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def read_manifest(version_dir: Path) -> dict[str, Any]:
    manifest_path = version_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        db_path = version_dir / INDEX_DB_NAME
        if not db_path.is_file():
            raise IndexUnavailable("INDEX_MISSING", f"no index at {version_dir}")
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()
        finally:
            connection.close()
        if not row:
            raise IndexUnavailable("INDEX_MISSING", f"index has no manifest: {version_dir}")
        return json.loads(row[0])
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- pointer


def read_pointer(index_root: Path) -> str | None:
    pointer = index_root / POINTER_NAME
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = payload.get("index_version")
    return str(version) if version else None


def publish(index_root: Path, version: str) -> None:
    """Atomically point ``current`` at ``version``.

    Written to a temporary file first and then moved into place, so a crash
    during publish cannot leave a half-written pointer behind.
    """
    index_root.mkdir(parents=True, exist_ok=True)
    previous = read_pointer(index_root)
    if previous and previous != version:
        _retire_previous(index_root, previous)
    temp = index_root / f"{POINTER_NAME}.tmp"
    temp.write_text(
        json.dumps({"index_version": version}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temp, index_root / POINTER_NAME)


def _retire_previous(index_root: Path, version: str) -> None:
    """Keep the version we just left, as ``<version>.prev``, for rollback.

    On Windows a live reader can hold the file, so a failure here removes
    nothing and is never fatal: the old directory simply stays where it is.
    """
    source = index_root / version
    if not source.is_dir():
        return
    target = index_root / f"{version}.prev"
    try:
        if target.exists():
            return  # Immutable versions need no destructive backup replacement.
        shutil.copytree(source, target)
    except OSError:
        return


def list_versions(index_root: Path) -> list[str]:
    if not index_root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in index_root.iterdir()
        if entry.is_dir() and (entry / INDEX_DB_NAME).is_file()
    )


# ----------------------------------------------------------------------- load


@dataclass
class LoadedIndex:
    """A read-only handle on one published index version."""

    index_root: Path
    version: str
    manifest: dict[str, Any]
    db_path: Path
    _connection: sqlite3.Connection | None = field(default=None, repr=False)

    @property
    def doc_hashes(self) -> dict[str, str]:
        return dict(self.manifest.get("doc_hashes") or {})

    @property
    def snapshot_hash(self) -> str:
        return str(self.manifest.get("projection_snapshot_hash") or "")

    @property
    def embedding_contract(self) -> dict[str, Any] | None:
        contract = self.manifest.get("embedding")
        return dict(contract) if contract else None

    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            self._connection = connection
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    # ------------------------------------------------------------- components

    def doc(self, doc_id: str) -> dict[str, Any] | None:
        row = self.connection().execute(
            "SELECT * FROM docs WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None

    def docs_by_target(self, kind: str, target_id: str) -> list[dict[str, Any]]:
        rows = self.connection().execute(
            "SELECT * FROM docs WHERE kind = ? AND target_id = ?", (kind, str(target_id))
        ).fetchall()
        return [dict(row) for row in rows]

    def has_vectors(self) -> bool:
        if not self.embedding_contract:
            return False
        row = self.connection().execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
        return bool(row and row["n"] == self.manifest.get("counts", {}).get("docs"))

    def dictionary(self) -> dict[str, Any] | None:
        """The tokenizer dictionary frozen with this index.

        Rebuilding it from the fixture at request time would let the vocabulary
        drift away from the documents it is supposed to segment.
        """
        row = self.connection().execute(
            "SELECT value FROM meta WHERE key='dictionary'"
        ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["value"])
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        # JSON object keys are strings; the tokenizer indexes by length.
        payload["by_length"] = {
            int(length): list(terms) for length, terms in (payload.get("by_length") or {}).items()
        }
        payload["single_chars"] = set(payload.get("single_chars") or [])
        return payload

    def ingredient_maps(self) -> dict[str, dict[str, str]]:
        """The dictionary the index was built with, not the fixture on disk."""
        row = self.connection().execute(
            "SELECT value FROM meta WHERE key='ingredient_maps'"
        ).fetchone()
        if not row:
            return {"names": {}, "aliases": {}}
        try:
            payload = json.loads(row["value"])
        except (TypeError, ValueError):
            return {"names": {}, "aliases": {}}
        return {
            "names": dict(payload.get("names") or {}),
            "aliases": dict(payload.get("aliases") or {}),
        }

    def vector_for(self, doc_id: str) -> list[float] | None:
        row = self.connection().execute(
            "SELECT dimension, contract_key, vector FROM embeddings WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return None
        contract = self.embedding_contract or {}
        if row["dimension"] != contract.get("dimension"):
            # A row from another model is not a comparable vector.
            raise ValueError("stored vector dimension does not match the manifest contract")
        if row["contract_key"] != embedding_contract_key(contract):
            raise ValueError("stored vector was produced under a different embedding contract")
        return unpack_vector(row["vector"])

    # ----------------------------------------------------------------- search

    def lexical_search(
        self,
        query: str,
        dictionary: dict[str, Any],
        *,
        limit: int,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """BM25 over the pre-tokenized column.

        ``allowed_ids`` restricts the search **inside** the query, before the
        ranking is truncated. Ranking the whole index first and filtering
        afterwards would let documents of another kind (or ones a hard filter
        already excluded) consume the top-N slots and push real matches out of
        the result entirely.

        An empty token stream is an empty result, not an error and not a
        whole-corpus scan.
        """
        tokens = query_terms(query, dictionary)
        if not tokens:
            return []
        if allowed_ids is not None and not allowed_ids:
            return []
        expression = " OR ".join(f'"{token}"' for token in dict.fromkeys(tokens))
        sql = (
            "SELECT docs_fts.doc_id AS doc_id, bm25(docs_fts) AS score "
            "FROM docs_fts JOIN docs ON docs.doc_id = docs_fts.doc_id "
            "WHERE docs_fts MATCH ?"
        )
        params: list[Any] = [expression]
        if allowed_ids is not None:
            ordered = sorted(allowed_ids)
            sql += f" AND docs.doc_id IN ({','.join('?' * len(ordered))})"
            params.extend(ordered)
        sql += " ORDER BY score LIMIT ?"
        params.append(int(limit))
        try:
            rows = self.connection().execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            # A missing or corrupt FTS table is a broken index, not an empty
            # corpus. Reporting it as "no results" would be a silent lie.
            raise IndexUnavailable("INDEX_BROKEN", f"lexical index is not usable: {exc}") from None
        # bm25() is "smaller is better"; flip the sign so every route in this
        # module ranks higher-is-better and RRF never has to special-case one.
        return [(str(row["doc_id"]), -float(row["score"])) for row in rows]

    def vector_search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Exact cosine over the stored float32 vectors.

        Same restriction rule as the lexical route: the candidate set is applied
        *inside* the scan, so a filtered-out document cannot occupy a top-N slot.
        Every stored row is checked against the manifest contract before it is
        scored — a row from another contract is a broken index, and a broken
        index must fail loudly rather than quietly rank wrong.
        """
        contract = self.embedding_contract or {}
        dimension = contract.get("dimension")
        if dimension is None:
            raise IndexUnavailable("INDEX_STALE", "index has vectors but no dimension contract")
        validate_vector(query_vector, dimension=int(dimension))
        expected_key = embedding_contract_key(contract)
        sql = "SELECT doc_id, dimension, contract_key, vector FROM embeddings"
        params: list[Any] = []
        if allowed_ids is not None:
            if not allowed_ids:
                return []
            ordered = sorted(allowed_ids)
            sql += f" WHERE doc_id IN ({','.join('?' * len(ordered))})"
            params.extend(ordered)
        scored: list[tuple[str, float]] = []
        for row in self.connection().execute(sql, params).fetchall():
            if row["dimension"] != dimension or row["contract_key"] != expected_key:
                raise IndexUnavailable(
                    "INDEX_STALE",
                    f"stored vector for {row['doc_id']} was produced under a different contract",
                )
            vector = unpack_vector(row["vector"])
            if len(vector) != len(query_vector):
                raise IndexUnavailable(
                    "INDEX_STALE", f"stored vector for {row['doc_id']} has the wrong dimension"
                )
            validate_vector(vector, dimension=int(dimension))
            scored.append((str(row["doc_id"]), cosine(query_vector, vector)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: int(limit)]


def load_index(index_root: Path, *, version: str | None = None) -> LoadedIndex:
    """Load the published index, or raise :class:`IndexUnavailable`.

    Contract incompatibility is *not* a degradation case: an index built for a
    different projection/text template must be reported as stale rather than
    quietly answered from.
    """
    root = Path(index_root)
    resolved = version or read_pointer(root)
    if not resolved:
        raise IndexUnavailable("INDEX_MISSING", f"no current index under {root}")
    version_dir = root / resolved
    try:
        manifest = read_manifest(version_dir)
    except IndexUnavailable:
        raise
    if manifest.get("manifest_id") and manifest["manifest_id"] != "sha256:" + _manifest_id(manifest):
        # The manifest is self-describing: a hand-edited manifest cannot be
        # used to make an incompatible index look compatible.
        raise IndexUnavailable("INDEX_STALE", f"index {resolved} manifest failed its own integrity check")
    if not manifest.get("manifest_id"):
        raise IndexUnavailable("INDEX_STALE", "manifest identity is missing")
    if int(manifest.get("index_schema_version") or 0) != INDEX_SCHEMA_VERSION:
        raise IndexUnavailable(
            "INDEX_STALE",
            f"index {resolved} has schema version {manifest.get('index_schema_version')}, "
            f"expected {INDEX_SCHEMA_VERSION}",
        )
    if int(manifest.get("projection_snapshot", {}).get("schema_version") or 0) != SCHEMA_VERSION:
        raise IndexUnavailable("INDEX_STALE", f"index {resolved} was built from a different projection schema")
    if manifest.get("lexical_tokenizer_version") != LEXICAL_TOKENIZER_VERSION:
        raise IndexUnavailable("INDEX_STALE", f"index {resolved} used a different tokenizer")
    if manifest.get("text_template_version") != TEXT_TEMPLATE_VERSION:
        raise IndexUnavailable("INDEX_STALE", f"index {resolved} used a different text template")
    index = LoadedIndex(
        index_root=root,
        version=resolved,
        manifest=manifest,
        db_path=version_dir / INDEX_DB_NAME,
    )
    try:
        _verify_stored_content(index)
    except Exception:
        index.close()
        raise
    return index


def _verify_stored_content(index: LoadedIndex) -> None:
    """Recompute the content hashes from what is stored, not from the manifest.

    A manifest that merely *declares* ``zh-dict-v1`` proves nothing. The
    dictionary actually on disk and the document text actually indexed are
    hashed and compared, so a swapped dictionary or a hand-edited index is
    reported as stale instead of silently changing what the tokenizer matches.
    """
    expected = dict(index.manifest.get("content_hashes") or {})
    if not expected:
        raise IndexUnavailable("INDEX_STALE", "index content contract is missing; rebuild required")
    try:
        if expected.get("ingredient_maps_hash") != _sha256_of(json.dumps(index.ingredient_maps(), ensure_ascii=False, sort_keys=True)):
            raise IndexUnavailable("INDEX_STALE", "frozen ingredient maps changed; rebuild required")
        from app.services.retrieval_projection import ProjectionDoc
        records = index.connection().execute("SELECT * FROM docs ORDER BY doc_id").fetchall()
        if len(records) != index.manifest.get("counts", {}).get("docs"):
            raise IndexUnavailable("INDEX_STALE", "document count differs from manifest")
        for row in records:
            projected = ProjectionDoc(doc_id=row["doc_id"], kind=row["kind"], target_id=row["target_id"],
                                      name=row["name"], text=row["text"], payload=json.loads(row["payload_json"]))
            if projected.static_hash != index.doc_hashes.get(row["doc_id"]):
                raise IndexUnavailable("INDEX_STALE", "stored document evidence differs from manifest")
        stored_dictionary = index.dictionary() or {}
        actual_dictionary = _sha256_of(
            json.dumps(
                _serializable_dictionary(stored_dictionary), ensure_ascii=False, sort_keys=True
            )
        )
        if actual_dictionary != expected.get("dictionary_hash"):
            raise IndexUnavailable("INDEX_STALE", f"index {index.version} dictionary hash mismatch")
        rows = index.connection().execute(
            "SELECT doc_id, text FROM docs ORDER BY doc_id"
        ).fetchall()
        actual_text = _sha256_of(
            json.dumps(
                {
                    "template": index.manifest.get("text_template_version"),
                    "docs": [[row["doc_id"], row["text"]] for row in rows],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if actual_text != expected.get("text_template_hash"):
            raise IndexUnavailable(
                "INDEX_STALE", f"index {index.version} indexed text hash mismatch"
            )
    except IndexUnavailable:
        raise
    except sqlite3.Error as exc:
        raise IndexUnavailable("INDEX_BROKEN", f"index {index.version} is unreadable: {exc}") from None


__all__ = [
    "EMBEDDING_CONTRACT_KEYS",
    "INDEX_DB_NAME",
    "INDEX_SCHEMA_VERSION",
    "IndexUnavailable",
    "LoadedIndex",
    "build_manifest",
    "cosine",
    "embedding_contract_key",
    "index_version_for",
    "list_versions",
    "load_index",
    "normalize_vector",
    "pack_vector",
    "publish",
    "read_manifest",
    "stage_and_commit",
    "read_pointer",
    "unpack_vector",
    "validate_vector",
    "write_index",
]
