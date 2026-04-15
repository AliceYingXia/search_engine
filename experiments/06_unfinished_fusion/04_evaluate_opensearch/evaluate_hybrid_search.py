"""
evaluate_hybrid_search.py
=========================

Legacy generic entrypoint for the confidence-gated hybrid evaluator.

Prefer one of the clearer names below:

- `evaluate_hybrid_confidence_gated_rrf.py`
- `evaluate_hybrid_query_signal_rrf.py`

Hybrid OpenSearch retrieval that combines:

    1. Full-text search over recipe text (OpenSearch BM25 / coverage scoring)
    2. Dense vector search over recipe embeddings (OpenSearch kNN / HNSW)

The same raw query is sent to both legs. There is no LLM query rewriting.
Fusion happens after retrieval, using weighted Reciprocal Rank Fusion (RRF).

Unlike a fixed-weight hybrid, this evaluator first estimates whether the FTS
leg looks trustworthy for the current query using compact lexical evidence from
structured fields (`connectors`, `actions`, `input_fields`, `datapill_fields`)
rather than scanning full recipe bodies.

It uses:

    - token_coverage
    - rare_token_match
    - hit_depth

Those are combined into an fts_confidence score, which then decides whether to:

    - skip FTS entirely and use dense only
    - fuse with a low FTS weight
    - fuse with a modest FTS weight
    - favor FTS for strong technical exact-match cases

Usage
-----
    python pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py
    python pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py --model "Qwen/Qwen3-Embedding-8B-full+instruct"
    python pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py --scoring coverage --category 2 3 --k 10

Environment variables
---------------------
    BASE_URL, API_KEY              — OpenAI-compatible gateway (text-embedding-3-*)
    BASETEN_API_KEY                — Baseten API key
    HF_TOKEN                       — HuggingFace token (optional)
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
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


class HybridOpenSearchEvaluator:
    """
    Hybrid evaluator that fuses OpenSearch full-text and dense retrieval.

    The query string is not rewritten. We simply run:
      raw query -> FTS
      raw query -> embedding model -> kNN
      FTS list + kNN list -> weighted RRF
    """

    def __init__(
        self,
        model_name: str,
        k: int,
        client,
        *,
        config: str = "english",
        scoring: str = "bm25",
        candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER,
        weighting: str = "signal",
        fts_weight: float = 1.0,
        dense_weight: float = 1.0,
    ):
        self.model = EmbeddingModel(model_name)
        self.k = k
        self.client = client
        self.weighting = weighting
        self.fixed_fts_weight = fts_weight
        self.fixed_dense_weight = dense_weight
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

    @staticmethod
    def _split_structured_value(value: str) -> list[str]:
        parts = re.split(r"[_/.\-\s]+", value.lower())
        return [part for part in parts if part]

    def _query_tokens(self, query: str) -> tuple[list[str], list[str]]:
        raw_tokens = [tok.lower() for tok in TOKEN_RE.findall(query)]
        expanded_tokens: list[str] = []
        for tok in raw_tokens:
            expanded_tokens.extend(self._split_structured_value(tok))
            expanded_tokens.append(tok)
        important_tokens = [
            tok for tok in expanded_tokens
            if len(tok) > 2 and tok not in STOPWORDS
        ]
        rare_tokens = [
            tok for tok in important_tokens
            if "_" in tok
            or "/" in tok
            or "-" in tok
            or any(ch.isdigit() for ch in tok)
            or len(tok) >= 12
        ]
        return list(dict.fromkeys(important_tokens)), list(dict.fromkeys(rare_tokens))

    def _get_candidate_sources(self, uids: list[str]) -> list[dict]:
        if not uids:
            return []
        resp = self.client.mget(
            index="recipes",
            body={
                "docs": [
                    {
                        "_id": uid,
                        "_source": [
                            "connectors",
                            "actions",
                            "input_fields",
                            "datapill_fields",
                        ],
                    }
                    for uid in uids
                ]
            },
        )
        docs_by_id = {
            doc["_id"]: doc.get("_source", {})
            for doc in resp["docs"]
            if doc.get("found")
        }
        return [docs_by_id.get(uid, {}) for uid in uids]

    def _candidate_structured_token_sets(self, candidate_sources: list[dict]) -> list[set[str]]:
        token_sets: list[set[str]] = []
        for src in candidate_sources:
            tokens: set[str] = set()
            for field in ("connectors", "actions", "input_fields", "datapill_fields"):
                values = src.get(field) or []
                if isinstance(values, list):
                    for value in values:
                        text = str(value).lower()
                        if not text:
                            continue
                        tokens.add(text)
                        tokens.update(self._split_structured_value(text))
            token_sets.append(tokens)
        return token_sets

    @staticmethod
    def _compute_token_coverage(important_tokens: list[str], candidate_token_sets: list[set[str]]) -> float:
        if not important_tokens:
            return 0.0
        matched = sum(
            1 for tok in important_tokens
            if any(tok in token_set for token_set in candidate_token_sets)
        )
        return matched / len(important_tokens)

    @staticmethod
    def _compute_rare_token_match(rare_tokens: list[str], candidate_token_sets: list[set[str]]) -> float:
        if not rare_tokens:
            return 0.0
        matched = sum(
            1 for tok in rare_tokens
            if any(tok in token_set for token_set in candidate_token_sets)
        )
        return matched / len(rare_tokens)

    @staticmethod
    def _compute_hit_depth(important_tokens: list[str], candidate_token_sets: list[set[str]], candidate_k: int) -> float:
        if not candidate_token_sets or candidate_k <= 0 or not important_tokens:
            return 0.0
        substantive_hits = sum(
            1
            for token_set in candidate_token_sets
            if any(tok in token_set for tok in important_tokens)
        )
        return min(substantive_hits / candidate_k, 1.0)

    @staticmethod
    def _compute_fts_confidence(
        token_coverage: float,
        rare_token_match: float,
        hit_depth: float,
        *,
        has_rare_tokens: bool,
    ) -> float:
        if has_rare_tokens:
            score = (
                0.45 * token_coverage
                + 0.35 * rare_token_match
                + 0.20 * hit_depth
            )
        else:
            score = (
                0.69 * token_coverage
                + 0.31 * hit_depth
            )
        return max(0.0, min(score, 1.0))

    def _weights(
        self,
        *,
        fts_confidence: float,
        rare_token_match: float,
        token_coverage: float,
    ) -> tuple[str, float, float]:
        if self.weighting == "fixed":
            return "fixed", self.fixed_fts_weight, self.fixed_dense_weight

        # Be conservative: FTS participates only when the lexical evidence is
        # clearly useful. Dense remains the default fallback.
        if fts_confidence < 0.35:
            return "dense_only", 0.0, 1.0
        if rare_token_match >= 0.9 and token_coverage >= 0.75:
            return "fts_favored", 2.0, 1.0
        if fts_confidence < 0.70:
            return "low_fts_weight", 0.35, 1.0
        return "balanced_fuse", 0.75, 1.0

    def _search(self, query: str) -> tuple[list[str], dict]:
        fts_results = self.fts._search(query)
        important_tokens, rare_tokens = self._query_tokens(query)
        candidate_sources = self._get_candidate_sources(fts_results)
        candidate_token_sets = self._candidate_structured_token_sets(candidate_sources)
        token_coverage = self._compute_token_coverage(important_tokens, candidate_token_sets)
        rare_token_match = self._compute_rare_token_match(rare_tokens, candidate_token_sets)
        hit_depth = self._compute_hit_depth(important_tokens, candidate_token_sets, self.candidate_k)
        fts_confidence = self._compute_fts_confidence(
            token_coverage,
            rare_token_match,
            hit_depth,
            has_rare_tokens=bool(rare_tokens),
        )
        signal, w_fts, w_dense = self._weights(
            fts_confidence=fts_confidence,
            rare_token_match=rare_token_match,
            token_coverage=token_coverage,
        )

        embedding = self.model.embed_query(query)
        t0 = time.perf_counter()
        dense_results = self._dense_search(embedding)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if w_fts == 0.0:
            fused = dense_results[: self.k]
        else:
            fused = self._rrf([
                (fts_results, w_fts),
                (dense_results, w_dense),
            ])[: self.k]

        detail = {
            "signal": signal,
            "w_fts": w_fts,
            "w_dense": w_dense,
            "important_tokens": ", ".join(important_tokens),
            "rare_tokens": ", ".join(rare_tokens),
            "token_coverage": round(token_coverage, 4),
            "rare_token_match": round(rare_token_match, 4),
            "hit_depth": round(hit_depth, 4),
            "fts_confidence": round(fts_confidence, 4),
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
            signal_counts[detail["signal"]] += 1

            records.append({
                "model": self.model.name,
                "search_mode": "os-hybrid-rrf",
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
        print(f"  Signal breakdown   : {dict(signal_counts)}")
        return pd.DataFrame(records)

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        cfg = self.model.config
        instruction_note = " +instruction" if cfg.instruction else ""

        print(f"{'=' * 60}")
        print(
            f"OpenSearch hybrid  |  model={self.model.name}  |  backend={cfg.backend}{instruction_note}"
        )
        print(
            f"FTS={self.fts.config}/{self.fts.scoring}  +  dense=os-hnsw  |  k={self.k}  |  candidate_k={self.candidate_k}"
        )
        if self.weighting == "fixed":
            print(f"Weights: fixed (fts={self.fixed_fts_weight}, dense={self.fixed_dense_weight})")
        else:
            print("Weights: confidence-gated, conservative on FTS (dense_only / low_fts_weight / balanced_fuse / fts_favored)")
        print("Confidence features: token_coverage + rare_token_match + hit_depth")
        print("Same raw query is used for both retrieval legs; no LLM rewrite step.")
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
                search_mode="os-hybrid-rrf",
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
        "--weighting", choices=["signal", "fixed"], default="signal",
        help="Use confidence-gated weights or fixed weights for both legs.",
    )
    parser.add_argument("--fts-weight", type=float, default=1.0)
    parser.add_argument("--dense-weight", type=float, default=1.0)
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
    evaluator = HybridOpenSearchEvaluator(
        model_name=args.model,
        k=args.k,
        client=client,
        config=args.config,
        scoring=args.scoring,
        candidate_multiplier=args.candidate_multiplier,
        weighting=args.weighting,
        fts_weight=args.fts_weight,
        dense_weight=args.dense_weight,
    )
    detail_frames, metrics = evaluator.run(selected_cats)

    combined = pd.concat(detail_frames, ignore_index=True)
    safe_model = args.model.replace("/", "_").replace("-", "_").replace("+", "plus")
    out_path = BASE_DIR / f"os_hybrid_rrf_{safe_model}_{args.config}_{args.scoring}_k{args.k}.csv"
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
        search_mode="os-hybrid-rrf",
    )


if __name__ == "__main__":
    main()
