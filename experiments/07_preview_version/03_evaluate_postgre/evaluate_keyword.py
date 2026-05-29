"""
evaluate_keyword.py
===================

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

Vocab tokens are split into two tiers by type:
    - underscore tokens : compound technical identifiers containing '_'
                          (e.g. workato_db_table, get_records). Precise and
                          unambiguous — safe to weight more heavily.
    - word tokens       : single-word app names (e.g. salesforce, snowflake).
                          Broader — used for scoring only, not strict filtering.

Search strategies (select with --strategy)
------------------------------------------
    and_or  (default)
        Two-pass fallback. First tries ILIKE AND across underscore tokens only
        (all must appear). If that returns nothing, falls back to ILIKE OR
        across all tokens (any must appear), ranked by match count.
        Queries with no vocab tokens return empty (no_vocab).

    weighted
        Single-pass unified scoring. WHERE clause is OR across all tokens so
        every partially-matching recipe is considered. Ranking uses a combined
        weighted score: each underscore token match = 3 points, each word token
        match = 1 point. Higher total score ranks first.

        Example (3 underscore + 2 word tokens in query):
            Recipe A matches 3 underscore              → score 9  → rank 1
            Recipe B matches 1 underscore + 2 word     → score 5  → rank 2
            Recipe C matches 2 word only               → score 2  → rank 3

        Caveat: enough word matches can outscore a single underscore match
        (e.g. 4 word tokens = 4 pts > 1 underscore = 3 pts).

    lexicographic
        Single-pass strict hierarchy. WHERE clause is OR across all tokens.
        Ranking uses two independent ORDER BY keys:
            1. underscore match count DESC  (primary)
            2. word match count DESC        (tiebreaker)
        Any recipe with ≥1 underscore match always outranks any recipe with
        zero underscore matches, regardless of word match counts.

        Example (same query as above):
            Recipe A: (underscore=3, word=0) → rank 1
            Recipe B: (underscore=1, word=2) → rank 2
            Recipe C: (underscore=0, word=2) → rank 3

If no vocab tokens are found in the query (e.g. pure business-language Cat 1
queries), all strategies return empty — the query is left for the embedding
model in a hybrid setup.

Usage
-----
    # All three categories, k=5, default strategy (and_or)
    python pipeline/03_evaluate_postgre/evaluate_fulltext.py

    # Weighted strategy
    python pipeline/03_evaluate_postgre/evaluate_fulltext.py --strategy weighted

    # Lexicographic strategy
    python pipeline/03_evaluate_postgre/evaluate_fulltext.py --strategy lexicographic

    # Combine with category / k flags
    python pipeline/03_evaluate_postgre/evaluate_fulltext.py --strategy weighted --category 2 3 --k 10

Output files are strategy-stamped (e.g. fts_category1_k5_weighted.csv) so
results from all three strategies can coexist and be compared in the shared
eval_summary_k{k}.csv.

Environment variables
---------------------
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clients import get_connection, parse_uid_list
from metrics import precision_at_k, recall_at_k, reciprocal_rank, write_summary

SEARCH_COLUMN = "text_no_comments"

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT_PATHS = {
    1: EVAL_DIR / "category1_dataset.csv",
    2: EVAL_DIR / "category2_dataset.csv",
    3: EVAL_DIR / "category3_dataset.csv",
}

_TOKEN_RE = re.compile(r'\b\w+(?:_\w+)*\b')


def _trigrams(s: str) -> set[str]:
    """Return the set of character trigrams for string s (padded with spaces)."""
    s = f" {s} "
    return {s[i:i+3] for i in range(len(s) - 2)}


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

    #: maps CLI strategy name → bound search method
    STRATEGIES = {
        "and_or":              "_search",
        "weighted":            "_search_weighted",
        "lexicographic":       "_search_lexicographic",
        "weighted_pgfts":      "_search_weighted_pgfts",
    }

    # Minimum ts_rank score for pgfts fallback results to be accepted.
    # Scores below this threshold are treated as noise (generic stem overlap)
    # and discarded. Calibrated from eval data:
    #   Cat 1 top-1 range: 0.012–0.055 (mostly noise)
    #   Cat 2 top-1 range: 0.024–0.068
    #   Cat 3 top-1 range: 0.035–0.086
    PGFTS_MIN_RANK = 0.03

    # Minimum query token length to attempt fuzzy correction.
    # Short tokens (< 5 chars) risk matching unrelated vocab terms at any threshold.
    FUZZY_MIN_LEN  = 5
    # Trigram similarity threshold for fuzzy vocab correction (0–1).
    # Empirical scores for typical typos (1–2 char errors):
    #   "saleforce"  vs "salesforce"  → 0.58
    #   "snowflaek"  vs "snowflake"   → 0.50
    #   "gogle"      vs "google"      → 0.57
    # Dangerous near-misses are blocked by FUZZY_MIN_LEN, not this threshold:
    #   "get"  (3 chars) → skipped by length guard
    #   "sale" (4 chars) → skipped by length guard
    # 0.7 is conservative — only catches very close matches (near-identical strings).
    FUZZY_THRESHOLD = 0.7

    def __init__(self, k: int, conn, strategy: str = "and_or", debug: bool = False):
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy {strategy!r}. Choose from: {list(self.STRATEGIES)}")
        self.k        = k
        self.conn     = conn
        self.cur      = conn.cursor()
        self.strategy = strategy
        self.debug    = debug
        self._search_fn = getattr(self, self.STRATEGIES[strategy])
        print("Building technical vocabulary from corpus ...", end=" ", flush=True)
        self._vocab = _build_tech_vocab(self.cur)
        self._vocab_trigrams = {term: _trigrams(term) for term in self._vocab}
        print(f"{len(self._vocab)} terms loaded.")

    # ── Vocabulary matching ───────────────────────────────────────────────────

    def _fuzzy_correct(self, token: str) -> str | None:
        """
        Attempt to fuzzy-correct a token that did not exactly match the vocab.

        Returns the closest vocab term if its trigram similarity exceeds
        FUZZY_THRESHOLD and the token meets FUZZY_MIN_LEN, otherwise None.

        Trigram similarity = |A ∩ B| / |A ∪ B| (Jaccard on trigram sets).
        Typical scores: ~0.58 for a 1-char typo, ~0.50 for a 2-char typo.
        See FUZZY_THRESHOLD for calibration details.
        """
        if len(token) < self.FUZZY_MIN_LEN:
            return None
        tok_tri  = _trigrams(token)
        best_sim = 0.0
        best_term = None
        for term, term_tri in self._vocab_trigrams.items():
            intersection = len(tok_tri & term_tri)
            if intersection == 0:
                continue
            sim = intersection / len(tok_tri | term_tri)
            if sim > best_sim:
                best_sim  = sim
                best_term = term
        if best_sim >= self.FUZZY_THRESHOLD:
            return best_term
        return None

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

        Tokens that do not exactly match the vocab are passed to _fuzzy_correct,
        which substitutes the closest vocab term if similarity >= FUZZY_THRESHOLD
        and the token is >= FUZZY_MIN_LEN chars. This makes the search robust to
        minor typos (e.g. "saleforce" → "salesforce", "snowflaek" → "snowflake").
        """
        seen         = set()
        underscore_t = []
        word_t       = []
        for raw in _TOKEN_RE.findall(query.lower()):
            t = raw
            if t not in self._vocab:
                corrected = self._fuzzy_correct(t)
                if corrected and self.debug:
                    print(f"    [fuzzy] {raw!r} → {corrected!r}")
                t = corrected or ""
            elif self.debug:
                print(f"    [exact] {raw!r}")
            if t and t not in seen:
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

    def _ilike_weighted(
        self,
        underscore_tokens: list[str],
        word_tokens: list[str],
        mode: str,
    ) -> list[str]:
        """
        Single-pass ILIKE search with multi-layer ranking.

        mode='weighted'      — Option A: underscore hits count as 3, word hits as 1.
                               ORDER BY combined weighted score DESC.
        mode='lexicographic' — Option B: ORDER BY (underscore_score DESC, word_score DESC).
                               Any underscore match strictly outranks any all-word match.

        WHERE clause is OR across all tokens so every partially-matching recipe
        is considered.
        """
        col        = SEARCH_COLUMN
        all_tokens = underscore_tokens + word_tokens
        all_ilike  = [f"%{t}%" for t in all_tokens]

        where = " OR ".join(f"{col} ILIKE %s" for _ in all_tokens)

        if mode == "weighted":
            UNDERSCORE_WEIGHT = 3
            WORD_WEIGHT       = 1
            u_expr = " + ".join(
                f"(CASE WHEN {col} ILIKE %s THEN {UNDERSCORE_WEIGHT} ELSE 0 END)"
                for _ in underscore_tokens
            )
            w_expr = " + ".join(
                f"(CASE WHEN {col} ILIKE %s THEN {WORD_WEIGHT} ELSE 0 END)"
                for _ in word_tokens
            )
            parts  = [e for e in (u_expr, w_expr) if e]
            score  = " + ".join(parts)
            order  = f"({score}) DESC"
            params = all_ilike + [f"%{t}%" for t in underscore_tokens] + [f"%{t}%" for t in word_tokens] + [self.k]
        else:  # lexicographic
            u_expr = (
                " + ".join(
                    f"(CASE WHEN {col} ILIKE %s THEN 1 ELSE 0 END)"
                    for _ in underscore_tokens
                )
                if underscore_tokens else "0::int"
            )
            w_expr = (
                " + ".join(
                    f"(CASE WHEN {col} ILIKE %s THEN 1 ELSE 0 END)"
                    for _ in word_tokens
                )
                if word_tokens else "0::int"
            )
            order  = f"({u_expr}) DESC, ({w_expr}) DESC"
            params = all_ilike + [f"%{t}%" for t in underscore_tokens] + [f"%{t}%" for t in word_tokens] + [self.k]

        self.cur.execute(
            f"""
            SELECT recipe_uid
            FROM   recipes
            WHERE  {where}
            ORDER  BY {order}, recipe_uid
            LIMIT  %s
            """,
            params,
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

    def _search_weighted(self, query: str) -> tuple[list[str], str]:
        """
        Option A — single-pass weighted scoring (underscore=3, word=1).
        Returns (recipe_uids, strategy_used).
        """
        underscore_tokens, word_tokens = self._extract_vocab_tokens(query)
        if not underscore_tokens and not word_tokens:
            return [], "no_vocab"
        results = self._ilike_weighted(underscore_tokens, word_tokens, mode="weighted")
        return results, "weighted"

    def _pgfts_fill(self, query: str, n: int, exclude: set[str]) -> list[str]:
        """
        Fetch up to n pgfts/english results not already in exclude, filtered
        by PGFTS_MIN_RANK. Returns an empty list if the tsquery is empty or
        no results clear the threshold.
        """
        self.cur.execute(
            "SELECT plainto_tsquery('english', %s)::text", (query,)
        )
        tsq_text = self.cur.fetchone()[0]
        if not tsq_text:
            return []
        tsq_or = tsq_text.replace(" & ", " | ")
        self.cur.execute(
            f"""
            SELECT recipe_uid
            FROM   recipes
            WHERE  text_search_vector @@ to_tsquery('english', %s)
              AND  ts_rank(text_search_vector, to_tsquery('english', %s)) >= %s
              AND  recipe_uid != ALL(%s)
            ORDER  BY ts_rank(text_search_vector, to_tsquery('english', %s)) DESC,
                      recipe_uid
            LIMIT  %s
            """,
            (tsq_or, tsq_or, self.PGFTS_MIN_RANK, list(exclude), tsq_or, n),
        )
        return [r[0] for r in self.cur.fetchall()]

    def _search_weighted_pgfts(self, query: str) -> tuple[list[str], str]:
        """
        Weighted ILIKE search (underscore=3, word=1) with pgfts/english fallback.

        Runs _search_weighted first. If fewer than k results are returned,
        fills remaining slots with pgfts/english results that clear
        PGFTS_MIN_RANK, deduped against already-retrieved UIDs.
        ILIKE results always occupy the top ranks.
        """
        underscore_tokens, word_tokens = self._extract_vocab_tokens(query)
        if not underscore_tokens and not word_tokens:
            # No vocab tokens — go straight to pgfts
            filled = self._pgfts_fill(query, self.k, exclude=set())
            return filled, "no_vocab+pgfts"

        results = self._ilike_weighted(underscore_tokens, word_tokens, mode="weighted")
        if len(results) < self.k:
            filled = self._pgfts_fill(query, self.k - len(results), exclude=set(results))
            results = results + filled
            return results, "weighted+pgfts"
        return results, "weighted"

    def _search_lexicographic(self, query: str) -> tuple[list[str], str]:
        """
        Option B — single-pass lexicographic ranking (underscore score first,
        word score as tiebreaker).
        Returns (recipe_uids, strategy_used).
        """
        underscore_tokens, word_tokens = self._extract_vocab_tokens(query)
        if not underscore_tokens and not word_tokens:
            return [], "no_vocab"
        results = self._ilike_weighted(underscore_tokens, word_tokens, mode="lexicographic")
        return results, "lexicographic"

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

            if self.debug:
                print(f"  query: {row['query']}")
            retrieved, strategy = self._search_fn(row["query"])
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

            records.append({
                "category":           category_name,
                "query_id":           row["query_id"],
                "query":              row["query"],
                "strategy":           strategy,
                "n_strong":           len(strong_set),
                "n_weak":             len(weak_set),
                f"precision@{k}":     precision_at_k(retrieved, strong_set, k),
                f"recall@{k}":        recall_at_k(retrieved, strong_set),
                "rr":                 reciprocal_rank(retrieved, strong_set),
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
        print(f"Keyword search  |  column={SEARCH_COLUMN}  |  vocab={len(self._vocab)} terms  |  k={k}  |  strategy={self.strategy}")

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
    parser.add_argument(
        "--strategy", choices=list(FullTextEvaluator.STRATEGIES), default="and_or",
        help="Search strategy: and_or (default), weighted (underscore=3/word=1), lexicographic",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print exact and fuzzy vocab matches for every query token",
    )
    args = parser.parse_args()

    k = args.k
    selected_cats = [
        (f"Category {n}", pd.read_csv(CAT_PATHS[n]))
        for n in sorted(args.category)
    ]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    conn      = get_connection()
    evaluator = FullTextEvaluator(k, conn, strategy=args.strategy, debug=args.debug)
    detail_frames, metrics = evaluator.run(selected_cats)

    # Per-category detail CSVs
    for frame, (cat_name, _) in zip(detail_frames, selected_cats):
        cat_slug = cat_name.lower().replace(" ", "")
        out_path = BASE_DIR / f"fts_{cat_slug}_k{k}_{args.strategy}.csv"
        frame.to_csv(out_path, index=False)
        print(f"Detailed results → {out_path.name}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    model_key   = f"keyword/ilike/{args.strategy}"
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
