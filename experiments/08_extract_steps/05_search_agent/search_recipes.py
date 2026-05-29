"""
search_recipes.py — Self-contained hybrid search tool for the recipe search agent.

Combines BM25 + dense kNN with RRF fusion. Step extraction is a separate step.

Public API:
    search_recipes(os_client, query, category, top_k, tag)
        -> tuple[list[dict], bool]
        Returns ranked recipes with metadata + search_text. tag_matched is False
        when a tag was requested but no documents carried that tag.

    extract_steps(llm_client, query, results)
        -> list[dict]
        Sends all recipes to GPT in batches, extracts query-relevant steps,
        and returns results with relevant_steps in place of search_text.

    category: "technical" | "mixed" | "business_intent"
    tag:      optional connector tag filter (snake_case), e.g. "salesforce"
"""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from langfuse.openai import OpenAI
from opensearchpy import OpenSearch
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INDEX_NAME = "bt_recipe"

BASETEN_EMBED_URL = "https://model-qrjgv4v3.api.baseten.co/environments/production/predict"
BASETEN_KEY       = os.environ["BASETEN_API_KEY"]
EMBED_DIMS = 4096

TOP_K_DEFAULT        = 10
CANDIDATE_MULTIPLIER = 3
RRF_K                = 60

GPT_MODEL        = "azure/gpt-5.2"
BATCH_CHAR_LIMIT = 400_000   # max search_text chars per LLM call

EXTRACTION_SYSTEM_PROMPT = """\
You are given a search query and a list of automation recipes.
For each recipe, extract the steps relevant to the query based on what the steps do, not exact wording.
A step is relevant if its action, connector, or fields relate to the intent of the query.

Rules:
- Treat each recipe independently. Do NOT deduplicate steps across recipes — if the same step type appears in multiple recipes, include it in every recipe where it is relevant.
- Include every relevant step occurrence within a recipe, even if the same action type repeats in different branches.
- You MUST process every recipe in the input and return one entry per recipe.
- If no steps are relevant for a recipe, return an empty list for that recipe."""

# ---------------------------------------------------------------------------
# Pydantic schemas for structured output
# ---------------------------------------------------------------------------

class RecipeSteps(BaseModel):
    recipe_uid: str
    relevant_steps: list[str]

class ExtractionResult(BaseModel):
    recipes: list[RecipeSteps]

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

def _bm25_query(category: str, rewritten: str) -> dict:
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
    # business_intent
    return {
        "multi_match": {
            "query": rewritten,
            "fields": ["description", "usage"],
            "type": "cross_fields",
            "operator": "or",
        }
    }


def _apply_tag_filter(query_body: dict, tag: str) -> dict:
    return {
        "bool": {
            "must": query_body,
            "filter": {"match": {"tag": {"query": tag, "operator": "and"}}},
        }
    }


def _inject_tag_into_query(query_body: dict, tag: str) -> dict:
    body = copy.deepcopy(query_body)
    mm = body["multi_match"]
    mm["query"] = f"{mm['query']} {tag}"
    return body

# ---------------------------------------------------------------------------
# OpenSearch runners
# ---------------------------------------------------------------------------

def _run_bm25(client: OpenSearch, query_body: dict, k: int,
              tag: str | None) -> tuple[list[dict], bool]:
    if tag:
        hits = client.search(index=INDEX_NAME, body={
            "size": k, "_source": False,
            "query": _apply_tag_filter(query_body, tag),
        })["hits"]["hits"]
        if hits:
            return hits, True
        query_body = _inject_tag_into_query(query_body, tag)
    hits = client.search(index=INDEX_NAME, body={
        "size": k, "_source": False, "query": query_body,
    })["hits"]["hits"]
    return hits, False


def _run_knn(client: OpenSearch, vector: list[float], k: int,
             tag: str | None, query: str = "") -> tuple[list[dict], bool]:
    knn_query: dict = {"knn": {"combined_qwen": {"vector": vector, "k": k}}}
    if tag:
        hits = client.search(index=INDEX_NAME, body={
            "size": k, "_source": False,
            "query": _apply_tag_filter(knn_query, tag),
        })["hits"]["hits"]
        if hits:
            return hits, True
        fallback_vector = embed_query(f"{query} {tag}" if query else tag)
        fallback_knn: dict = {"knn": {"combined_qwen": {"vector": fallback_vector, "k": k}}}
        hits = client.search(index=INDEX_NAME, body={
            "size": k, "_source": False, "query": fallback_knn,
        })["hits"]["hits"]
        return hits, False
    hits = client.search(index=INDEX_NAME, body={
        "size": k, "_source": False, "query": knn_query,
    })["hits"]["hits"]
    return hits, False


def _rrf_fusion(dense_hits: list[dict], fts_hits: list[dict],
                top_k: int) -> list[tuple[str, float]]:
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
    return scored[:top_k]


def _fetch_docs(client: OpenSearch, doc_ids: list[str]) -> dict[str, dict]:
    if not doc_ids:
        return {}
    mget = client.mget(
        index=INDEX_NAME, body={"ids": doc_ids},
        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
    )
    return {d["_id"]: d["_source"] for d in mget["docs"] if d.get("found")}

# ---------------------------------------------------------------------------
# Step extraction internals
# ---------------------------------------------------------------------------

def _call_extraction_llm(llm_client: OpenAI, query: str, recipes: list[dict]) -> list[dict]:
    """One LLM call for a batch of recipes using Pydantic structured output."""
    blocks = "\n\n".join(
        f"[Recipe {r['recipe_uid']}]\n{r['search_text']}" for r in recipes
    )
    user_prompt = f"Query: {query}\n\nRecipes:\n{blocks}"
    resp = llm_client.beta.chat.completions.parse(
        model=GPT_MODEL,
        max_completion_tokens=4096,
        temperature=0,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format=ExtractionResult,
    )
    result = resp.choices[0].message.parsed
    return [r.model_dump() for r in result.recipes] if result else []


def _build_batches(results: list[dict]) -> list[list[dict]]:
    """Split results into batches where each batch's total search_text ≤ BATCH_CHAR_LIMIT."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for r in results:
        n = len(r.get("search_text", ""))
        if current and current_chars + n > BATCH_CHAR_LIMIT:
            batches.append(current)
            current, current_chars = [], 0
        current.append(r)
        current_chars += n
    if current:
        batches.append(current)
    return batches

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_recipes(os_client: OpenSearch, query: str, category: str,
                   top_k: int = TOP_K_DEFAULT,
                   tag: str | None = None) -> tuple[list[dict], bool]:
    """
    Hybrid recipe search. Returns ranked recipes with metadata + search_text.
    Call extract_steps() on the results before sending to the agent.

    Returns (results, tag_matched) — tag_matched is False when a tag was
    requested but no documents carried that tag (results are a fallback).
    """
    q_body = _bm25_query(category, query)
    candidate_k = top_k * CANDIDATE_MULTIPLIER

    if category == "technical":
        hits, tag_matched = _run_bm25(os_client, q_body, top_k, tag)
        doc_map = _fetch_docs(os_client, [h["_id"] for h in hits])
        return [
            {"recipe_uid": h["_id"], "score": h["_score"], "score_type": "bm25",
             **doc_map.get(h["_id"], {})}
            for h in hits
        ], tag_matched

    # mixed or business_intent — hybrid RRF
    vector = embed_query(query)
    fts_hits, fts_tag_matched = _run_bm25(os_client, q_body, candidate_k, tag)
    dense_hits, knn_tag_matched = _run_knn(os_client, vector, candidate_k, tag, query)
    tag_matched = fts_tag_matched or knn_tag_matched
    top = _rrf_fusion(dense_hits, fts_hits, top_k)

    doc_map = _fetch_docs(os_client, [doc_id for doc_id, _ in top])
    return [
        {"recipe_uid": doc_id, "score": score, "score_type": "rrf",
         **doc_map.get(doc_id, {})}
        for doc_id, score in top
    ], tag_matched


def extract_steps(llm_client: OpenAI, query: str,
                  results: list[dict]) -> list[dict]:
    """
    Send all recipes to GPT in batches (up to BATCH_CHAR_LIMIT chars each),
    extract query-relevant steps, and return agent-ready results.

    Each result in the output contains:
        recipe_uid, description, score, score_type, relevant_steps
    search_text is dropped.
    """
    # Build a uid -> result index to merge extraction output back in order
    uid_to_result = {r["recipe_uid"]: r for r in results}

    for batch in _build_batches(results):
        extracted = _call_extraction_llm(llm_client, query, batch)
        for item in extracted:
            uid = item.get("recipe_uid")
            if uid in uid_to_result:
                uid_to_result[uid]["relevant_steps"] = item.get("relevant_steps", [])

    return [
        {k: v for k, v in uid_to_result[r["recipe_uid"]].items() if k != "search_text"}
        for r in results
    ]
