"""
evaluate_pgfts.py
=================

Full-text search baseline using standard PostgreSQL FTS with no domain
customisation.  Two configurations are supported:

    english (default)
        Porter stemmer + standard ~122-word English stoplist.
        Stopwords are dropped from both the document and the query; remaining
        terms are stemmed before matching.

    simple
        Lowercase only — no stemming, no stopword removal.
        Every token in the document and query is retained as-is (lowercased).
        This is the "basic FTS" baseline.

Query strategy (both configs):
    plainto_tsquery applies the chosen config to stem / normalise terms; all
    surviving terms are then OR-combined so that any match retrieves a document.
    ts_rank promotes documents that contain more of the query terms, giving
    TF-IDF-like ranking.  AND semantics (the plainto_tsquery default) would
    require every non-stopword token to appear simultaneously, making long
    natural-language queries return zero results.

Requires the tsvector columns and GIN indexes created by setup_schema.py:
    text_search_vector         ← english config
    text_search_vector_simple  ← simple config

Usage
-----
    # english config (default), all categories, k=5
    python pipeline/03_evaluate_embeddings/evaluate_pgfts.py

    # simple (basic) config
    python pipeline/03_evaluate_embeddings/evaluate_pgfts.py --config simple

    # specific categories or k
    python pipeline/03_evaluate_embeddings/evaluate_pgfts.py --category 1 2
    python pipeline/03_evaluate_embeddings/evaluate_pgfts.py --config simple --category 3 --k 10

Environment variables
---------------------
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_connection
from evaluate_fulltext import parse_uid_list

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT_PATHS = {
    1: EVAL_DIR / "category1_dataset.csv",
    2: EVAL_DIR / "category2_dataset.csv",
    3: EVAL_DIR / "category3_dataset.csv",
}

# Mapping from config name → pre-computed tsvector column
TS_COLUMNS = {
    "english": "text_search_vector",
    "simple":  "text_search_vector_simple",
}

TS_DESCRIPTIONS = {
    "english": "Porter stemmer + standard English stopwords (~122 words)",
    "simple":  "lowercase only — no stemming, no stopword removal",
}


# ---------------------------------------------------------------------------
# Metrics dataclass
# ---------------------------------------------------------------------------

@dataclass
class CategoryMetrics:
    category: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class PgFtsEvaluator:
    """
    Full-text search evaluator using a standard PostgreSQL text search config.

    Parameters
    ----------
    k      : number of results to retrieve per query
    config : 'english' or 'simple'
    conn   : open psycopg2 connection
    """

    def __init__(self, k: int, config: str, conn):
        if config not in TS_COLUMNS:
            raise ValueError(f"config must be one of {list(TS_COLUMNS)}, got {config!r}")
        self.k      = k
        self.config = config
        self.ts_col = TS_COLUMNS[config]
        self.conn   = conn
        self.cur    = conn.cursor()

    def _to_or_tsquery(self, query: str) -> str | None:
        """
        Convert a natural-language query to an OR tsquery.

        plainto_tsquery applies stemming and stopword removal for the chosen
        config; we then replace every & with | to get OR semantics.
        Returns None when the query reduces to nothing (e.g. all stopwords
        with the english config).
        """
        self.cur.execute(
            f"SELECT plainto_tsquery('{self.config}', %s)::text", (query,)
        )
        and_form = self.cur.fetchone()[0]
        if not and_form:
            return None
        return and_form.replace(" & ", " | ")

    def _search(self, query: str) -> list[str]:
        or_query = self._to_or_tsquery(query)
        if or_query is None:
            return []
        col = self.ts_col
        self.cur.execute(
            f"""
            SELECT recipe_uid
            FROM   recipes
            WHERE  {col} @@ to_tsquery('{self.config}', %s)
            ORDER  BY ts_rank({col}, to_tsquery('{self.config}', %s)) DESC, recipe_uid
            LIMIT  %s
            """,
            (or_query, or_query, self.k),
        )
        return [r[0] for r in self.cur.fetchall()]

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
        k       = self.k
        records = []
        skipped = 0
        no_hits = 0

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set   = set(parse_uid_list(row["weak_list"]))

            if not strong_set:
                skipped += 1
                continue

            retrieved = self._search(row["query"])
            if not retrieved:
                no_hits += 1

            records.append({
                "category":           category_name,
                "query_id":           row["query_id"],
                "query":              row["query"],
                "n_strong":           len(strong_set),
                "n_weak":             len(weak_set),
                f"precision@{k}":     self._precision_at_k(retrieved, strong_set, k),
                f"recall@{k}":        self._recall_at_k(retrieved, strong_set),
                "rr":                 self._reciprocal_rank(retrieved, strong_set),
                "strong_hits_top5":   sum(1 for u in retrieved[:k] if u in strong_set),
                "weak_hits_top5":     sum(1 for u in retrieved[:k] if u in weak_set),
                "n_retrieved":        len(retrieved),
                "retrieved":          ", ".join(retrieved),
                "strong_list":        ", ".join(sorted(strong_set)),
                "weak_list":          ", ".join(sorted(weak_set)),
            })

        if skipped:
            print(f"  Skipped {skipped} queries (empty strong list)")
        print(f"  Queries with 0 FTS hits: {no_hits}")
        return pd.DataFrame(records)

    # ── Full run ──────────────────────────────────────────────────────────────

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        k = self.k
        print(f"{'=' * 60}")
        print(f"PostgreSQL FTS  |  config={self.config}  |  query=plainto_tsquery→OR  |  k={k}")
        print(f"{TS_DESCRIPTIONS[self.config]}")
        print(f"{'=' * 60}")

        detail_frames: list[pd.DataFrame] = []
        metrics:       list[CategoryMetrics] = []

        for cat_name, df in category_dfs:
            print(f"\n── {cat_name} ──")
            results = self.evaluate_category(df, cat_name)
            detail_frames.append(results)

            p          = results[f"precision@{k}"].mean()
            r          = results[f"recall@{k}"].mean()
            mrr        = results["rr"].mean()
            avg_strong = results["strong_hits_top5"].mean()
            avg_weak   = results["weak_hits_top5"].mean()
            no_results = (results["n_retrieved"] == 0).sum()

            print(f"  Queries evaluated  : {len(results)}")
            print(f"  Queries with 0 hits: {no_results}")
            print(f"  Precision@{k}       : {p:.4f}")
            print(f"  Recall@{k}          : {r:.4f}")
            print(f"  MRR                : {mrr:.4f}")
            print(f"  Avg strong hits@{k} : {avg_strong:.4f}")
            print(f"  Avg weak hits@{k}   : {avg_weak:.4f}")

            metrics.append(CategoryMetrics(
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
        "--config", choices=["english", "simple"], default="english",
        help="PostgreSQL text search config (default: english). "
             "english: Porter stemmer + stopwords. "
             "simple: lowercase only, no stemming or stopwords.",
    )
    parser.add_argument(
        "--category", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3],
        help="Which eval categories to run (default: 1 2 3)",
    )
    parser.add_argument(
        "--k", type=int, default=5,
        help="Number of results to retrieve (default: 5)",
    )
    args = parser.parse_args()

    k = args.k
    selected_cats = [
        (f"Category {n}", pd.read_csv(CAT_PATHS[n]))
        for n in sorted(args.category)
    ]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    conn      = get_connection()
    evaluator = PgFtsEvaluator(k=k, config=args.config, conn=conn)
    detail_frames, metrics = evaluator.run(selected_cats)

    # Per-category detail CSVs
    for frame, (cat_name, _) in zip(detail_frames, selected_cats):
        cat_slug = cat_name.lower().replace(" ", "")
        out_path = BASE_DIR / f"pgfts_{args.config}_{cat_slug}_k{k}.csv"
        frame.to_csv(out_path, index=False)
        print(f"Detailed results → {out_path.name}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    model_key    = f"pgfts/{args.config}"
    summary_rows = [
        {
            "model":               model_key,
            "category":            m.category,
            "n_queries":           m.n_queries,
            f"precision@{k}":       m.precision,
            f"recall@{k}":          m.recall,
            "MRR":                 m.mrr,
            f"avg_strong_hits@{k}": m.avg_strong_hits,
            f"avg_weak_hits@{k}":   m.avg_weak_hits,
        }
        for m in metrics
    ]
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))

    summary_path = BASE_DIR / f"eval_summary_k{k}.csv"
    if summary_path.exists():
        existing   = pd.read_csv(summary_path)
        cats       = [m.category for m in metrics]
        existing   = existing[
            ~((existing["model"] == model_key) & (existing["category"].isin(cats)))
        ]
        summary_df = pd.concat([existing, summary_df], ignore_index=True)
    summary_df.to_csv(summary_path, index=False)
    print(f"\nSummary saved → {summary_path.name}")

    conn.close()


if __name__ == "__main__":
    main()
