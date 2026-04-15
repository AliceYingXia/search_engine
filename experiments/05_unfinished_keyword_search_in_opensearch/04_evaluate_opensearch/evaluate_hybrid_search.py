"""
evaluate_hybrid_search.py
=========================

Hybrid OpenSearch retrieval that combines:

    1. Full-text search over recipe text (english_underscore + BM25)
    2. Structured keyword/fuzzy search over connectors/actions/field names

The hybrid keeps FTS as the base retriever and boosts structured keyword
search only when the query looks technical. Results are fused with weighted
Reciprocal Rank Fusion (RRF), using query-aware weights:

    natural_language  -> FTS 0.85, keyword 0.15
    mixed             -> FTS 0.60, keyword 0.40
    technical         -> FTS 0.35, keyword 0.65

This avoids relying on raw score comparability across the two retrievers and
keeps the synchronous online path cheap:

    - 1 BM25 query
    - 1 bounded structured fuzzy query
    - 1 in-memory fusion over small candidate lists

Usage
-----
    python pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py
    python pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py --k 10
    python pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py --category 1 2

Environment variables
---------------------
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_client, parse_uid_list
from evaluate_full_text_search import CAT_PATHS as FTS_CAT_PATHS
from evaluate_full_text_search import OsFtsEvaluator
from evaluate_structured_fuzzy_search import (
    ALIASES,
    PHRASE_ALIASES,
    SearchResult,
    OsKeywordEvaluator,
)
from metrics import precision_at_k, recall_at_k, reciprocal_rank, write_summary

BASE_DIR = Path(__file__).parent
RRF_K = 20
DEFAULT_CANDIDATES = 20
_TOKEN_RE = re.compile(r"\b\w+(?:[_/]\w+)*\b")


@dataclass
class CategoryMetrics:
    category: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float


class HybridOpenSearchEvaluator:
    """
    Query-aware hybrid retrieval between FTS and structured keyword search.

    FTS is the main lexical retriever. Structured keyword search adds value
    for technical connector/action/field-style queries.
    """

    def __init__(self, k: int, client, candidate_k: int | None = None):
        self.k = k
        self.client = client
        self.candidate_k = max(candidate_k or DEFAULT_CANDIDATES, k)
        self.fts = OsFtsEvaluator(
            k=self.candidate_k,
            config="english",
            client=client,
            scoring="bm25",
        )
        self.keyword = OsKeywordEvaluator(k=self.candidate_k, client=client)

    @staticmethod
    def _rrf_weighted(ranked_lists: list[tuple[list[str], float]]) -> list[str]:
        scores: dict[str, float] = defaultdict(float)
        for ranked, weight in ranked_lists:
            for rank, uid in enumerate(ranked, start=1):
                scores[uid] += weight * (1.0 / (RRF_K + rank))
        return sorted(scores, key=lambda uid: scores[uid], reverse=True)

    def _classify_query(self, query: str) -> tuple[str, float, float]:
        text = query.lower()
        raw_tokens = _TOKEN_RE.findall(text)

        alias_hits = sum(1 for token in raw_tokens if token in ALIASES)
        phrase_alias_hits = sum(1 for phrase, _ in PHRASE_ALIASES if phrase in text)
        underscore_or_slash = sum(1 for token in raw_tokens if "_" in token or "/" in token)
        connectorish = sum(
            1
            for token in raw_tokens
            if token in {
                "connector", "connectors", "action", "actions", "field", "fields",
                "datapill", "recipe", "recipes", "workflow", "workflows",
            }
        )

        technical_score = (
            underscore_or_slash * 2
            + alias_hits * 2
            + phrase_alias_hits * 2
            + connectorish
        )

        questionish = text.startswith(("how ", "what ", "which ", "when ", "why "))
        long_query = len(raw_tokens) >= 10

        if technical_score >= 3:
            return ("technical", 0.35, 0.65)
        if technical_score >= 1:
            return ("mixed", 0.60, 0.40)
        if questionish or long_query:
            return ("natural_language", 0.85, 0.15)
        return ("mixed", 0.60, 0.40)

    def _search(self, query: str) -> tuple[list[str], dict]:
        bucket, w_fts, w_kw = self._classify_query(query)
        fts_hits = self.fts._search(query)
        kw_result: SearchResult = self.keyword._search(query)
        keyword_hits = kw_result.uids

        fused = self._rrf_weighted([
            (fts_hits, w_fts),
            (keyword_hits, w_kw),
        ])[: self.k]

        meta = {
            "query_bucket": bucket,
            "fts_weight": w_fts,
            "keyword_weight": w_kw,
            "fts_candidates": ", ".join(fts_hits[: self.k]),
            "keyword_candidates": ", ".join(keyword_hits[: self.k]),
            "keyword_search_error": kw_result.error or "",
        }
        return fused, meta

    def evaluate_category(self, df: pd.DataFrame, category_name: str) -> pd.DataFrame:
        records = []
        skipped = 0

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set = set(parse_uid_list(row["weak_list"]))

            if not strong_set:
                skipped += 1
                continue

            retrieved, meta = self._search(row["query"])

            records.append({
                "category": category_name,
                "query_id": row["query_id"],
                "query": row["query"],
                "query_bucket": meta["query_bucket"],
                "fts_weight": meta["fts_weight"],
                "keyword_weight": meta["keyword_weight"],
                "keyword_search_error": meta["keyword_search_error"],
                "fts_candidates_top5": meta["fts_candidates"],
                "keyword_candidates_top5": meta["keyword_candidates"],
                "n_strong": len(strong_set),
                "n_weak": len(weak_set),
                f"precision@{self.k}": precision_at_k(retrieved, strong_set, self.k),
                f"recall@{self.k}": recall_at_k(retrieved, strong_set),
                "rr": reciprocal_rank(retrieved, strong_set),
                "strong_hits_top5": sum(1 for u in retrieved[: self.k] if u in strong_set),
                "weak_hits_top5": sum(1 for u in retrieved[: self.k] if u in weak_set),
                "n_retrieved": len(retrieved),
                "retrieved": ", ".join(retrieved),
                "strong_list": ", ".join(sorted(strong_set)),
                "weak_list": ", ".join(sorted(weak_set)),
            })

        if skipped:
            print(f"  Skipped {skipped} queries (empty strong list)")
        return pd.DataFrame(records)

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        print(f"{'=' * 60}")
        print(f"OpenSearch hybrid  |  k={self.k}  |  candidate_k={self.candidate_k}")
        print("FTS=english/BM25  +  keyword=fuzzy structured search")
        print("Query buckets: natural_language(0.85/0.15), mixed(0.60/0.40), technical(0.35/0.65)")
        print(f"{'=' * 60}")

        detail_frames: list[pd.DataFrame] = []
        metrics: list[CategoryMetrics] = []

        for cat_name, df in category_dfs:
            print(f"\n── {cat_name} ──")
            results = self.evaluate_category(df, cat_name)
            detail_frames.append(results)

            p = results[f"precision@{self.k}"].mean()
            r = results[f"recall@{self.k}"].mean()
            mrr = results["rr"].mean()
            avg_strong = results["strong_hits_top5"].mean()
            avg_weak = results["weak_hits_top5"].mean()
            no_results = (results["n_retrieved"] == 0).sum()
            n_kw_errors = (results["keyword_search_error"] != "").sum()

            print(f"  Queries evaluated   : {len(results)}")
            print(f"  Queries with 0 hits : {no_results}")
            print(f"  Keyword errors      : {n_kw_errors}")
            print(f"  Precision@{self.k}   : {p:.4f}")
            print(f"  Recall@{self.k}      : {r:.4f}")
            print(f"  MRR                 : {mrr:.4f}")
            print(f"  Avg strong hits@{self.k}: {avg_strong:.4f}")
            print(f"  Avg weak hits@{self.k}  : {avg_weak:.4f}")

            metrics.append(CategoryMetrics(
                category=cat_name,
                n_queries=len(results),
                precision=round(p, 4),
                recall=round(r, 4),
                mrr=round(mrr, 4),
                avg_strong_hits=round(avg_strong, 4),
                avg_weak_hits=round(avg_weak, 4),
            ))

        return detail_frames, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--category", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3],
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=DEFAULT_CANDIDATES,
        help="Number of candidates to retrieve from each leg before fusion.",
    )
    args = parser.parse_args()

    selected_cats = [
        (f"Category {n}", pd.read_csv(FTS_CAT_PATHS[n]))
        for n in sorted(args.category)
    ]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    client = get_client()
    evaluator = HybridOpenSearchEvaluator(
        k=args.k,
        candidate_k=args.candidate_k,
        client=client,
    )
    detail_frames, metrics = evaluator.run(selected_cats)

    for frame, (cat_name, _) in zip(detail_frames, selected_cats):
        cat_slug = cat_name.lower().replace(" ", "")
        out_path = BASE_DIR / f"os_hybrid_fts_keyword_{cat_slug}_k{args.k}.csv"
        frame.to_csv(out_path, index=False)
        print(f"Detailed results → {out_path.name}")

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")

    model_key = "os/hybrid/fts-keyword"
    summary_rows = [
        {
            "model": model_key,
            "category": m.category,
            "n_queries": m.n_queries,
            f"precision@{args.k}": m.precision,
            f"recall@{args.k}": m.recall,
            "MRR": m.mrr,
            f"avg_strong_hits@{args.k}": m.avg_strong_hits,
            f"avg_weak_hits@{args.k}": m.avg_weak_hits,
        }
        for m in metrics
    ]
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))

    write_summary(
        BASE_DIR / f"eval_summary_k{args.k}.csv",
        summary_df,
        model_key,
        categories=[m.category for m in metrics],
    )


if __name__ == "__main__":
    main()
