from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo_1"
sys.path.insert(0, str(DEMO_DIR))

from common.clients import get_client  # noqa: E402
from common.models import DEFAULT_MODEL_NAME, EmbeddingModel  # noqa: E402
from common.retrieval import dense_search, fts_search, query_signal, rrf, weights_for_signal  # noqa: E402


DATA_DIR = ROOT / "pipeline" / "02_synthesize_data"
DEFAULT_OUTPUT_DIR = ROOT / "tests" / "outputs"
CAT_PATHS = [
    ("Category 1", DATA_DIR / "category1_dataset.csv"),
    ("Category 2", DATA_DIR / "category2_dataset.csv"),
    ("Category 3", DATA_DIR / "category3_dataset.csv"),
]


def parse_uid_list(value) -> list[str]:
    if pd.isna(value) or str(value).strip() == "":
        return []
    return [uid.strip() for uid in str(value).split(",") if uid.strip()]


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    return sum(1 for uid in retrieved[:k] if uid in relevant) / k


def recall_at_k(retrieved: list[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    return sum(1 for uid in retrieved if uid in relevant) / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, uid in enumerate(retrieved, 1):
        if uid in relevant:
            return 1.0 / rank
    return 0.0


@dataclass
class CategoryMetrics:
    category: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float
    avg_latency_ms: float


class Demo1HybridEvaluator:
    def __init__(self, k: int, candidate_multiplier: int):
        self.k = k
        self.candidate_k = max(k * candidate_multiplier, k)
        self.client = get_client()
        self.model = EmbeddingModel(DEFAULT_MODEL_NAME)

    def search(self, query: str) -> tuple[list[str], dict]:
        signal = query_signal(query)
        mode_used, w_fts, w_dense = weights_for_signal(signal)

        t0 = time.perf_counter()
        fts_hits = fts_search(self.client, query, self.candidate_k) if w_fts > 0 else []
        dense_hits = dense_search(self.client, self.model, query, self.candidate_k) if w_dense > 0 else []
        ranked = rrf([(fts_hits, w_fts), (dense_hits, w_dense)])[: self.k]
        latency_ms = (time.perf_counter() - t0) * 1000.0

        detail = {
            "signal": signal,
            "mode_used": mode_used,
            "w_fts": w_fts,
            "w_dense": w_dense,
            "n_fts": len(fts_hits),
            "n_dense": len(dense_hits),
            "fts_candidates": ", ".join(fts_hits[: self.k]),
            "dense_candidates": ", ".join(dense_hits[: self.k]),
            "latency_ms": round(latency_ms, 3),
        }
        return ranked, detail

    def evaluate_category(self, category_name: str, df: pd.DataFrame) -> tuple[pd.DataFrame, CategoryMetrics]:
        records: list[dict] = []

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set = set(parse_uid_list(row["weak_list"]))
            if not strong_set:
                continue

            retrieved, detail = self.search(row["query"])
            records.append({
                "model": self.model.name,
                "search_mode": "demo1-hybrid-query-signal-rrf",
                "category": category_name,
                "query_id": row["query_id"],
                "query": row["query"],
                **detail,
                "n_strong": len(strong_set),
                "n_weak": len(weak_set),
                f"precision@{self.k}": precision_at_k(retrieved, strong_set, self.k),
                f"recall@{self.k}": recall_at_k(retrieved, strong_set),
                "rr": reciprocal_rank(retrieved, strong_set),
                "strong_hits_top5": sum(1 for uid in retrieved[: self.k] if uid in strong_set),
                "weak_hits_top5": sum(1 for uid in retrieved[: self.k] if uid in weak_set),
                "retrieved": ", ".join(retrieved),
                "strong_list": ", ".join(sorted(strong_set)),
                "weak_list": ", ".join(sorted(weak_set)),
            })

        results = pd.DataFrame(records)
        metrics = CategoryMetrics(
            category=category_name,
            n_queries=int(len(results)),
            precision=float(results[f"precision@{self.k}"].mean()),
            recall=float(results[f"recall@{self.k}"].mean()),
            mrr=float(results["rr"].mean()),
            avg_strong_hits=float(results["strong_hits_top5"].mean()),
            avg_weak_hits=float(results["weak_hits_top5"].mean()),
            avg_latency_ms=float(results["latency_ms"].mean()),
        )
        return results, metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--candidate-multiplier", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    evaluator = Demo1HybridEvaluator(k=args.k, candidate_multiplier=args.candidate_multiplier)

    detail_frames: list[pd.DataFrame] = []
    metric_rows: list[dict] = []

    print(f"{'=' * 60}")
    print(f"Demo 1 retrieval strategy eval  |  model={DEFAULT_MODEL_NAME}")
    print(f"k={args.k}  |  candidate_k={evaluator.candidate_k}")
    print("Strategy: query-signal weighted RRF across FTS + dense")
    print(f"{'=' * 60}")

    for category_name, path in CAT_PATHS:
        df = pd.read_csv(path)
        print(f"\n── {category_name} ──")
        results, metrics = evaluator.evaluate_category(category_name, df)
        detail_frames.append(results)

        signal_counts = results["mode_used"].value_counts().to_dict()
        zero_hits = int((results["rr"] == 0).sum())

        print(f"  Signal breakdown   : {signal_counts}")
        print(f"  Queries evaluated  : {metrics.n_queries}")
        print(f"  Queries with 0 hits: {zero_hits}")
        print(f"  Precision@{args.k:<2}   : {metrics.precision:.4f}")
        print(f"  Recall@{args.k:<2}      : {metrics.recall:.4f}")
        print(f"  MRR                 : {metrics.mrr:.4f}")
        print(f"  Avg strong hits@{args.k}: {metrics.avg_strong_hits:.4f}")
        print(f"  Avg weak hits@{args.k}  : {metrics.avg_weak_hits:.4f}")
        print(f"  Avg latency/query ms: {metrics.avg_latency_ms:.2f}")

        metric_rows.append({
            "model": DEFAULT_MODEL_NAME,
            "search_mode": "demo1-hybrid-query-signal-rrf",
            "category": metrics.category,
            "n_queries": metrics.n_queries,
            f"precision@{args.k}": metrics.precision,
            f"recall@{args.k}": metrics.recall,
            "MRR": metrics.mrr,
            f"avg_strong_hits@{args.k}": metrics.avg_strong_hits,
            f"avg_weak_hits@{args.k}": metrics.avg_weak_hits,
            "avg_latency_ms": metrics.avg_latency_ms,
        })

    details = pd.concat(detail_frames, ignore_index=True)
    summary = pd.DataFrame(metric_rows)

    detail_path = args.output_dir / f"demo1_retrieval_eval_k{args.k}.csv"
    summary_path = args.output_dir / f"demo1_retrieval_summary_k{args.k}.csv"
    details.to_csv(detail_path, index=False)
    summary.to_csv(summary_path, index=False)

    print(f"\nDetailed results -> {detail_path}")
    print(f"Summary saved   -> {summary_path}")


if __name__ == "__main__":
    main()
