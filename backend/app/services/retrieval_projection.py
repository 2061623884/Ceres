"""Static retrieval projection: one dish document, one SKU document.

The projection is the *only* thing the index is built from. It is deliberately
narrow:

* It is read from a named snapshot (the S1 candidate runtime database) plus the
  frozen canonical ingredient dictionary, and from nothing else. Nothing here
  falls back to ``data/runtime/sale_guide.sqlite3`` or re-reads a newer fixture.
* Dishes and SKUs stay two separate collections. A dish and a product are not
  comparable units, so they are never scored with one ruler.
* Prices, stock and delivery are **not** part of it and are never embedded. They
  are read live from SQL at request time by the existing business services.
* Unknown attributes (cook minutes, taste, nutrition) are never invented to pad
  the retrieval text. A missing field stays missing.

Every document carries its own static hash so the index can drop a stale row or
top up a short result list without re-hashing the whole corpus.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.ingredient_catalog import load_ingredient_catalog

#: Bumped when the shape of a projected document changes.
SCHEMA_VERSION = 1
#: Bumped when the text that is embedded or tokenized changes. Changing it
#: invalidates the embedding contract and forces an offline rebuild.
TEXT_TEMPLATE_VERSION = "v1"
#: Bumped when the Chinese dictionary segmentation changes. A purely lexical
#: change only invalidates the lexical index.
LEXICAL_TOKENIZER_VERSION = "zh-dict-v1"

DISH_SOURCE = "chinese-dishes-v1"
DOC_DISH = "dish"
DOC_SKU = "sku"

#: How many characters of a document may be embedded. Documents are structured
#: and short; this is a guard rail, not a chunking strategy — nothing is split.
MAX_DOC_CHARS = 400


def _sha256(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ProjectionDoc:
    """One retrievable document. ``payload`` is static, verified metadata only."""

    doc_id: str
    kind: str
    target_id: str
    name: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def static_hash(self) -> str:
        return _sha256(
            _canonical(
                {
                    "kind": self.kind,
                    "target_id": self.target_id,
                    "name": self.name,
                    "text": self.text,
                    "payload": self.payload,
                    "text_template_version": TEXT_TEMPLATE_VERSION,
                }
            )
        )


@dataclass(frozen=True)
class Projection:
    """The frozen static retrieval projection of exactly one snapshot."""

    docs: list[ProjectionDoc]
    snapshot: dict[str, Any]
    doc_hashes: dict[str, str]

    #: Fields of ``snapshot`` that describe *where the build read from*, not what
    #: it read. A label or a path is a note for a human; it must never change the
    #: identity of the projection, or the same corpus built twice would look like
    #: two different corpora and force a pointless re-embedding.
    AUDIT_ONLY_SNAPSHOT_FIELDS = ("snapshot_label", "candidate_db_path")

    @property
    def content_snapshot(self) -> dict[str, Any]:
        """The part of the snapshot that actually identifies the corpus."""
        return {
            key: value
            for key, value in self.snapshot.items()
            if key not in self.AUDIT_ONLY_SNAPSHOT_FIELDS
        }

    @property
    def snapshot_hash(self) -> str:
        """Hash of the canonical static projection only.

        Not of the runtime database: sessions, stock and prices change on every
        request and must never invalidate the index. Not of the build's own
        label or source path either — those are audit notes.
        """
        return _sha256(
            _canonical({"snapshot": self.content_snapshot, "doc_hashes": self.doc_hashes})
        )

    def of_kind(self, kind: str) -> list[ProjectionDoc]:
        return [doc for doc in self.docs if doc.kind == kind]


# ----------------------------------------------------------------------- dictionary


def _load_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _load_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def build_dictionary(
    *,
    dish_rows: Iterable[dict[str, Any]],
    sku_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """The frozen Chinese dictionary the tokenizer segments with.

    Sources, in order: canonical ingredient names/aliases/``ner_terms``, dish
    names and registered aliases, SKU usage tags and product names. It is built
    from the same snapshot as the documents, so it can never drift into a newer
    fixture behind the index's back.
    """
    terms: set[str] = set()
    catalog = load_ingredient_catalog()
    for item in catalog["ingredients"].values():
        for key in ("name_zh", "name", "ingredient_id"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                terms.add(value.strip())
        for key in ("aliases", "ner_terms"):
            for value in item.get(key) or []:
                if isinstance(value, str) and value.strip():
                    terms.add(value.strip())
    for row in dish_rows:
        # The template table calls it ``scenario``; the projected document calls it
        # ``name``. Reading only one of them silently drops every dish name from
        # the dictionary.
        aliases = row.get("aliases")
        if aliases is None:
            aliases = _load_json_list(row.get("aliases_json"))
        for value in [row.get("name") or row.get("scenario"), *(aliases or [])]:
            if isinstance(value, str) and value.strip():
                terms.add(value.strip())
    for row in sku_rows:
        for value in [row.get("name_zh"), row.get("name"), row.get("brand")]:
            if isinstance(value, str) and value.strip():
                terms.add(value.strip())
        for tag in _load_json_list(row.get("usage_tags")):
            if isinstance(tag, str) and tag.strip():
                terms.add(tag.strip())

    by_length: dict[int, list[str]] = {}
    for term in terms:
        normalized = term.strip().lower()
        if not normalized:
            continue
        by_length.setdefault(len(normalized), []).append(normalized)
    for bucket in by_length.values():
        bucket.sort(key=len, reverse=True)
    #: A single Chinese character is a real query ("蛋", "鱼") but is not itself a
    #: registered term. It is expanded into the registered terms that *contain*
    #: it, and only into those: the expansion is bounded by the frozen canonical
    #: dictionary, so it is a dictionary lookup rather than "match any text with
    #: this character in it".
    single_char_expansions: dict[str, list[str]] = {}
    canonical_chars: set[str] = set()
    for item in catalog["ingredients"].values():
        for key in ("name_zh", "aliases", "ner_terms"):
            raw = item.get(key)
            for value in [raw] if isinstance(raw, str) else (raw or []):
                if isinstance(value, str):
                    canonical_chars.update(ch for ch in value.strip().lower() if _is_cjk(ch))
    for char in canonical_chars:
        expanded = sorted(term for term in terms if char in term.strip().lower())
        if expanded:
            single_char_expansions[char] = expanded
    return {
        "version": LEXICAL_TOKENIZER_VERSION,
        "terms": sorted(terms),
        "by_length": by_length,
        "single_char_expansions": single_char_expansions,
        #: Single-character tokens are *controlled*: only a character the frozen
        #: dictionary actually registered may be used as a token. Otherwise a
        #: one-character query would match most of the corpus.
        "single_chars": {t for t in by_length.get(1, [])},
    }


def tokenize(text: str | None, dictionary: dict[str, Any]) -> list[str]:
    """Longest-match segmentation against the frozen dictionary.

    CJK runs are segmented by dictionary lookup, longest term first; an
    unregistered CJK run falls back to character bigrams (never single
    characters) so an unseen word still produces *some* lexical signal without
    letting one character match everything. Latin/digit runs are kept whole.
    """
    if not text:
        return []
    lowered = text.lower()
    by_length: dict[int, list[str]] = dictionary["by_length"]
    max_len = max(by_length) if by_length else 1
    single_chars: set[str] = dictionary["single_chars"]
    tokens: list[str] = []
    index = 0
    length = len(lowered)
    while index < length:
        char = lowered[index]
        if not char.isalnum():
            index += 1
            continue
        if not _is_cjk(char):
            end = index
            while end < length and lowered[end].isalnum() and not _is_cjk(lowered[end]):
                end += 1
            tokens.append(lowered[index:end])
            index = end
            continue
        matched = None
        for size in range(min(max_len, length - index), 0, -1):
            candidate = lowered[index : index + size]
            if candidate in by_length.get(size, []) or candidate in _term_set(dictionary):
                matched = candidate
                break
        if matched is None:
            # Unseen CJK run: bigrams only, and only while they stay in-run.
            if index + 2 <= length and _is_cjk(lowered[index + 1]):
                tokens.append(lowered[index : index + 2])
                index += 2
            else:
                index += 1
            continue
        if len(matched) == 1 and matched not in single_chars:
            # A controlled single character the dictionary never registered is
            # not a token at all.
            index += 1
            continue
        tokens.append(matched)
        index += len(matched)
    return tokens


_TERM_CACHE: dict[int, set[str]] = {}


def _term_set(dictionary: dict[str, Any]) -> set[str]:
    key = id(dictionary)
    cached = _TERM_CACHE.get(key)
    if cached is None:
        cached = set(dictionary.get("terms") or [])
        _TERM_CACHE[key] = cached
    return cached


def _is_cjk(char: str) -> bool:
    return "㐀" <= char <= "鿿" or "豈" <= char <= "﫿"


def tokenized_text(text: str, dictionary: dict[str, Any]) -> str:
    """The space-joined token stream stored in the FTS5 column."""
    return " ".join(tokenize(text, dictionary))


def query_terms(query: str, dictionary: dict[str, Any]) -> list[str]:
    """Tokens for a **query**, with the controlled single-character expansion.

    Documents are tokenized strictly: a one-character term only appears if the
    dictionary registered it. A *query* made of one such character ("蛋") is a
    real thing a shopper types, so it is expanded into the registered terms that
    contain it. Nothing outside the frozen dictionary can be reached this way,
    and the expansion only applies to a query that is that single character —
    a multi-token query keeps the strict rule.
    """
    tokens = tokenize(query, dictionary)
    if tokens:
        return tokens
    stripped = query.strip().lower()
    if len(stripped) == 1 and _is_cjk(stripped):
        return list((dictionary.get("single_char_expansions") or {}).get(stripped) or [])
    return []


# ------------------------------------------------------------------- projection


def _ingredient_names(
    ingredient_ids: Iterable[str], frozen: dict[str, str] | None = None
) -> list[str]:
    """Canonical Chinese names for ingredient ids.

    ``frozen`` is the name map captured in the index. The live request path
    passes it so that re-projecting a row for a staleness check never re-reads
    the mutable fixture — the same map the build used is the only one that
    produces a comparable hash.
    """
    if frozen is not None:
        return list(
            dict.fromkeys(
                frozen[str(i)] for i in ingredient_ids if i and str(i) in frozen
            )
        )
    catalog = load_ingredient_catalog()
    names: list[str] = []
    for ingredient_id in ingredient_ids:
        if not ingredient_id:
            continue
        item = catalog["ingredients"].get(ingredient_id)
        if item and item.get("name_zh"):
            names.append(str(item["name_zh"]))
            continue
        canonical = catalog["alias_to_id"].get(ingredient_id)
        if canonical and catalog["ingredients"].get(canonical, {}).get("name_zh"):
            names.append(str(catalog["ingredients"][canonical]["name_zh"]))
    return list(dict.fromkeys(names))


def project_dish_row(
    row: dict[str, Any], frozen_names: dict[str, str] | None = None
) -> ProjectionDoc:
    """Project one ``purchase_templates`` row into a dish document.

    Public because the request path re-projects a live row with *this* function
    to check whether the stored document is still current; a second
    implementation would produce hashes that never match.
    """
    dish_id = str(row["template_id"])
    name = str(row.get("scenario") or "").strip()
    aliases = [str(a).strip() for a in _load_json_list(row.get("aliases_json")) if str(a).strip()]
    required = _load_json_dict_list(row.get("required_items"))
    optional = _load_json_dict_list(row.get("optional_items"))
    main_ids = [str(i.get("ingredient_id")) for i in required if i.get("ingredient_id")]
    optional_ids = [str(i.get("ingredient_id")) for i in optional if i.get("ingredient_id")]
    metadata = _load_json_dict(row.get("metadata_json"))
    review = metadata.get("review") or {}
    review_status = str(review.get("status") or "unreviewed")
    review_basis = _review_basis(review, metadata.get("meta_provenance") or {})

    # Only verified naming and main-ingredient signals. Taste, cook time and
    # nutrition are absent from the data, so they are absent from the text.
    text = " ".join(
        part
        for part in [
            name,
            *aliases,
            *_ingredient_names(main_ids, frozen_names),
            *_ingredient_names(optional_ids, frozen_names),
        ]
        if part
    )[:MAX_DOC_CHARS]
    return ProjectionDoc(
        doc_id=f"{DOC_DISH}:{dish_id}",
        kind=DOC_DISH,
        target_id=dish_id,
        name=name,
        text=text,
        payload={
            "aliases": aliases,
            "required_ingredient_ids": main_ids,
            "optional_ingredient_ids": optional_ids,
            "all_ingredient_ids": list(dict.fromkeys(main_ids + optional_ids)),
            "pantry_items": [str(p) for p in _load_json_list(row.get("pantry_items")) if isinstance(p, str)],
            "base_people": row.get("base_people") or 2,
            "review_status": review_status,
            "review_basis": review_basis,
        },
    )


def _review_basis(review: dict[str, Any], provenance: dict[str, Any]) -> str:
    """Evidence strength, never fabricated.

    An unreviewed row is reported as unreviewed. Nothing here promotes a machine
    generated value to a human review.
    """
    if str(review.get("status") or "") == "approved" and review.get("reviewer"):
        return "manual_review"
    for value in provenance.values():
        if value == "manual_review":
            return "manual_review"
    return "unreviewed"


def _load_json_dict_list(raw: Any) -> list[dict[str, Any]]:
    return [entry for entry in _load_json_list(raw) if isinstance(entry, dict)]


SKU_TEXT_RELATIONS = ("declared", "reviewed")


def project_sku_row(
    row: dict[str, Any], frozen_names: dict[str, str] | None = None
) -> ProjectionDoc:
    """Project one ``catalog_products`` row into a SKU document. See above."""
    sku_id = str(row["sku_id"])
    metadata = _load_json_dict(row.get("metadata_json"))
    mappings = [
        entry for entry in (metadata.get("ingredient_mapping") or []) if isinstance(entry, dict)
    ]
    declared_ids = [str(i) for i in _load_json_list(row.get("ingredient_ids")) if i]
    mapped_ids = [
        str(m.get("ingredient_id"))
        for m in mappings
        if m.get("ingredient_id") and m.get("relation") in SKU_TEXT_RELATIONS
    ]
    # ``inferred`` mappings are recorded but never used as retrieval text: an
    # inferred cross-identity mapping must not make a product recallable as an
    # ingredient it has not been shown to be. See the audit's forbidden pairs.
    inferred_ids = [
        str(m.get("ingredient_id"))
        for m in mappings
        if m.get("ingredient_id") and m.get("relation") not in SKU_TEXT_RELATIONS
    ]
    usage_tags = [str(t).strip() for t in _load_json_list(row.get("usage_tags")) if str(t).strip()]
    name = str(row.get("name") or "").strip()
    name_zh = str(row.get("name_zh") or "").strip()
    brand = str(row.get("brand") or "").strip()
    image_status = metadata.get("image_status") or {}
    allergens = metadata.get("allergens") or {}

    text = " ".join(
        part
        for part in [
            name_zh,
            name,
            brand,
            *usage_tags,
            *_ingredient_names(list(dict.fromkeys(declared_ids + mapped_ids)), frozen_names),
        ]
        if part
    )[:MAX_DOC_CHARS]
    return ProjectionDoc(
        doc_id=f"{DOC_SKU}:{sku_id}",
        kind=DOC_SKU,
        target_id=sku_id,
        name=name_zh or name,
        text=text,
        payload={
            "declared_ingredient_ids": declared_ids,
            "verified_mapping_relations": [
                str(m.get("ingredient_id")) for m in mappings
                if m.get("relation") in ("declared", "reviewed") and m.get("ingredient_id")
            ],
            "inferred_ingredient_ids": inferred_ids,
            "usage_tags": usage_tags,
            "spec_quantity": row.get("spec_quantity"),
            "spec_unit": row.get("spec_unit"),
            "product_type": row.get("product_type"),
            "category_id": row.get("category_id"),
            "source": row.get("source"),
            "review_status": row.get("review_status") or "approved",
            #: Unknown stays unknown. A missing allergen block is not "no
            #: allergens", and the retrieval layer never claims otherwise.
            "allergens_status": str(allergens.get("status") or "unknown"),
            "image_kind": str(image_status.get("kind") or "unknown"),
            "image_semantic_match": str(image_status.get("semantic_match") or "unknown"),
        },
    )


def read_snapshot(db_path: str | Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the two projected tables from the snapshot database, read-only.

    ``mode=ro`` is not decoration: the index build must be provably incapable of
    writing to the snapshot it was handed.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        # One explicit read transaction across both tables. Without it the two
        # SELECTs can straddle a writer and produce a projection that never
        # existed as a consistent state of the snapshot.
        connection.execute("BEGIN")
        dish_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT template_id, scenario, aliases_json, base_people, required_items, "
                "optional_items, pantry_items, metadata_json FROM purchase_templates "
                "WHERE source = ? ORDER BY template_id",
                (DISH_SOURCE,),
            )
        ]
        sku_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT sku_id, name, name_zh, brand, category_id, ingredient_ids, usage_tags, "
                "product_type, spec_quantity, spec_unit, source, review_status, metadata_json "
                "FROM catalog_products WHERE review_status = 'approved' ORDER BY sku_id"
            )
        ]
        connection.execute("COMMIT")
    finally:
        connection.close()
    return dish_rows, sku_rows


def build_projection(
    db_path: str | Any,
    *,
    snapshot_label: str = "",
) -> tuple[Projection, dict[str, Any]]:
    """Build the projection plus the dictionary it was tokenized against."""
    dish_rows, sku_rows = read_snapshot(db_path)
    dictionary = build_dictionary(dish_rows=dish_rows, sku_rows=sku_rows)
    docs = [project_dish_row(row) for row in dish_rows] + [project_sku_row(row) for row in sku_rows]
    catalog = load_ingredient_catalog()
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "text_template_version": TEXT_TEMPLATE_VERSION,
        "lexical_tokenizer_version": LEXICAL_TOKENIZER_VERSION,
        "ingredient_catalog_version": str(catalog.get("version") or "unknown"),
        "dish_source": DISH_SOURCE,
        "dish_count": len(dish_rows),
        "sku_count": len(sku_rows),
        "canonical_ingredient_count": len(catalog["ingredients"]),
        "snapshot_label": snapshot_label,
    }
    projection = Projection(
        docs=docs,
        snapshot=snapshot,
        doc_hashes={doc.doc_id: doc.static_hash for doc in docs},
    )
    return projection, dictionary


__all__ = [
    "DOC_DISH",
    "DOC_SKU",
    "LEXICAL_TOKENIZER_VERSION",
    "MAX_DOC_CHARS",
    "Projection",
    "ProjectionDoc",
    "SCHEMA_VERSION",
    "TEXT_TEMPLATE_VERSION",
    "build_dictionary",
    "build_projection",
    "read_snapshot",
    "tokenize",
    "tokenized_text",
]
