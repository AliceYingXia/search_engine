"""
search_recipes.py
=================

Runtime query script for Demo 1.

Runs live retrieval against OpenSearch using:

- full-text search
- dense vector search
- weighted Reciprocal Rank Fusion (RRF)

This is the production-facing version of the query-signal hybrid logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from common.clients import ensure_opensearch_connection, get_client  # noqa: E402
from common.logging_utils import get_logger  # noqa: E402
from common.models import DEFAULT_MODEL_NAME, EmbeddingModel  # noqa: E402
from common.retrieval import dense_search, fetch_sources, fts_search, query_signal, rrf, weights_for_signal  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-multiplier", type=int, default=3)
    parser.add_argument(
        "--allow-fts-fallback",
        action="store_true",
        help="If dense embedding fails, degrade to FTS-only instead of exiting.",
    )
    args = parser.parse_args()

    if not args.query.strip():
        raise ValueError("Query must not be empty.")

    ensure_opensearch_connection()
    client = get_client()
    model = EmbeddingModel(DEFAULT_MODEL_NAME)
    signal = query_signal(args.query)
    mode_used, w_fts, w_dense = weights_for_signal(signal)
    candidate_k = max(args.top_k * args.candidate_multiplier, args.top_k)
    fallback_mode_used: str | None = None

    fts_hits = fts_search(client, args.query, candidate_k) if w_fts > 0 else []
    dense_hits: list[str] = []
    if w_dense > 0:
        try:
            dense_hits = dense_search(client, model, args.query, candidate_k)
        except Exception:
            if not args.allow_fts_fallback:
                raise
            if not fts_hits:
                fts_hits = fts_search(client, args.query, candidate_k)
                w_fts = 1.0
            fallback_mode_used = "fts_only_after_dense_failure"
            w_dense = 0.0
            logger.warning("Dense retrieval failed; falling back to FTS-only.")
    ranked = rrf([(fts_hits, w_fts), (dense_hits, w_dense)])[: args.top_k]

    result = {
        "query": args.query,
        "model": DEFAULT_MODEL_NAME,
        "signal": signal,
        "mode_used": mode_used,
        "w_fts": w_fts,
        "w_dense": w_dense,
        "fallback_mode_used": fallback_mode_used,
        "fts_candidates": fts_hits[: args.top_k],
        "dense_candidates": dense_hits[: args.top_k],
        "results": fetch_sources(client, ranked),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
