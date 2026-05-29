"""
search.py — BM25 strategy experiment with fixed combined_qwen dense search.

BM25 strategies:
  search_text_only     — BM25 on search_text only
  description_usage    — BM25 on description + usage only
  cross_fields_all     — cross_fields: search_text + description + usage + connectors^2
  cross_fields_tech    — cross_fields: search_text + connectors^3
  routed               — structured query → search_text + connectors^3
                         natural query   → description + usage + connectors^2 + search_text

Dense: fixed combined_qwen for all strategies.
Fusion: weighted RRF (w_fts, w_dense per strategy).

Usage:
    python search.py
    python search.py --top-k 5 --verbose
    python search.py --strategy cross_fields_all
"""

from __future__ import annotations

import argparse
import math
import os
import re
import time
from pathlib import Path

import json

import requests
from dotenv import load_dotenv
from openai import OpenAI
from opensearchpy import OpenSearch

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
INDEX_NAME     = "bt_recipe"
BASETEN_URL    = "https://model-qrjgv4v3.api.baseten.co/environments/production/predict"
BASETEN_KEY    = os.environ["BASETEN_API_KEY"]
DIMS           = 4096
INSTRUCTION    = "Instruct: Retrieve the most relevant document for this search query.\nQuery: "

LLM_BASE_URL   = os.getenv("BASE_URL", "https://ai-gateway-int.awstf.workato.com/v1/")
LLM_API_KEY    = os.getenv("API_KEY", "")
LLM_MODEL      = "azure/gpt-4.1-mini"

TOP_K                = 10
CANDIDATE_MULTIPLIER = 3
RRF_K                = 60


def apply_tag_filter(query_body: dict, tag: str | None) -> dict:
    """Wrap a query body in a bool filter for the given tag, or return as-is."""
    if tag is None:
        return query_body
    return {
        "bool": {
            "must": query_body,
            "filter": {"term": {"tag": tag}},
        }
    }


_llm_client = None

def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    return _llm_client


_classify_cache: dict[str, tuple[str, str]] = {}

_CLASSIFY_SYSTEM = """\
You are a search query classifier for a recipe automation platform.

Classify the query into one of three categories, rewrite it as a compact \
keyword phrase for BM25 search (strip question framing and tag filter instructions, \
keep domain signal), and extract a tag if one is present.

Categories:
- technical: query mentions a specific field name (usually snake_case like sobject_name) \
or object identifier — focus on exact field/connector names
- mixed: query mentions connector/product names (Salesforce, NetSuite, Slack, etc.) \
together with a business action or process
- business_intent: pure business language, no technical terms or connector names

Tag: only extract a tag when the user explicitly requests filtering by tag, \
e.g. "with tag salesforce", "tagged as netsuite", "tag: jira". \
Use snake_case. Return null if the user does not explicitly mention a tag filter \
— merely mentioning a connector name in the query is NOT a tag. \
Do NOT include the tag or tag filter phrase in the rewritten query.

Respond with JSON only:
{"category": "<technical|mixed|business_intent>", "rewritten": "<keywords>", "tag": "<connector_name or null>"}
"""


def classify_and_rewrite(query: str) -> tuple[str, str, str | None]:
    """Return (category, rewritten_query, tag) using LLM. Results are cached."""
    if query in _classify_cache:
        return _classify_cache[query]
    client = _get_llm_client()
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": query},
        ],
    )
    result = json.loads(resp.choices[0].message.content)
    category = result.get("category", "mixed")
    rewritten = result.get("rewritten", query)
    tag = result.get("tag") or None
    _classify_cache[query] = (category, rewritten, tag)
    return category, rewritten, tag

QUERIES = [
    # technical
    "What recipes refer to field netsuite_object?",
    "If I update field netsuite_object, what recipes will be affected?",
    "What recipes refer to field search_settings of NetSuite?",
    "If I update field search_settings of NetSuite, what recipes will be affected?",
    "What recipes refer to field internal_id of NetSuite?",
    "If I update field internal_id of NetSuite, what recipes will be affected?",
    "What recipes refer to field sobject_name of Salesforce?",
    "If I update field sobject_name of SDFC, how many recipes will be affected?",
    "If I update field sobject_name of SDFC, what recipes will be affected?",
    "What recipes refer to field external_id of Salesforce?",
    "If I update field external_id of SDFC, how many recipes will be affected?",
    # mixed
    "What recipes synch between SDFC and Netsuite?",
    "Which recipes are involved in the Procure to Pay process?",
    "What recipes are involved in the Quote to Cash process?",
    "Which recipes post Slack alerts for high-priority incidents from ServiceNow?",
    "Please find recipes where Zendesk ticket webhook searches Salesforce contacts and posts to Slack.",
    "What recipes send notifications when a Salesforce lead is updated?",
    # business intent
    "Show me recipes that support customer support automation.",
    "Find all automations that are part of the financial close process.",
]

# ---------------------------------------------------------------------------
# BM25 strategies
# ---------------------------------------------------------------------------

_UNDERSCORE_RE = re.compile(r"\b\w+_\w+\b")


def _is_structured(query: str) -> bool:
    return bool(_UNDERSCORE_RE.search(query))


def bm25_query(strategy: str, query: str) -> dict:
    structured = _is_structured(query)

    if strategy == "search_text_only":
        return {
            "match": {"search_text": {"query": query, "operator": "or"}}
        }

    if strategy == "description_usage":
        return {
            "multi_match": {
                "query": query,
                "fields": ["description", "usage"],
                "type": "cross_fields",
                "operator": "or",
            }
        }

    if strategy == "cross_fields_all":
        return {
            "multi_match": {
                "query": query,
                "fields": ["search_text", "description", "usage", "connectors^2"],
                "type": "cross_fields",
                "operator": "or",
            }
        }

    if strategy == "cross_fields_tech":
        return {
            "multi_match": {
                "query": query,
                "fields": ["search_text", "connectors^3"],
                "type": "cross_fields",
                "operator": "or",
            }
        }

    if strategy == "routed":
        if structured:
            return {
                "multi_match": {
                    "query": query,
                    "fields": ["search_text", "connectors^3"],
                    "type": "cross_fields",
                    "operator": "or",
                }
            }
        else:
            return {
                "multi_match": {
                    "query": query,
                    "fields": ["description^2", "usage^2", "connectors^2", "search_text"],
                    "type": "cross_fields",
                    "operator": "or",
                }
            }

    if strategy == "best_fields":
        return {
            "multi_match": {
                "query": query,
                "fields": ["search_text", "connectors", "input_fields", "datapill_fields", "description", "usage"],
                "type": "best_fields",
                "operator": "or",
            }
        }

    if strategy == "cross_fields_sud":
        return {
            "multi_match": {
                "query": query,
                "fields": ["search_text", "usage", "description"],
                "type": "cross_fields",
                "operator": "or",
            }
        }

    if strategy == "smart_routed":
        category, rewritten, _ = classify_and_rewrite(query)
        if category == "technical":
            return {
                "multi_match": {
                    "query": rewritten,
                    "fields": ["search_text", "connectors"],
                    "type": "cross_fields",
                    "operator": "or",
                }
            }
        if category == "mixed":
            return {
                "multi_match": {
                    "query": rewritten,
                    "fields": ["search_text", "connectors", "description"],
                    "type": "cross_fields",
                    "operator": "or",
                }
            }
        # business_intent — keep full query for semantic richness
        return {
            "multi_match": {
                "query": rewritten,
                "fields": ["description", "usage"],
                "type": "cross_fields",
                "operator": "or",
            }
        }

    raise ValueError(f"Unknown strategy: {strategy}")


def _rrf_weights(strategy: str, query: str) -> tuple[float, float]:
    """Return (w_fts, w_dense)."""
    if strategy == "routed":
        if _is_structured(query):
            return 2.0, 1.0   # field queries: trust BM25 more
        return 1.0, 1.5       # intent queries: trust dense more
    return 1.0, 1.0           # equal weights for all other strategies


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_query(text: str) -> list[float]:
    resp = requests.post(
        BASETEN_URL,
        headers={"Authorization": f"Api-Key {BASETEN_KEY}"},
        json={"input": [f"{INSTRUCTION}{text}"], "model": "model", "encoding_format": "float"},
        timeout=300,
    )
    resp.raise_for_status()
    vec = resp.json()["data"][0]["embedding"][:DIMS]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _inject_tag_into_query(query_body: dict, tag: str) -> dict:
    """Append tag tokens to a multi_match or match query's query string."""
    import copy
    body = copy.deepcopy(query_body)
    mm = body.get("multi_match") or body.get("bool", {}).get("must", {}).get("multi_match")
    if mm:
        mm["query"] = f"{mm['query']} {tag}"
        return body
    m = body.get("match")
    if m:
        field = next(iter(m))
        if isinstance(m[field], dict):
            m[field]["query"] = f"{m[field]['query']} {tag}"
        else:
            m[field] = f"{m[field]} {tag}"
        return body
    return body


def run_bm25(client: OpenSearch, query_body: dict, k: int,
             tag: str | None = None) -> tuple[list[dict], bool]:
    """Returns (hits, tag_matched). Falls back to tag-enriched unfiltered query if tag yields 0 hits."""
    if tag:
        hits = client.search(index=INDEX_NAME, body={
            "size": k, "_source": False,
            "query": apply_tag_filter(query_body, tag),
        })["hits"]["hits"]
        if hits:
            return hits, True
        # no match for tag — fall back with tag appended to query text
        query_body = _inject_tag_into_query(query_body, tag)
    hits = client.search(index=INDEX_NAME, body={
        "size": k, "_source": False, "query": query_body,
    })["hits"]["hits"]
    return hits, False


def run_knn(client: OpenSearch, vector: list[float], k: int,
            tag: str | None = None) -> tuple[list[dict], bool]:
    """Returns (hits, tag_matched). Falls back to unfiltered if tag yields 0 hits.
    (Dense uses the original vector; tag is already absent from embedding input.)
    """
    knn_query: dict = {"knn": {"combined_qwen": {"vector": vector, "k": k}}}
    if tag:
        hits = client.search(index=INDEX_NAME, body={
            "size": k, "_source": False,
            "query": apply_tag_filter(knn_query, tag),
        })["hits"]["hits"]
        if hits:
            return hits, True
    hits = client.search(index=INDEX_NAME, body={
        "size": k, "_source": False, "query": knn_query,
    })["hits"]["hits"]
    return hits, False


def rrf_fusion(dense_hits: list[dict], fts_hits: list[dict],
               w_dense: float, w_fts: float, top_k: int) -> list[tuple[str, float, int | None, int | None]]:
    dense_ranks = {h["_id"]: i + 1 for i, h in enumerate(dense_hits)}
    fts_ranks   = {h["_id"]: i + 1 for i, h in enumerate(fts_hits)}
    all_ids = set(dense_ranks) | set(fts_ranks)
    scored = []
    for doc_id in all_ids:
        dc = w_dense / (RRF_K + dense_ranks[doc_id]) if doc_id in dense_ranks else 0.0
        fc = w_fts   / (RRF_K + fts_ranks[doc_id])   if doc_id in fts_ranks   else 0.0
        scored.append((doc_id, dc + fc, dense_ranks.get(doc_id), fts_ranks.get(doc_id)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def dense_only_search(client: OpenSearch, vector: list[float], top_k: int,
                      tag: str | None = None) -> list[dict]:
    hits, _ = run_knn(client, vector, top_k, tag=tag)
    doc_ids = [h["_id"] for h in hits]
    mget = client.mget(
        index=INDEX_NAME, body={"ids": doc_ids},
        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
    )
    doc_map = {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}
    results = []
    for rank, hit in enumerate(hits, 1):
        src = doc_map.get(hit["_id"], {})
        results.append({
            "_id": hit["_id"], "dense_score": hit["_score"],
            "dense_rank": rank, **src,
        })
    return results


def bm25_only_search(client: OpenSearch, query: str, strategy: str, top_k: int,
                     tag: str | None = None) -> list[dict]:
    q_body = bm25_query(strategy, query)
    hits, tag_matched = run_bm25(client, q_body, top_k, tag=tag)
    if tag and not tag_matched:
        print(f"  [tag '{tag}' not found — showing unfiltered results]")

    doc_ids = [h["_id"] for h in hits]
    mget = client.mget(
        index=INDEX_NAME, body={"ids": doc_ids},
        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
    )
    doc_map = {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}

    results = []
    for rank, hit in enumerate(hits, 1):
        src = doc_map.get(hit["_id"], {})
        results.append({
            "_id": hit["_id"], "bm25_score": hit["_score"],
            "bm25_rank": rank, **src,
        })
    return results


def hybrid_search(client: OpenSearch, query: str, vector: list[float],
                  strategy: str, top_k: int) -> list[dict]:
    candidate_k = top_k * CANDIDATE_MULTIPLIER
    w_fts, w_dense = _rrf_weights(strategy, query)
    q_body = bm25_query(strategy, query)

    fts_hits, _   = run_bm25(client, q_body, candidate_k)
    dense_hits, _ = run_knn(client, vector, candidate_k)
    top = rrf_fusion(dense_hits, fts_hits, w_dense, w_fts, top_k)

    doc_ids = [t[0] for t in top]
    mget = client.mget(
        index=INDEX_NAME, body={"ids": doc_ids},
        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
    )
    doc_map = {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}

    results = []
    for doc_id, score, dense_rank, fts_rank in top:
        src = doc_map.get(doc_id, {})
        results.append({
            "_id": doc_id, "rrf_score": score,
            "dense_rank": dense_rank, "fts_rank": fts_rank,
            **src,
        })
    return results

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

STRATEGIES = ["search_text_only", "description_usage", "cross_fields_all",
              "cross_fields_tech", "routed", "best_fields", "cross_fields_sud", "smart_routed"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--strategy", choices=STRATEGIES + ["all"], default="all")
    parser.add_argument("--mode", choices=["bm25", "hybrid"], default="bm25")
    args = parser.parse_args()

    strategies = STRATEGIES if args.strategy == "all" else [args.strategy]
    client = OpenSearch(OPENSEARCH_URL)

    for query in QUERIES:
        category, rewritten, tag = classify_and_rewrite(query)
        print("\n" + "=" * 80)
        print(f"QUERY:     {query}")
        print(f"Type:      {category}")
        print(f"Rewritten: {rewritten}")
        print(f"Tag filter: {tag or '(none)'}")
        print("=" * 80)

        # embed for dense or hybrid paths
        vector = None
        if args.mode == "hybrid" or (args.strategy == "smart_routed" and category in ("mixed", "business_intent")):
            t0 = time.perf_counter()
            vector = embed_query(query)
            print(f"Embedded in {(time.perf_counter()-t0)*1000:.0f}ms")

        for strategy in strategies:
            if strategy == "smart_routed":
                if category == "technical":
                    results = bm25_only_search(client, query, strategy, args.top_k, tag=tag)
                    print(f"\n--- {strategy:25s}  [bm25-only, technical] ---")
                    for i, r in enumerate(results, 1):
                        desc = (r.get("description") or "")[:80].replace("\n", " ")
                        print(f"  #{i:2d}  bm25={r['bm25_score']:7.3f}  "
                              f"{r['_id']:30s}  {r.get('connectors','')[:40]}")
                        if args.verbose:
                            print(f"        {desc}")
                elif category == "mixed":
                    candidate_k = args.top_k * CANDIDATE_MULTIPLIER
                    q_body = bm25_query(strategy, query)
                    fts_hits, fts_tag_matched = run_bm25(client, q_body, candidate_k, tag=tag)
                    dense_hits, _ = run_knn(client, vector, candidate_k, tag=tag)
                    if tag and not fts_tag_matched:
                        print(f"  [tag '{tag}' not found — showing unfiltered results]")
                    top = rrf_fusion(dense_hits, fts_hits, w_dense=1.0, w_fts=1.0, top_k=args.top_k)
                    doc_ids = [t[0] for t in top]
                    mget = client.mget(
                        index=INDEX_NAME, body={"ids": doc_ids},
                        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
                    )
                    doc_map = {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}
                    results = []
                    for doc_id, score, dense_rank, fts_rank in top:
                        src = doc_map.get(doc_id, {})
                        results.append({"_id": doc_id, "rrf_score": score,
                                        "dense_rank": dense_rank, "fts_rank": fts_rank, **src})
                    print(f"\n--- {strategy:25s}  [hybrid rrf, mixed] ---")
                    for i, r in enumerate(results, 1):
                        desc = (r.get("description") or "")[:80].replace("\n", " ")
                        dr = f"d{r['dense_rank']}" if r['dense_rank'] else "  -"
                        fr = f"f{r['fts_rank']}"   if r['fts_rank']   else "  -"
                        print(f"  #{i:2d}  rrf={r['rrf_score']:.5f}  {dr:4s}/{fr:4s}  "
                              f"{r['_id']:30s}  {r.get('connectors','')[:40]}")
                        if args.verbose:
                            print(f"        {desc}")
                else:  # business_intent — hybrid rrf equal weights
                    candidate_k = args.top_k * CANDIDATE_MULTIPLIER
                    q_body = bm25_query(strategy, query)
                    fts_hits, fts_tag_matched = run_bm25(client, q_body, candidate_k, tag=tag)
                    dense_hits, _ = run_knn(client, vector, candidate_k, tag=tag)
                    if tag and not fts_tag_matched:
                        print(f"  [tag '{tag}' not found — showing unfiltered results]")
                    top = rrf_fusion(dense_hits, fts_hits, w_dense=1.0, w_fts=1.0, top_k=args.top_k)
                    doc_ids = [t[0] for t in top]
                    mget = client.mget(
                        index=INDEX_NAME, body={"ids": doc_ids},
                        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
                    )
                    doc_map = {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}
                    results = []
                    for doc_id, score, dense_rank, fts_rank in top:
                        src = doc_map.get(doc_id, {})
                        results.append({"_id": doc_id, "rrf_score": score,
                                        "dense_rank": dense_rank, "fts_rank": fts_rank, **src})
                    print(f"\n--- {strategy:25s}  [hybrid rrf, business_intent] ---")
                    for i, r in enumerate(results, 1):
                        desc = (r.get("description") or "")[:80].replace("\n", " ")
                        dr = f"d{r['dense_rank']}" if r['dense_rank'] else "  -"
                        fr = f"f{r['fts_rank']}"   if r['fts_rank']   else "  -"
                        print(f"  #{i:2d}  rrf={r['rrf_score']:.5f}  {dr:4s}/{fr:4s}  "
                              f"{r['_id']:30s}  {r.get('connectors','')[:40]}")
                        if args.verbose:
                            print(f"        {desc}")
            elif args.mode == "bm25":
                results = bm25_only_search(client, query, strategy, args.top_k)
                print(f"\n--- {strategy:25s} ---")
                for i, r in enumerate(results, 1):
                    desc = (r.get("description") or "")[:80].replace("\n", " ")
                    print(f"  #{i:2d}  bm25={r['bm25_score']:7.3f}  "
                          f"{r['_id']:30s}  {r.get('connectors','')[:40]}")
                    if args.verbose:
                        print(f"        {desc}")
            else:
                w_fts, w_dense = _rrf_weights(strategy, query)
                results = hybrid_search(client, query, vector, strategy, args.top_k)
                print(f"\n--- {strategy:25s}  (w_fts={w_fts}, w_dense={w_dense}) ---")
                for i, r in enumerate(results, 1):
                    desc = (r.get("description") or "")[:80].replace("\n", " ")
                    dr = f"d{r['dense_rank']}" if r['dense_rank'] else "  -"
                    fr = f"f{r['fts_rank']}"   if r['fts_rank']   else "  -"
                    print(f"  #{i:2d}  rrf={r['rrf_score']:.5f}  {dr:4s}/{fr:4s}  "
                          f"{r['_id']:30s}  {r.get('connectors','')[:40]}")
                    if args.verbose:
                        print(f"        {desc}")


if __name__ == "__main__":
    main()
