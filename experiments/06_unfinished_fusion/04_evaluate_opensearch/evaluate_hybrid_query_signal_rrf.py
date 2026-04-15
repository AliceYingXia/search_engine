"""
evaluate_hybrid_query_signal_rrf.py
===================================

Hybrid OpenSearch retrieval using a simple query-signal policy inspired by
`pipeline/03_evaluate_postgre/evaluate_hybrid.py`.

The same raw query is sent to:

    1. OpenSearch full-text search
    2. OpenSearch dense vector search

The two ranked lists are then fused with weighted Reciprocal Rank Fusion (RRF),
but the weights are chosen from the query itself rather than from FTS candidate
quality signals.

Signals
-------
    structured_exact
        Query contains explicit structured identifiers such as underscores,
        slashes, hyphens, or digits. These are strong lexical cues.

    technical_words
        Query is short / technical but not explicitly identifier-heavy.

    natural_language
        Query contains only broad business-language wording.

Modes
-----
    fuse  (default)
        structured_exact -> w_fts=2.0, w_dense=1.0
        technical_words  -> w_fts=1.0, w_dense=2.0
        natural_language -> w_fts=0.0, w_dense=1.0

    route
        structured_exact -> FTS only
        otherwise        -> dense only
"""

from __future__ import annotations

import argparse
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_client, parse_uid_list
from evaluate_full_text_search import CAT_PATHS, OsFtsEvaluator
from metrics import precision_at_k, recall_at_k, reciprocal_rank, write_summary
from models import MODEL_REGISTRY, EmbeddingModel

BASE_DIR = Path(__file__).parent
RRF_K = 60
DEFAULT_CANDIDATE_MULTIPLIER = 3
TOKEN_RE = re.compile(r"\b\w+(?:[_/.-]\w+)*\b")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "i", "if", "in", "into", "is", "it", "of", "on", "or", "that", "the",
    "this", "to", "using", "what", "when", "where", "which", "with", "why",
}


@dataclass
class CategoryMetrics:
    model: str
    search_mode: str
    category: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float
    avg_latency_ms: float


class QuerySignalHybridEvaluator:
    def __init__(
        self,
        model_name: str,
        k: int,
        client,
        *,
        config: str = "english",
        scoring: str = "bm25",
        candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER,
        mode: str = "fuse",
    ):
        self.model = EmbeddingModel(model_name)
        self.k = k
        self.client = client
        self.mode = mode
        self.candidate_k = max(k * candidate_multiplier, k)
        self.fts = OsFtsEvaluator(
            k=self.candidate_k,
            config=config,
            client=client,
            scoring=scoring,
        )

    def _dense_search(self, embedding: list[float]) -> list[str]:
        resp = self.client.search(
            index=self.model.table,
            body={
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": embedding,
                            "k": self.candidate_k,
                        }
                    }
                },
                "size": self.candidate_k,
                "_source": False,
            },
        )
        return [hit["_id"] for hit in resp["hits"]["hits"]]

    @staticmethod
    def _rrf(ranked_lists: list[tuple[list[str], float]]) -> list[str]:
        scores: dict[str, float] = defaultdict(float)
        for ranked, weight in ranked_lists:
            for rank, uid in enumerate(ranked, start=1):
                scores[uid] += weight * (1.0 / (RRF_K + rank))
        return sorted(scores, key=lambda uid: scores[uid], reverse=True)

    def _query_signal(self, query: str) -> tuple[list[str], str]:
        raw_tokens = [tok.lower() for tok in TOKEN_RE.findall(query)]
        important_tokens = [
            tok for tok in raw_tokens
            if len(tok) > 2 and tok not in STOPWORDS
        ]
        has_structured_exact = any(
            "_" in tok or "/" in tok or "-" in tok or any(ch.isdigit() for ch in tok)
            for tok in raw_tokens
        )
        if has_structured_exact:
            return important_tokens, "structured_exact"
        if len(important_tokens) <= 5 and any(len(tok) >= 5 for tok in important_tokens):
            return important_tokens, "technical_words"
        return important_tokens, "natural_language"

    def _weights(self, signal: str) -> tuple[str, float, float]:
        if self.mode == "route":
            if signal == "structured_exact":
                return "fts_only", 1.0, 0.0
            return "dense_only", 0.0, 1.0

        if signal == "structured_exact":
            return signal, 2.0, 1.0
        if signal == "technical_words":
            return signal, 1.0, 2.0
        return signal, 0.0, 1.0

    def _search(self, query: str) -> tuple[list[str], dict]:
        important_tokens, signal = self._query_signal(query)
        mode_used, w_fts, w_dense = self._weights(signal)

        t0 = time.perf_counter()
        fts_results = self.fts._search(query) if w_fts > 0 else []
        embedding = self.model.embed_query(query)
        dense_results = self._dense_search(embedding) if w_dense > 0 else []
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if w_fts > 0 and w_dense > 0:
            fused = self._rrf([
                (fts_results, w_fts),
                (dense_results, w_dense),
            ])[: self.k]
        elif w_fts > 0:
            fused = fts_results[: self.k]
        else:
            fused = dense_results[: self.k]

        detail = {
            "signal": signal,
            "mode_used": mode_used,
            "w_fts": w_fts,
            "w_dense": w_dense,
            "important_tokens": ", ".join(important_tokens),
            "n_fts": len(fts_results),
            "n_dense": len(dense_results),
            "fts_candidates": ", ".join(fts_results[: self.k]),
            "dense_candidates": ", ".join(dense_results[: self.k]),
            "latency_ms": round(latency_ms, 3),
        }
        return fused, detail

    def evaluate_category(self, df: pd.DataFrame, category_name: str) -> pd.DataFrame:
        records = []
        skipped = 0
        signal_counts: dict[str, int] = defaultdict(int)

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set = set(parse_uid_list(row["weak_list"]))

            if not strong_set:
                skipped += 1
                continue

            retrieved, detail = self._search(row["query"])
            signal_counts[detail["mode_used"]] += 1

            records.append({
                "model": self.model.name,
                "search_mode": f"os-hybrid-query-signal-{self.mode}",
                "category": category_name,
                "query_id": row["query_id"],
                "query": row["query"],
                **detail,
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
        print(f"  Mode breakdown     : {dict(signal_counts)}")
        return pd.DataFrame(records)

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        cfg = self.model.config
        instruction_note = " +instruction" if cfg.instruction else ""

        print(f"{'=' * 60}")
        print(
            f"OpenSearch hybrid (query-signal)  |  model={self.model.name}  |  backend={cfg.backend}{instruction_note}"
        )
        print(
            f"FTS={self.fts.config}/{self.fts.scoring}  +  dense=os-hnsw  |  k={self.k}  |  candidate_k={self.candidate_k}  |  mode={self.mode}"
        )
        print("Signals: structured_exact / technical_words / natural_language")
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
            avg_latency_ms = results["latency_ms"].mean()
            no_results = (results["n_retrieved"] == 0).sum()

            print(f"  Queries evaluated   : {len(results)}")
            print(f"  Queries with 0 hits : {no_results}")
            print(f"  Precision@{self.k}   : {p:.4f}")
            print(f"  Recall@{self.k}      : {r:.4f}")
            print(f"  MRR                 : {mrr:.4f}")
            print(f"  Avg strong hits@{self.k}: {avg_strong:.4f}")
            print(f"  Avg weak hits@{self.k}  : {avg_weak:.4f}")
            print(f"  Avg latency/query ms: {avg_latency_ms:.2f}")

            metrics.append(CategoryMetrics(
                model=self.model.name,
                search_mode=f"os-hybrid-query-signal-{self.mode}",
                category=cat_name,
                n_queries=len(results),
                precision=round(p, 4),
                recall=round(r, 4),
                mrr=round(mrr, 4),
                avg_strong_hits=round(avg_strong, 4),
                avg_weak_hits=round(avg_weak, 4),
                avg_latency_ms=round(avg_latency_ms, 2),
            ))

        return detail_frames, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        choices=list(MODEL_REGISTRY),
        default="Qwen/Qwen3-Embedding-8B-full+instruct",
        help="Dense embedding model to use for the dense leg.",
    )
    parser.add_argument(
        "--config", choices=["english", "simple"], default="english",
        help="FTS analyzer config for the lexical leg.",
    )
    parser.add_argument(
        "--scoring", choices=["bm25", "coverage"], default="bm25",
        help="FTS scoring method for the lexical leg.",
    )
    parser.add_argument(
        "--mode", choices=["fuse", "route"], default="fuse",
        help="fuse: weighted RRF by query signal. route: hard route to one leg.",
    )
    parser.add_argument("--candidate-multiplier", type=int, default=DEFAULT_CANDIDATE_MULTIPLIER)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--category", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3],
    )
    args = parser.parse_args()

    selected_cats = [
        (f"Category {n}", pd.read_csv(CAT_PATHS[n]))
        for n in sorted(args.category)
    ]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    client = get_client()
    evaluator = QuerySignalHybridEvaluator(
        model_name=args.model,
        k=args.k,
        client=client,
        config=args.config,
        scoring=args.scoring,
        candidate_multiplier=args.candidate_multiplier,
        mode=args.mode,
    )
    detail_frames, metrics = evaluator.run(selected_cats)

    combined = pd.concat(detail_frames, ignore_index=True)
    safe_model = args.model.replace("/", "_").replace("-", "_").replace("+", "plus")
    out_path = BASE_DIR / f"os_hybrid_query_signal_{args.mode}_{safe_model}_{args.config}_{args.scoring}_k{args.k}.csv"
    combined.to_csv(out_path, index=False)
    print(f"\nDetailed results → {out_path.name}")

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    summary_rows = [
        {
            "model": m.model,
            "search_mode": m.search_mode,
            "category": m.category,
            "n_queries": m.n_queries,
            f"precision@{args.k}": m.precision,
            f"recall@{args.k}": m.recall,
            "MRR": m.mrr,
            f"avg_strong_hits@{args.k}": m.avg_strong_hits,
            f"avg_weak_hits@{args.k}": m.avg_weak_hits,
            "avg_latency_ms": m.avg_latency_ms,
        }
        for m in metrics
    ]
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))

    write_summary(
        BASE_DIR / f"eval_summary_k{args.k}.csv",
        summary_df,
        args.model,
        categories=[m.category for m in metrics],
        search_mode=f"os-hybrid-query-signal-{args.mode}",
    )


if __name__ == "__main__":
    main()
