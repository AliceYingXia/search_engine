"""
evaluate_pgvector.py
====================

Evaluates pgvector dense search for Category 1 and Category 2 queries.

Ground truth: `strong_list` column from the eval datasets (recipe UIDs that
both GPT-5.2 and Claude rated as "Strongly Related").  The eval datasets were
built against the same 115 seed recipes that are loaded into pgvector, so the
ground truth is fully covered by the index.

Metrics
-------
    Precision@k  = |retrieved[:k] ∩ relevant| / k
    Recall@k     = |retrieved[:k] ∩ relevant| / |relevant|
    MRR          = mean(1 / rank_of_first_relevant)   (0 if none in top-k)

Usage
-----
    python pipeline/03_evaluate_embeddings/evaluate_pgvector.py
    python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --model text-embedding-3-small
    python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --model text-embedding-3-large --k 10
    python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --model "BAAI/bge-m3" "Qwen/Qwen3-Embedding-0.6B"
    python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --model "Qwen/Qwen3-Embedding-0.6B" "Qwen/Qwen3-Embedding-0.6B+instruct"

Notes
-----
    - Results are appended to eval_summary_k{k}.csv (existing rows for the
      same model are replaced, all others are preserved).
    - The "+instruct" variant reuses the same document vectors as the base
      model but prepends a task instruction to each query at evaluation time.

Environment variables
---------------------
    BASE_URL, API_KEY           — OpenAI-compatible gateway (text-embedding-3-*)
    BASETEN_API_KEY             — Baseten API key
    HF_TOKEN                    — HuggingFace token for gated model downloads (optional)
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_connection
from models import MODEL_REGISTRY, EmbeddingModel

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT1_PATH = EVAL_DIR / "category1_dataset.csv"
CAT2_PATH = EVAL_DIR / "category2_dataset.csv"
CAT3_PATH = EVAL_DIR / "category3_dataset.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_uid_list(s) -> list[str]:
    """Parse a comma-separated string of recipe UIDs."""
    if pd.isna(s) or str(s).strip() == "":
        return []
    return [uid.strip() for uid in str(s).split(",") if uid.strip()]


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

@dataclass
class CategoryMetrics:
    model: str
    category: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float


class PgVectorEvaluator:
    """
    Evaluates one embedding model against Category 1 and Category 2 query sets.

    Parameters
    ----------
    model_name : registry key from models.MODEL_REGISTRY
    k          : number of results to retrieve per query
    conn       : open psycopg2 connection
    """

    def __init__(self, model_name: str, k: int, conn):
        self.model = EmbeddingModel(model_name)
        self.k = k
        self.conn = conn
        self.cur = conn.cursor()

    # ── Search ────────────────────────────────────────────────────────────────

    def _search(self, embedding: list[float]) -> list[str]:
        vec_str = "[" + ",".join(map(str, embedding)) + "]"
        self.cur.execute(
            f"""
            SELECT r.recipe_uid
            FROM   {self.model.table} e
            JOIN   recipes r USING (recipe_uid)
            ORDER  BY e.embedding <=> %s::vector
            LIMIT  %s
            """,
            (vec_str, self.k),
        )
        return [row[0] for row in self.cur.fetchall()]

    # ── Metrics ───────────────────────────────────────────────────────────────

    @staticmethod
    def _precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
        return sum(1 for uid in retrieved[:k] if uid in relevant) / k

    @staticmethod
    def _recall_at_k(retrieved: list[str], relevant: set[str]) -> float:
        if not relevant:
            return 0.0
        return sum(1 for uid in retrieved if uid in relevant) / len(relevant)

    @staticmethod
    def _reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
        for rank, uid in enumerate(retrieved, 1):
            if uid in relevant:
                return 1.0 / rank
        return 0.0

    # ── Per-category evaluation ───────────────────────────────────────────────

    def evaluate_category(self, df: pd.DataFrame, category_name: str) -> pd.DataFrame:
        """Run evaluation over all queries in df. Returns a per-query results DataFrame."""
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
            retrieved = self._search(embedding)

            records.append({
                "category":         category_name,
                "query_id":         row["query_id"],
                "query":            row["query"],
                "n_strong":         len(strong_set),
                "n_weak":           len(weak_set),
                f"precision@{k}":   self._precision_at_k(retrieved, strong_set, k),
                f"recall@{k}":      self._recall_at_k(retrieved, strong_set),
                "rr":               self._reciprocal_rank(retrieved, strong_set),
                "strong_hits_top5": sum(1 for u in retrieved[:k] if u in strong_set),
                "weak_hits_top5":   sum(1 for u in retrieved[:k] if u in weak_set),
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
        """
        Evaluate over the supplied categories.

        Parameters
        ----------
        category_dfs : list of (category_name, DataFrame) pairs

        Returns
        -------
        detail_frames : per-query DataFrames (one per category)
        metrics       : CategoryMetrics for each category
        """
        k = self.k
        cfg = self.model.config
        instruction_note = " +instruction" if cfg.instruction else ""

        print(f"{'=' * 60}")
        print(f"Model: {self.model.name}  |  backend={cfg.backend}{instruction_note}  |  k={k}")
        print(f"{'=' * 60}")

        detail_frames: list[pd.DataFrame] = []
        metrics: list[CategoryMetrics] = []

        for cat_name, df in category_dfs:
            print(f"\n── {cat_name} ──")
            results = self.evaluate_category(df, cat_name)
            detail_frames.append(results)

            p          = results[f"precision@{k}"].mean()
            r          = results[f"recall@{k}"].mean()
            mrr        = results["rr"].mean()
            avg_strong = results["strong_hits_top5"].mean()
            avg_weak   = results["weak_hits_top5"].mean()

            print(f"  Queries evaluated    : {len(results)}")
            print(f"  Precision@{k}         : {p:.4f}")
            print(f"  Recall@{k}            : {r:.4f}")
            print(f"  MRR                  : {mrr:.4f}")
            print(f"  Avg strong hits@{k}   : {avg_strong:.4f}")
            print(f"  Avg weak hits@{k}     : {avg_weak:.4f}")

            metrics.append(CategoryMetrics(
                model           = self.model.name,
                category        = cat_name,
                n_queries       = len(results),
                precision       = round(p, 4),
                recall          = round(r, 4),
                mrr             = round(mrr, 4),
                avg_strong_hits = round(avg_strong, 4),
                avg_weak_hits   = round(avg_weak, 4),
            ))

        return detail_frames, metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        nargs="+",
        choices=list(MODEL_REGISTRY),
        default=["text-embedding-3-large"],
        help="Embedding model(s) to evaluate (default: text-embedding-3-large)",
    )
    parser.add_argument(
        "--k", type=int, default=5,
        help="Number of results to retrieve (default: 5)",
    )
    parser.add_argument(
        "--category", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3],
        help="Which eval categories to run (default: 1 2 3)",
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

    conn = get_connection()
    all_summary_rows: list[dict] = []

    for model_name in args.model:
        evaluator = PgVectorEvaluator(model_name, k, conn)
        detail_frames, metrics = evaluator.run(selected_cats)

        # Save per-query detail CSV
        combined  = pd.concat(detail_frames, ignore_index=True)
        safe_name = model_name.replace("/", "_").replace("-", "_")
        out_path  = BASE_DIR / f"eval_results_{safe_name}_k{k}.csv"
        combined.to_csv(out_path, index=False)
        print(f"\nDetailed results → {out_path.name}")

        for m in metrics:
            all_summary_rows.append({
                "model":               m.model,
                "category":            m.category,
                "n_queries":           m.n_queries,
                f"precision@{k}":       m.precision,
                f"recall@{k}":          m.recall,
                "MRR":                 m.mrr,
                f"avg_strong_hits@{k}": m.avg_strong_hits,
                f"avg_weak_hits@{k}":   m.avg_weak_hits,
            })

    conn.close()

    # Summary table
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    summary_df = pd.DataFrame(all_summary_rows)
    print(summary_df.to_string(index=False))

    summary_path = BASE_DIR / f"eval_summary_k{k}.csv"
    if summary_path.exists():
        existing   = pd.read_csv(summary_path)
        existing   = existing[~existing["model"].isin(args.model)]
        summary_df = pd.concat([existing, summary_df], ignore_index=True)
    summary_df.to_csv(summary_path, index=False)
    print(f"\nSummary saved → {summary_path.name}")


if __name__ == "__main__":
    main()
