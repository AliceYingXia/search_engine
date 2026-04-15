"""
evaluate_hybrid.py
==================

Hybrid search combining Qwen3-Embedding-8B+instruct (dense) and vocabulary-
driven ILIKE keyword search, evaluated against Category 1, 2, and 3 query sets.

Modes
-----
    fuse  (default)
        Both systems always run. Results merged with weighted Reciprocal Rank
        Fusion (RRF). Weights are determined by query type signal:

            underscore tokens found → w_kw=2.0, w_emb=1.0  (keyword wins on exact lookup)
            word tokens only        → w_kw=1.0, w_emb=2.0  (Qwen wins on feature queries)
            no vocab tokens         → w_kw=0.0, w_emb=1.0  (keyword returns nothing → pure Qwen)

        RRF formula:
            score(doc) = w_kw * 1/(RRF_K + rank_kw) + w_emb * 1/(RRF_K + rank_emb)

        Documents in only one list naturally get 0 contribution from the other.
        Each system retrieves k*3 candidates before fusion, then top-k is returned.

    fts-fuse
        Same vocab-based weight signal as fuse, but the keyword leg is replaced
        by PostgreSQL FTS (english config: Porter stemmer + stopword removal).
        This lets stemming broaden FTS recall (e.g. "running" matches "run")
        while the weight signal still determines how much to trust FTS vs dense:

            underscore tokens found → w_fts=2.0, w_emb=1.0
            word tokens only        → w_fts=1.0, w_emb=2.0
            no vocab tokens         → w_fts=0.0, w_emb=1.0  (pure Qwen)

        The FTS query uses plainto_tsquery('english') → OR semantics so that
        any surviving stem matches a document (same as evaluate_pgfts.py).

    weighted-pgfts-fuse
        Same vocab-based weight signal as fuse, but the keyword leg is replaced
        by weighted_pgfts (weighted ILIKE with a pgfts/english gap-fill fallback).
        The keyword leg runs weighted ILIKE first (underscore=3, word=1 scoring);
        if it returns fewer than k*3 candidates the remaining slots are filled by
        pgfts/english results that clear the ts_rank ≥ 0.03 threshold. This adds
        robustness to newly added connectors not yet in the vocabulary while still
        prioritising precise ILIKE matches.

            underscore tokens found → w_kw=2.0, w_emb=1.0
            word tokens only        → w_kw=1.0, w_emb=2.0
            no vocab tokens         → w_kw=0.0, w_emb=1.0  (pure Qwen)

        The kw_strategy field in the detail CSV records which path fired per query:
            "weighted"       — ILIKE saturated k*3 slots, no fallback needed
            "weighted+pgfts" — ILIKE returned < k*3; pgfts filled the gap
            "no_vocab+pgfts" — no vocab tokens; all keyword candidates from pgfts

    route
        Hard routing — only one system handles the query:
            underscore tokens found → keyword search only
            otherwise              → Qwen only

Usage
-----
    # fuse mode (default), all categories, k=5
    python pipeline/03_evaluate_postgre/evaluate_hybrid.py

    # fts-fuse mode
    python pipeline/03_evaluate_postgre/evaluate_hybrid.py --mode fts-fuse

    # weighted-pgfts-fuse mode (weighted ILIKE + pgfts fallback + dense)
    python pipeline/03_evaluate_postgre/evaluate_hybrid.py --mode weighted-pgfts-fuse

    # route mode
    python pipeline/03_evaluate_postgre/evaluate_hybrid.py --mode route

    # specific categories or k
    python pipeline/03_evaluate_postgre/evaluate_hybrid.py --category 1 2 --k 10

Environment variables
---------------------
    BASETEN_API_KEY                  — Qwen3-Embedding-8B+instruct (Baseten)
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_connection, parse_uid_list
from evaluate_keyword import FullTextEvaluator
from metrics import precision_at_k, recall_at_k, reciprocal_rank, write_summary
from models import EmbeddingModel

EMBED_MODEL = "Qwen/Qwen3-Embedding-8B+instruct"
RRF_K       = 60    # standard RRF constant

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT_PATHS = {
    1: EVAL_DIR / "category1_dataset.csv",
    2: EVAL_DIR / "category2_dataset.csv",
    3: EVAL_DIR / "category3_dataset.csv",
}


# ---------------------------------------------------------------------------
# Metrics dataclass
# ---------------------------------------------------------------------------

@dataclass
class CategoryMetrics:
    category: str
    mode: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float


# ---------------------------------------------------------------------------
# Hybrid evaluator
# ---------------------------------------------------------------------------

class HybridEvaluator:
    """
    Combines Qwen3-Embedding-8B+instruct dense search with vocabulary-driven
    ILIKE keyword search.

    Parameters
    ----------
    k    : number of results to return per query
    mode : 'fuse' or 'route'
    conn : open psycopg2 connection
    """

    def __init__(self, k: int, mode: str, conn):
        self.k    = k
        self.mode = mode
        self.conn = conn
        self.cur  = conn.cursor()

        # Keyword search (also owns the corpus vocabulary)
        self.kw = FullTextEvaluator(k=k * 3, conn=conn)

        # Dense embedding model
        print(f"Loading embedding model: {EMBED_MODEL}")
        self.model = EmbeddingModel(EMBED_MODEL)

    # ── FTS search (english: Porter stemmer + stopword removal) ──────────────

    def _fts_search(self, query: str, k: int) -> list[str]:
        """
        PostgreSQL FTS using the 'english' config.

        plainto_tsquery('english') applies Porter stemming and the standard
        ~122-word English stoplist to both the query and the indexed documents.
        AND semantics are converted to OR so that natural-language queries with
        multiple terms are not silently filtered to zero results.
        """
        self.cur.execute(
            "SELECT plainto_tsquery('english', %s)::text", (query,)
        )
        and_form = self.cur.fetchone()[0]
        if not and_form:
            return []
        or_query = and_form.replace(" & ", " | ")
        self.cur.execute(
            """
            SELECT recipe_uid
            FROM   recipes
            WHERE  text_search_vector @@ to_tsquery('english', %s)
            ORDER  BY ts_rank(text_search_vector, to_tsquery('english', %s)) DESC,
                      recipe_uid
            LIMIT  %s
            """,
            (or_query, or_query, k),
        )
        return [r[0] for r in self.cur.fetchall()]

    # ── pgvector search ───────────────────────────────────────────────────────

    def _embed_search(self, embedding: list[float], k: int) -> list[str]:
        vec_str = "[" + ",".join(map(str, embedding)) + "]"
        self.cur.execute(
            f"""
            SELECT r.recipe_uid
            FROM   {self.model.table} e
            JOIN   recipes r USING (recipe_uid)
            ORDER  BY e.embedding <=> %s::vector
            LIMIT  %s
            """,
            (vec_str, k),
        )
        return [row[0] for row in self.cur.fetchall()]

    # ── RRF fusion ────────────────────────────────────────────────────────────

    @staticmethod
    def _rrf(ranked_lists: list[tuple[list[str], float]]) -> list[str]:
        """
        Weighted RRF over multiple ranked lists.

        ranked_lists : list of (recipe_uid_list, weight) pairs
        Returns      : recipe_uids ordered by descending RRF score
        """
        scores: dict[str, float] = defaultdict(float)
        for uid_list, weight in ranked_lists:
            for rank, uid in enumerate(uid_list, 1):
                scores[uid] += weight * (1.0 / (RRF_K + rank))
        return sorted(scores, key=lambda u: scores[u], reverse=True)

    # ── Query routing / weight assignment ─────────────────────────────────────

    def _query_signal(self, query: str) -> tuple[list[str], list[str], str]:
        """
        Returns (underscore_tokens, word_tokens, signal_label).
        signal_label: 'underscore' | 'word' | 'no_vocab'
        """
        underscore_t, word_t = self.kw._extract_vocab_tokens(query)
        if underscore_t:
            return underscore_t, word_t, "underscore"
        if word_t:
            return underscore_t, word_t, "word"
        return underscore_t, word_t, "no_vocab"

    def _weights(self, signal: str) -> tuple[float, float]:
        """Return (w_kw, w_emb) for the given signal label."""
        return {
            "underscore": (2.0, 1.0),
            "word":       (1.0, 2.0),
            "no_vocab":   (0.0, 1.0),
        }[signal]

    # ── Single-query search ───────────────────────────────────────────────────

    def _search(self, query: str, embedding: list[float]) -> tuple[list[str], dict]:
        """
        Returns (recipe_uids, detail_dict).
        detail_dict contains per-query diagnostic fields added to the CSV.
        """
        _, _, signal = self._query_signal(query)
        w_kw, w_emb  = self._weights(signal)

        k_wide = self.k * 3   # wider net before fusion

        if self.mode == "route":
            if signal == "underscore":
                kw_results, kw_strat = self.kw._search(query)
                results = kw_results[:self.k]
                detail  = {"signal": signal, "mode_used": "keyword",
                           "kw_strategy": kw_strat, "n_kw": len(kw_results), "n_emb": 0}
            else:
                emb_results = self._embed_search(embedding, self.k)
                results = emb_results
                detail  = {"signal": signal, "mode_used": "embed",
                           "kw_strategy": "—", "n_kw": 0, "n_emb": len(emb_results)}
            return results, detail

        # fts-fuse mode — FTS/english leg instead of ILIKE keyword
        if self.mode == "fts-fuse":
            fts_results = self._fts_search(query, k_wide)
            emb_results = self._embed_search(embedding, k_wide)

            fused = self._rrf([
                (fts_results, w_kw),
                (emb_results, w_emb),
            ])[:self.k]

            detail = {
                "signal":    signal,
                "mode_used": f"fts-fuse(w_fts={w_kw},w_emb={w_emb})",
                "n_fts":     len(fts_results),
                "n_emb":     len(emb_results),
                "w_fts":     w_kw,
                "w_emb":     w_emb,
            }
            return fused, detail

        # weighted-pgfts-fuse mode — weighted ILIKE + pgfts fallback leg
        if self.mode == "weighted-pgfts-fuse":
            kw_results, kw_strat = self.kw._search_weighted_pgfts(query)
            kw_results  = kw_results[:k_wide]
            emb_results = self._embed_search(embedding, k_wide)

            fused = self._rrf([
                (kw_results,  w_kw),
                (emb_results, w_emb),
            ])[:self.k]

            detail = {
                "signal":      signal,
                "mode_used":   f"weighted-pgfts-fuse(w_kw={w_kw},w_emb={w_emb})",
                "kw_strategy": kw_strat,
                "n_kw":        len(kw_results),
                "n_emb":       len(emb_results),
                "w_kw":        w_kw,
                "w_emb":       w_emb,
            }
            return fused, detail

        # fuse mode — ILIKE keyword leg
        kw_results, kw_strat = self.kw._search(query)
        kw_results  = kw_results[:k_wide]
        emb_results = self._embed_search(embedding, k_wide)

        fused = self._rrf([
            (kw_results,  w_kw),
            (emb_results, w_emb),
        ])[:self.k]

        detail = {
            "signal":      signal,
            "mode_used":   f"fuse(w_kw={w_kw},w_emb={w_emb})",
            "kw_strategy": kw_strat,
            "n_kw":        len(kw_results),
            "n_emb":       len(emb_results),
            "w_kw":        w_kw,
            "w_emb":       w_emb,
        }
        return fused, detail

    # ── Per-category evaluation ───────────────────────────────────────────────

    def evaluate_category(self, df: pd.DataFrame, category_name: str) -> pd.DataFrame:
        k       = self.k
        records = []
        skipped = 0
        signal_counts: dict[str, int] = {}

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set   = set(parse_uid_list(row["weak_list"]))

            if not strong_set:
                skipped += 1
                continue

            _, _, signal = self._query_signal(row["query"])
            # In route mode, skip embedding when query will be handled by keyword
            if self.mode == "route" and signal == "underscore":
                embedding = []
            else:
                embedding = self.model.embed_query(row["query"])
            retrieved, detail = self._search(row["query"], embedding)

            sig = detail["signal"]
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

            records.append({
                "category":           category_name,
                "query_id":           row["query_id"],
                "query":              row["query"],
                **detail,
                "n_strong":           len(strong_set),
                "n_weak":             len(weak_set),
                f"precision@{k}":     precision_at_k(retrieved, strong_set, k),
                f"recall@{k}":        recall_at_k(retrieved, strong_set),
                "rr":                 reciprocal_rank(retrieved, strong_set),
                "strong_hits_top5":   sum(1 for u in retrieved[:k] if u in strong_set),
                "weak_hits_top5":     sum(1 for u in retrieved[:k] if u in weak_set),
                "retrieved":          ", ".join(retrieved),
                "strong_list":        ", ".join(sorted(strong_set)),
                "weak_list":          ", ".join(sorted(weak_set)),
            })

        if skipped:
            print(f"  Skipped {skipped} queries (empty strong list)")
        print(f"  Signal breakdown: {signal_counts}")
        return pd.DataFrame(records)

    # ── Full run ──────────────────────────────────────────────────────────────

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        k = self.k
        print(f"{'=' * 60}")
        print(f"Hybrid search  |  mode={self.mode}  |  embed={EMBED_MODEL}  |  k={k}")
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

            print(f"  Queries evaluated  : {len(results)}")
            print(f"  Precision@{k}       : {p:.4f}")
            print(f"  Recall@{k}          : {r:.4f}")
            print(f"  MRR                : {mrr:.4f}")
            print(f"  Avg strong hits@{k} : {avg_strong:.4f}")
            print(f"  Avg weak hits@{k}   : {avg_weak:.4f}")

            metrics.append(CategoryMetrics(
                category        = cat_name,
                mode            = self.mode,
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
        "--mode", choices=["fuse", "fts-fuse", "weighted-pgfts-fuse", "route"], default="fuse",
        help=(
            "fuse: weighted RRF of keyword + dense (default). "
            "fts-fuse: weighted RRF of FTS/english + dense. "
            "weighted-pgfts-fuse: weighted RRF of weighted_pgfts (ILIKE + pgfts fallback) + dense. "
            "route: hard routing."
        ),
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
    evaluator = HybridEvaluator(k=k, mode=args.mode, conn=conn)
    detail_frames, metrics = evaluator.run(selected_cats)

    # Per-mode combined detail CSV
    combined  = pd.concat(detail_frames, ignore_index=True)
    out_path  = BASE_DIR / f"hybrid_{args.mode}_k{k}.csv"
    combined.to_csv(out_path, index=False)
    print(f"\nDetailed results → {out_path.name}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    model_key    = f"hybrid/qwen3-8b+instruct/{args.mode}"
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

    write_summary(
        BASE_DIR / f"eval_summary_k{k}.csv",
        summary_df,
        model_key,
        categories=[m.category for m in metrics],
    )

    conn.close()


if __name__ == "__main__":
    main()
