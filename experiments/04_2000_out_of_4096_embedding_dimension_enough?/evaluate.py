from __future__ import annotations

import math


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return sum(1 for doc_id in retrieved[:k] if doc_id in relevant) / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, doc_id in enumerate(retrieved, 1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def dcg_at_k(retrieved: list[str], qrels: dict[str, int], k: int) -> float:
    score = 0.0
    for rank, doc_id in enumerate(retrieved[:k], 1):
        rel = qrels.get(doc_id, 0)
        if rel > 0:
            score += (2**rel - 1) / math.log2(rank + 1)
    return score


def ndcg_at_k(retrieved: list[str], qrels: dict[str, int], k: int) -> float:
    ideal_docs = [doc_id for doc_id, _ in sorted(qrels.items(), key=lambda item: item[1], reverse=True)]
    ideal = dcg_at_k(ideal_docs, qrels, k)
    if ideal == 0:
        return 0.0
    return dcg_at_k(retrieved, qrels, k) / ideal
