"""
search_recipes.py — Self-contained hybrid search tool for the recipe search agent.

Combines BM25 + dense kNN with RRF fusion. Routing is determined by how many
dictionary fields the BM25 query hits — no LLM category is involved.

Public API:
    search_recipes(os_client, query, dense_query, tag)
        -> tuple[list[dict], bool]
        Returns ALL ranked recipes (no top-K cap) with metadata + search_text.

        query        — keyword-focused string for BM25 (filler stripped)
        dense_query  — semantic-rich string for kNN (always required; ignored
                       in the 2+ filter case where dense is skipped)
        tag          — optional connector tag filter (snake_case), e.g. "salesforce"

        tag_matched is False when a tag was requested but no documents carried it.

Filter-count routing (based on `_extract_keyword_filters(query)`):
    2+ field filters → BM25 only (dense skipped, embedding call saved)
    1 field filter   → BM25 + dense (no dense floor, all hits) + RRF
    0 filters        → multi-field BM25 (floor 1.5) + dense (floor 0.80) + RRF
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from nltk.stem import PorterStemmer
from opensearchpy import OpenSearch

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INDEX_NAME = "bt_recipe"

BASETEN_EMBED_URL = "https://model-qrjgv4v3.api.baseten.co/environments/production/predict"
BASETEN_KEY       = os.environ["BASETEN_API_KEY"]
EMBED_DIMS = 4096

RRF_K                = 60
DENSE_SCORE_FLOOR    = 0.80    # applied in the 0-filter case only
BM25_SCORE_FLOOR     = 1.5     # applied in the 0-filter case only (no dict anchor → prose noise)
BM25_MAX_HITS        = 10000   # OpenSearch default index.max_result_window
KNN_MAX_HITS         = 10000   # also bounded by index.max_result_window
TOP_HYDRATE_N        = 20      # top-N hits get full hydration (description + connectors); rest get id only

# ---------------------------------------------------------------------------
# Dictionary-based query rewriting
# ---------------------------------------------------------------------------

_DICT_PATH = Path(
    os.environ.get(
        "RECIPE_DICTIONARIES_PATH",
        Path(__file__).parent.parent / "01_process_data" / "cleaned" / "dictionaries_full.json",
    )
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


_STEMMER = PorterStemmer()


def _stem(token: str) -> str:
    return _STEMMER.stem(token.lower())


def _build_stem_map(entries: list[str]) -> dict[str, list[str]]:
    """Map each Porter stem to the list of original entries that share that stem."""
    out: dict[str, list[str]] = {}
    for e in entries:
        out.setdefault(_stem(e), []).append(e)
    return out


def _load_dictionaries() -> tuple[dict, dict, dict]:
    with _DICT_PATH.open() as f:
        d = json.load(f)
    return (
        _build_stem_map(d.get("connectors", [])),
        _build_stem_map(d.get("actions", [])),
        _build_stem_map(d.get("fields", [])),
    )


CONNECTORS_STEMS, ACTIONS_STEMS, FIELDS_STEMS = _load_dictionaries()


def _tokenize_for_rewrite(query: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(query)]


def _stem_class_filter(field: str, originals: list[str]) -> dict:
    """OR-of-terms clause for a single stem class (singular/plural variants)."""
    originals = sorted({v.lower() for v in originals})
    if len(originals) == 1:
        return {"term": {field: originals[0]}}
    return {"terms": {field: originals}}


def _extract_keyword_filters(query: str) -> list[dict]:
    """
    For each unique stemmed query token, look up which dict bucket it hits
    (precedence: connectors > actions > fields). Each match expands to all
    original entries sharing that stem (singular/plural variants).

    Semantics:
      - within a single stem class: OR (any variant matches → terms query)
      - across distinct stems in the same field: AND (all stems must match)
      - across fields: AND
    """
    token_stems = {_stem(t) for t in _tokenize_for_rewrite(query)}

    by_field: dict[str, list[list[str]]] = {"connectors": [], "actions": [], "fields": []}
    for ts in token_stems:
        if ts in CONNECTORS_STEMS:
            by_field["connectors"].append(CONNECTORS_STEMS[ts])
        elif ts in ACTIONS_STEMS:
            by_field["actions"].append(ACTIONS_STEMS[ts])
        elif ts in FIELDS_STEMS:
            by_field["fields"].append(FIELDS_STEMS[ts])

    filters: list[dict] = []
    for field, stem_classes in by_field.items():
        if not stem_classes:
            continue
        clauses = [_stem_class_filter(field, originals) for originals in stem_classes]
        if len(clauses) == 1:
            filters.append(clauses[0])
        else:
            filters.append({"bool": {"filter": clauses}})
    return filters

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_query(text: str) -> list[float]:
    resp = requests.post(
        BASETEN_EMBED_URL,
        headers={"Authorization": f"Api-Key {BASETEN_KEY}"},
        json={"input": [text], "model": "model", "encoding_format": "float"},
        timeout=300,
    )
    resp.raise_for_status()
    vec = resp.json()["data"][0]["embedding"][:EMBED_DIMS]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec

# ---------------------------------------------------------------------------
# BM25 query builders
# ---------------------------------------------------------------------------

def _bm25_query(query: str, fields: list[str]) -> dict:
    return {
        "multi_match": {
            "query": query,
            "fields": fields,
            "type": "cross_fields",
            "operator": "or",
        }
    }


def _apply_filters(query_body: dict, tag: str | None,
                   keyword_filters: list[dict]) -> dict:
    filters: list[dict] = list(keyword_filters)
    if tag:
        filters.append({"match": {"tag": {"query": tag, "operator": "and"}}})
    if not filters:
        return query_body
    return {
        "bool": {
            "must":   query_body,
            "filter": filters,
        }
    }


def _tag_exists(client: OpenSearch, tag: str) -> bool:
    """Cheap preflight: does any document in the index carry this tag?"""
    resp = client.count(
        index=INDEX_NAME,
        body={"query": {"match": {"tag": {"query": tag, "operator": "and"}}}},
    )
    return resp["count"] > 0

# ---------------------------------------------------------------------------
# OpenSearch runners
# ---------------------------------------------------------------------------

def _run_bm25(client: OpenSearch, query_body: dict,
              tag: str | None, keyword_filters: list[dict]) -> list[dict]:
    return client.search(index=INDEX_NAME, body={
        "size": BM25_MAX_HITS, "_source": False,
        "query": _apply_filters(query_body, tag, keyword_filters),
    })["hits"]["hits"]


def _run_knn(client: OpenSearch, vector: list[float],
             tag: str | None, keyword_filters: list[dict],
             floor: float | None = None) -> list[dict]:
    knn_query: dict = {"knn": {"combined_qwen": {"vector": vector, "k": KNN_MAX_HITS}}}
    hits = client.search(index=INDEX_NAME, body={
        "size": KNN_MAX_HITS, "_source": False,
        "query": _apply_filters(knn_query, tag, keyword_filters),
    })["hits"]["hits"]
    if floor is not None:
        hits = [h for h in hits if h["_score"] >= floor]
    return hits


def _rrf_fusion(dense_hits: list[dict], fts_hits: list[dict]) -> list[tuple[str, float]]:
    dense_ranks = {h["_id"]: i + 1 for i, h in enumerate(dense_hits)}
    fts_ranks   = {h["_id"]: i + 1 for i, h in enumerate(fts_hits)}
    all_ids = set(dense_ranks) | set(fts_ranks)
    scored = [
        (doc_id,
         (1.0 / (RRF_K + dense_ranks[doc_id]) if doc_id in dense_ranks else 0.0)
         + (1.0 / (RRF_K + fts_ranks[doc_id]) if doc_id in fts_ranks else 0.0))
        for doc_id in all_ids
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _fetch_docs(client: OpenSearch, doc_ids: list[str]) -> dict[str, dict]:
    if not doc_ids:
        return {}
    mget = client.mget(
        index=INDEX_NAME, body={"ids": doc_ids},
        params={"_source_includes": "description,connectors"},
    )
    return {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_recipes(os_client: OpenSearch, query: str,
                   dense_query: str,
                   tag: str | None = None) -> tuple[list[dict], bool]:
    """
    Hybrid recipe search. Routing is determined by the dictionary filter count
    on `query` — no LLM category is involved.

    Filter-count routing:
        2+ field filters → BM25 only (no embedding call)
        1 field filter   → BM25 + dense (no dense floor) + RRF
        0 filters        → multi-field BM25 (floor 1.5) + dense (floor 0.80) + RRF

    Tag handling: preflight `_tag_exists` once at the top. If the tag exists,
    strict-filter both legs. If not, append the tag to `query` and `dense_query`,
    drop the strict filter, and re-extract keyword filters from the augmented
    query (so a dict-matching tag still narrows the pool).

    Returns (results, tag_matched) — tag_matched is False when a tag was
    requested but no documents carried that tag (results are a fallback).
    """
    tag_matched = True
    if tag and not _tag_exists(os_client, tag):
        query = f"{query} {tag}"
        dense_query = f"{dense_query} {tag}"
        tag = None
        tag_matched = False

    keyword_filters = _extract_keyword_filters(query)
    n_filter_fields = len(keyword_filters)

    # ---- 2+ field filters: BM25 only ----
    if n_filter_fields >= 2:
        q_body = _bm25_query(query, ["search_text"])
        hits = _run_bm25(os_client, q_body, tag, keyword_filters)
        doc_map = _fetch_docs(os_client, [h["_id"] for h in hits[:TOP_HYDRATE_N]])
        return [
            {"recipe_uid": h["_id"], "score": h["_score"], "score_type": "bm25",
             **doc_map.get(h["_id"], {})}
            for h in hits
        ], tag_matched

    # ---- 1 filter or 0 filters: hybrid RRF ----
    if n_filter_fields == 1:
        bm25_fields = ["search_text"]
        bm25_floor  = None
        dense_floor = None        # let RRF mix all dense hits with BM25
    else:
        bm25_fields = ["search_text", "description", "usage"]
        bm25_floor  = BM25_SCORE_FLOOR
        dense_floor = DENSE_SCORE_FLOOR

    q_body = _bm25_query(query, bm25_fields)
    vector = embed_query(dense_query)
    fts_hits = _run_bm25(os_client, q_body, tag, keyword_filters)
    if bm25_floor is not None:
        fts_hits = [h for h in fts_hits if h["_score"] >= bm25_floor]
    dense_hits = _run_knn(os_client, vector, tag, keyword_filters, floor=dense_floor)
    top = _rrf_fusion(dense_hits, fts_hits)

    doc_map = _fetch_docs(os_client, [doc_id for doc_id, _ in top[:TOP_HYDRATE_N]])
    return [
        {"recipe_uid": doc_id, "score": score, "score_type": "rrf",
         **doc_map.get(doc_id, {})}
        for doc_id, score in top
    ], tag_matched
