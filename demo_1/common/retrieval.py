from __future__ import annotations

import re
from collections import defaultdict

from common.models import EmbeddingModel

RRF_K = 60
TOKEN_RE = re.compile(r"\b\w+(?:[_/.-]\w+)*\b")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "did",
    "do", "does", "find", "for", "from", "how", "i", "if", "in", "into",
    "is", "it", "me", "my", "of", "on", "or", "our", "please", "show",
    "should", "tell", "that", "the", "this", "to", "using", "we", "what",
    "when", "where", "which", "why", "with", "would", "you", "your",
}


def fts_search(client, query: str, k: int, field: str = "text_no_comments") -> list[str]:
    resp = client.search(
        index="recipes",
        body={
            "query": {"match": {field: {"query": query, "operator": "or"}}},
            "size": k,
            "_source": False,
        },
    )
    return [hit["_id"] for hit in resp["hits"]["hits"]]


def dense_search(client, model: EmbeddingModel, query: str, k: int) -> list[str]:
    embedding = model.embed_query(query)
    resp = client.search(
        index=model.table,
        body={
            "query": {"knn": {"embedding": {"vector": embedding, "k": k}}},
            "size": k,
            "_source": False,
        },
    )
    return [hit["_id"] for hit in resp["hits"]["hits"]]


def rrf(ranked_lists: list[tuple[list[str], float]]) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranked, weight in ranked_lists:
        for rank, uid in enumerate(ranked, start=1):
            scores[uid] += weight * (1.0 / (RRF_K + rank))
    return sorted(scores, key=lambda uid: scores[uid], reverse=True)


def query_signal(query: str) -> str:
    raw_tokens = [tok.lower() for tok in TOKEN_RE.findall(query)]
    important_tokens = [tok for tok in raw_tokens if len(tok) > 2 and tok not in STOPWORDS]
    has_structured_exact = any(
        "_" in tok or "/" in tok or "-" in tok or any(ch.isdigit() for ch in tok)
        for tok in raw_tokens
    )
    if has_structured_exact:
        return "structured_exact"
    if len(important_tokens) <= 5 and any(len(tok) >= 5 for tok in important_tokens):
        return "technical_words"
    return "natural_language"


def weights_for_signal(signal: str) -> tuple[str, float, float]:
    if signal == "structured_exact":
        return signal, 2.0, 1.0
    if signal == "technical_words":
        return signal, 1.0, 2.0
    return signal, 0.0, 1.0


def fetch_sources(client, recipe_uids: list[str]) -> list[dict]:
    resp = client.mget(
        index="recipes",
        body={
            "docs": [
                {
                    "_id": uid,
                    "_source": [
                        "flow_id",
                        "version_no",
                        "step_count",
                        "connectors",
                        "actions",
                        "input_fields",
                        "datapill_fields",
                        "text_no_comments",
                    ],
                }
                for uid in recipe_uids
            ]
        },
    )
    by_id = {doc["_id"]: doc.get("_source", {}) for doc in resp["docs"] if doc.get("found")}
    return [{"recipe_uid": uid, **by_id.get(uid, {})} for uid in recipe_uids]
