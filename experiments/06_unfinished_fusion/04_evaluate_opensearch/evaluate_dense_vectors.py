"""
evaluate_dense_vectors.py
=================

Evaluates OpenSearch kNN (HNSW) dense search for Category 1, 2, and 3 queries.
Mirrors pipeline/03_evaluate_postgre/evaluate_dense.py but uses OpenSearch
kNN queries instead of pgvector.

Ground truth: `strong_list` column from the eval datasets.

Metrics
-------
    Precision@k  = |retrieved[:k] ∩ relevant| / k
    Recall@k     = |retrieved[:k] ∩ relevant| / |relevant|
    MRR          = mean(1 / rank_of_first_relevant)

Usage
-----
    python pipeline/04_evaluate_opensearch/evaluate_dense_vectors.py
    python pipeline/04_evaluate_opensearch/evaluate_dense_vectors.py --model "Qwen/Qwen3-Embedding-8B-full+instruct"
    python pipeline/04_evaluate_opensearch/evaluate_dense_vectors.py --model "Qwen/Qwen3-Embedding-8B-full+instruct" --k 10
Environment variables
---------------------
    BASE_URL, API_KEY              — OpenAI-compatible gateway (text-embedding-3-*)
    BASETEN_API_KEY                — Baseten API key
    HF_TOKEN                       — HuggingFace token (optional)
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_client, parse_uid_list
from metrics import precision_at_k, recall_at_k, reciprocal_rank, write_summary
from models import MODEL_REGISTRY, EmbeddingModel

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT1_PATH = EVAL_DIR / "category1_dataset.csv"
CAT2_PATH = EVAL_DIR / "category2_dataset.csv"
CAT3_PATH = EVAL_DIR / "category3_dataset.csv"


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

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


class OsKnnEvaluator:
    """
    Evaluates one embedding model against all three eval categories using
    OpenSearch kNN (HNSW).

    Parameters
    ----------
    model_name : registry key from models.MODEL_REGISTRY
    k          : number of results to retrieve per query
    client     : OpenSearch client from clients.get_client()
    """

    def __init__(self, model_name: str, k: int, client):
        self.model  = EmbeddingModel(model_name)
        self.k      = k
        self.client = client

    def _search(self, embedding: list[float]) -> list[str]:
        resp = self.client.search(
            index=self.model.table,
            body={
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": embedding,
                            "k":      self.k,
                        }
                    }
                },
                "size":    self.k,
                "_source": False,
            },
        )
        return [hit["_id"] for hit in resp["hits"]["hits"]]

    def evaluate_category(self, df: pd.DataFrame, category_name: str) -> pd.DataFrame:
        k       = self.k
        records = []
        skipped = 0

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set   = set(parse_uid_list(row["weak_list"]))

            if not strong_set:
                skipped += 1
                continue

            embedding = self.model.embed_query(row["query"])
            t0 = time.perf_counter()
            retrieved  = self._search(embedding)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            records.append({
                "model":            self.model.name,
                "search_mode":      "os-hnsw",
                "category":         category_name,
                "query_id":         row["query_id"],
                "query":            row["query"],
                "n_strong":         len(strong_set),
                "n_weak":           len(weak_set),
                f"precision@{k}":   precision_at_k(retrieved, strong_set, k),
                f"recall@{k}":      recall_at_k(retrieved, strong_set),
                "rr":               reciprocal_rank(retrieved, strong_set),
                "strong_hits_top5": sum(1 for u in retrieved[:k] if u in strong_set),
                "weak_hits_top5":   sum(1 for u in retrieved[:k] if u in weak_set),
                "latency_ms":       round(latency_ms, 3),
                "retrieved":        ", ".join(retrieved),
                "strong_list":      ", ".join(sorted(strong_set)),
                "weak_list":        ", ".join(sorted(weak_set)),
            })

        if skipped:
            print(f"  Skipped {skipped} queries (empty strong list)")
        return pd.DataFrame(records)

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        k   = self.k
        cfg = self.model.config
        instruction_note = " +instruction" if cfg.instruction else ""
        store_dim_note   = f" → truncated={cfg.store_dim}" if cfg.store_dim else ""

        print(f"{'=' * 60}")
        print(
            f"Model: {self.model.name}  |  backend={cfg.backend}{instruction_note}"
            f"  |  k={k}"
        )
        print(
            f"Storage: dim={cfg.dimension or 'query-only'}{store_dim_note}"
        )
        print(f"OpenSearch HNSW (ef_construction=512, m=16)")
        print(f"{'=' * 60}")

        detail_frames: list[pd.DataFrame] = []
        metrics:       list[CategoryMetrics] = []

        for cat_name, df in category_dfs:
            print(f"\n── {cat_name} ──")
            results = self.evaluate_category(df, cat_name)
            detail_frames.append(results)

            p              = results[f"precision@{k}"].mean()
            r              = results[f"recall@{k}"].mean()
            mrr            = results["rr"].mean()
            avg_strong     = results["strong_hits_top5"].mean()
            avg_weak       = results["weak_hits_top5"].mean()
            avg_latency_ms = results["latency_ms"].mean()

            print(f"  Queries evaluated    : {len(results)}")
            print(f"  Precision@{k}         : {p:.4f}")
            print(f"  Recall@{k}            : {r:.4f}")
            print(f"  MRR                  : {mrr:.4f}")
            print(f"  Avg strong hits@{k}   : {avg_strong:.4f}")
            print(f"  Avg weak hits@{k}     : {avg_weak:.4f}")
            print(f"  Avg latency/query ms : {avg_latency_ms:.2f}")

            metrics.append(CategoryMetrics(
                model           = self.model.name,
                search_mode     = "os-hnsw",
                category        = cat_name,
                n_queries       = len(results),
                precision       = round(p, 4),
                recall          = round(r, 4),
                mrr             = round(mrr, 4),
                avg_strong_hits = round(avg_strong, 4),
                avg_weak_hits   = round(avg_weak, 4),
                avg_latency_ms  = round(avg_latency_ms, 2),
            ))

        return detail_frames, metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", nargs="+", choices=list(MODEL_REGISTRY),
        default=["Qwen/Qwen3-Embedding-8B-full+instruct"],
        help="Embedding model(s) to evaluate (default: Qwen/Qwen3-Embedding-8B-full+instruct)",
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--category", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3],
    )
    args = parser.parse_args()

    k = args.k
    all_cats = [
        ("Category 1", pd.read_csv(CAT1_PATH)),
        ("Category 2", pd.read_csv(CAT2_PATH)),
        ("Category 3", pd.read_csv(CAT3_PATH)),
    ]
    selected_cats = [(name, df) for name, df in all_cats
                     if int(name[-1]) in args.category]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    client          = get_client()
    all_summary_rows: list[dict] = []

    for model_name in args.model:
        evaluator = OsKnnEvaluator(model_name, k, client)
        detail_frames, metrics = evaluator.run(selected_cats)

        combined  = pd.concat(detail_frames, ignore_index=True)
        safe_name = model_name.replace("/", "_").replace("-", "_")
        out_path  = BASE_DIR / f"eval_results_{safe_name}_os_hnsw_k{k}.csv"
        combined.to_csv(out_path, index=False)
        print(f"\nDetailed results → {out_path.name}")

        for m in metrics:
            all_summary_rows.append({
                "model":               m.model,
                "search_mode":         m.search_mode,
                "category":            m.category,
                "n_queries":           m.n_queries,
                f"precision@{k}":       m.precision,
                f"recall@{k}":          m.recall,
                "MRR":                 m.mrr,
                f"avg_strong_hits@{k}": m.avg_strong_hits,
                f"avg_weak_hits@{k}":   m.avg_weak_hits,
                "avg_latency_ms":      m.avg_latency_ms,
            })

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    summary_df = pd.DataFrame(all_summary_rows)
    print(summary_df.to_string(index=False))

    write_summary(
        BASE_DIR / f"eval_summary_k{k}.csv",
        summary_df,
        args.model,
        search_mode="os-hnsw",
    )


if __name__ == "__main__":
    main()
