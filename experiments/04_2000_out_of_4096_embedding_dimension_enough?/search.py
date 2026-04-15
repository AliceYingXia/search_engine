from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def top_k_exact(
    query_vec: list[float],
    corpus_ids: list[str],
    corpus_vecs: list[list[float]],
    k: int,
) -> list[str]:
    scored = [
        (doc_id, cosine_similarity(query_vec, doc_vec))
        for doc_id, doc_vec in zip(corpus_ids, corpus_vecs)
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [doc_id for doc_id, _ in scored[:k]]
