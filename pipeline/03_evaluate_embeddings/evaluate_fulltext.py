"""
evaluate_fulltext.py
====================

Keyword search baseline using vocabulary-driven ILIKE matching against
Category 1, 2, and 3 query sets.

How it works
------------
At startup, a technical vocabulary is built from the recipe corpus:
    - Connector names      (e.g. salesforce, workato_db_table, google_sheets)
    - Action names         (e.g. get_records, __adhoc_http_action)
    - Field names >= 8 chars (e.g. table_id, continuation_token)
    - Sub-words from compound connector names (e.g. google from google_sheets,
      amazon from amazon_s3) — alphabetic parts >= 5 chars that appear in
      fewer than half the recipes (filters out noise like workato, connector)

Any query token that matches the vocabulary becomes an ILIKE condition.
This is automatic keyword extraction — no hand-crafted rules or stopword lists.

Search strategy (first non-empty result wins)
---------------------------------------------
    1. ILIKE AND — all underscore tokens from the query that exist in the vocab
                   must appear in the recipe text, ranked by number of matches.
                   Underscore tokens only (e.g. workato_db_table, get_records)
                   because single-word tokens are too broad for AND filtering.
    2. ILIKE OR  — any vocab token (underscore or single-word app names like
                   salesforce, snowflake) must appear, ranked by match count.

If no vocab tokens are found in the query (e.g. pure business-language Cat 1
queries), both passes return empty — the query is left for the embedding model
in a hybrid setup.

Usage
-----
    # All three categories, k=5 (default)
    python pipeline/03_evaluate_embeddings/evaluate_fulltext.py

    # Specific categories or k
    python pipeline/03_evaluate_embeddings/evaluate_fulltext.py --category 1 2
    python pipeline/03_evaluate_embeddings/evaluate_fulltext.py --category 3 --k 10

Environment variables
---------------------
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_connection

SEARCH_COLUMN = "text_no_comments"

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT_PATHS = {
    1: EVAL_DIR / "category1_dataset.csv",
    2: EVAL_DIR / "category2_dataset.csv",
    3: EVAL_DIR / "category3_dataset.csv",
}

_TOKEN_RE = re.compile(r'\b\w+(?:_\w+)*\b')


# ---------------------------------------------------------------------------
# Corpus vocabulary
# ---------------------------------------------------------------------------

def _build_tech_vocab(cur) -> set[str]:
    """
    Build a technical vocabulary from the recipe corpus. All terms lowercase.

    Sources:
      1. Connector names (from the connectors column)
      2. Action names (parsed from 'action: X / Y' lines in text_no_comments)
      3. Field names >= 8 chars (parsed from 'fields: ...' lines)
      4. Alphabetic sub-words >= 5 chars from compound connector names,
         excluding sub-words that appear in >= 50% of recipes (noise filter)
    """
    # ── Connectors ────────────────────────────────────────────────────────────
    cur.execute("""
        SELECT DISTINCT unnest(string_to_array(connectors, ', '))
        FROM recipes WHERE connectors IS NOT NULL
    """)
    connector_tokens = [r[0].lower() for r in cur.fetchall()]
    connector_set = set(connector_tokens)

    # ── Sub-words from compound connector names ────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM recipes")
    total_recipes = cur.fetchone()[0]
    threshold = total_recipes * 0.5   # sub-word must appear in < 50% of recipes

    subwords = set()
    for token in connector_tokens:
        if '_' not in token:
            continue
        for part in token.split('_'):
            if part.isalpha() and len(part) >= 5:
                # Check how many recipes contain this sub-word
                cur.execute(
                    f"SELECT COUNT(*) FROM recipes WHERE {SEARCH_COLUMN} ILIKE %s",
                    (f"%{part}%",)
                )
                count = cur.fetchone()[0]
                if count < threshold:
                    subwords.add(part)

    # ── Actions and fields ────────────────────────────────────────────────────
    cur.execute(f"SELECT {SEARCH_COLUMN} FROM recipes")
    # Match both trigger (0-space indent) and action (2-space indent) lines
    action_re = re.compile(r'(?:trigger|action): \S+ / (\S+)')
    field_re  = re.compile(r'^\s+fields: (.+)$', re.MULTILINE)

    actions = set()
    fields  = set()
    for (text,) in cur.fetchall():
        if not text:
            continue
        for m in action_re.finditer(text):
            actions.add(m.group(1).lower())
        for m in field_re.finditer(text):
            for f in m.group(1).split(','):
                f = f.strip().lower()
                if len(f) >= 8:
                    fields.add(f)

    vocab = connector_set | subwords | actions | fields
    return vocab


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
    category: str
    n_queries: int
    precision: float
    recall: float
    mrr: float
    avg_strong_hits: float
    avg_weak_hits: float


class FullTextEvaluator:
    """
    Keyword search evaluator using vocabulary-driven ILIKE matching.

    Parameters
    ----------
    k    : number of results to retrieve per query
    conn : open psycopg2 connection
    """

    def __init__(self, k: int, conn):
        self.k   = k
        self.conn = conn
        self.cur  = conn.cursor()
        print("Building technical vocabulary from corpus ...", end=" ", flush=True)
        self._vocab = _build_tech_vocab(self.cur)
        print(f"{len(self._vocab)} terms loaded.")

    # ── Vocabulary matching ───────────────────────────────────────────────────

    def _extract_vocab_tokens(self, query: str) -> tuple[list[str], list[str]]:
        """
        Tokenise the query and split matched vocab tokens into two groups:

        - underscore_tokens : tokens containing '_' — specific technical
          identifiers (connector names, action names, field names) that cannot
          be confused with ordinary English words. Used for AND filtering.

        - word_tokens : single-word matches (app names like salesforce,
          snowflake, google). Used for OR scoring only, as they are too broad
          to AND-filter without excluding the right recipe.

        Both lists are order-preserving and deduplicated.
        """
        seen         = set()
        underscore_t = []
        word_t       = []
        for t in _TOKEN_RE.findall(query.lower()):
            if t in self._vocab and t not in seen:
                seen.add(t)
                (underscore_t if '_' in t else word_t).append(t)
        return underscore_t, word_t

    # ── ILIKE search ─────────────────────────────────────────────────────────

    def _ilike_scored(self, tokens: list[str], require_all: bool) -> list[str]:
        """
        ILIKE search ranked by number of token matches.

        require_all=True  → AND filter (all tokens must appear)
        require_all=False → OR filter (any token must appear)
        """
        col        = SEARCH_COLUMN
        ilike      = [f"%{t}%" for t in tokens]
        score_expr = " + ".join(
            f"(CASE WHEN {col} ILIKE %s THEN 1 ELSE 0 END)" for _ in tokens
        )
        if require_all:
            where = " AND ".join(f"{col} ILIKE %s" for _ in tokens)
        else:
            where = " OR ".join(f"{col} ILIKE %s" for _ in tokens)
        self.cur.execute(
            f"""
            SELECT recipe_uid
            FROM   recipes
            WHERE  {where}
            ORDER  BY ({score_expr}) DESC, recipe_uid
            LIMIT  %s
            """,
            ilike + ilike + [self.k],
        )
        return [r[0] for r in self.cur.fetchall()]

    def _search(self, query: str) -> tuple[list[str], str]:
        """
        Returns (recipe_uids, strategy_used).

        Strategy 1 — ILIKE AND: all underscore vocab tokens must appear,
                                 ranked by match score
        Strategy 2 — ILIKE OR:  any vocab token (underscore or word) appears,
                                 ranked by match score
        Strategy 0 — no_vocab:  query contains no technical vocabulary tokens
        """
        underscore_tokens, word_tokens = self._extract_vocab_tokens(query)
        all_tokens = underscore_tokens + word_tokens

        if not all_tokens:
            return [], "no_vocab"

        if underscore_tokens:
            results = self._ilike_scored(underscore_tokens, require_all=True)
            if results:
                return results, "AND"

        results = self._ilike_scored(all_tokens, require_all=False)
        return results, "OR"

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
        k               = self.k
        records         = []
        skipped         = 0
        strategy_counts: dict[str, int] = {}

        for _, row in df.iterrows():
            strong_set = set(parse_uid_list(row["strong_list"]))
            weak_set   = set(parse_uid_list(row["weak_list"]))

            if not strong_set:
                skipped += 1
                continue

            retrieved, strategy = self._search(row["query"])
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

            records.append({
                "category":           category_name,
                "query_id":           row["query_id"],
                "query":              row["query"],
                "strategy":           strategy,
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
        print(f"  Strategy used: {strategy_counts}")
        return pd.DataFrame(records)

    # ── Full run ──────────────────────────────────────────────────────────────

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        k = self.k
        print(f"{'=' * 60}")
        print(f"Keyword search  |  column={SEARCH_COLUMN}  |  vocab={len(self._vocab)} terms  |  k={k}")
        print(f"Strategy: ILIKE AND → ILIKE OR")

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
    evaluator = FullTextEvaluator(k, conn)
    detail_frames, metrics = evaluator.run(selected_cats)

    # Per-category detail CSVs
    for frame, (cat_name, _) in zip(detail_frames, selected_cats):
        cat_slug = cat_name.lower().replace(" ", "")
        out_path = BASE_DIR / f"fts_{cat_slug}_k{k}.csv"
        frame.to_csv(out_path, index=False)
        print(f"Detailed results → {out_path.name}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    model_key   = "keyword/ilike"
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
