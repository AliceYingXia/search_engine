"""
evaluate_full_text_search.py
===============

Full-text search baseline using OpenSearch against Category 1, 2, and 3
query sets.  Mirrors pipeline/03_evaluate_postgre/evaluate_fts.py but uses
OpenSearch instead of PostgreSQL tsvector + GIN.

Two configurations are supported:

    english (default)
        Uses the text_no_comments field with the custom english_underscore
        analyzer (standard tokenizer → word_delimiter_graph → lowercase →
        english stopwords → Porter stemmer).  Splits underscore-compound
        identifiers (e.g. workato_recipe_function → workato + recip + function)
        so that natural-language queries match technical identifiers in recipes.

    simple
        Uses the text_no_comments.simple sub-field (lowercase only, no stemming,
        no stopword removal).

Two scoring modes are supported via --scoring:

    bm25
        Standard BM25 match query with operator=or.  Rewards term frequency
        and penalizes long documents (partially).

    coverage
        Token coverage scoring: each unique query token that appears in a
        document contributes exactly 1 to the score, regardless of frequency
        or document length.  Implemented as a bool/should of constant_score
        term filters — one clause per token.  Mirrors Postgres ts_rank's
        lexeme-count behaviour and is length-blind by construction.

        Requires one extra analyze API call per query to tokenize the query
        string into the same token set used at index time.

Usage
-----
    python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py
    python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --scoring bm25
    python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --config simple
    python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --category 1 2
    python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --config simple --category 3 --k 10

Environment variables
---------------------
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from opensearchpy import ConnectionError, ConnectionTimeout, TransportError

from clients import get_client, parse_uid_list
from metrics import precision_at_k, recall_at_k, reciprocal_rank, write_summary

BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "02_synthesize_data"
CAT_PATHS = {
    1: EVAL_DIR / "category1_dataset.csv",
    2: EVAL_DIR / "category2_dataset.csv",
    3: EVAL_DIR / "category3_dataset.csv",
}

# Mapping from config name → OpenSearch field name
OS_FIELDS = {
    "english": "text_no_comments",
    "simple":  "text_no_comments.simple",
}

OS_DESCRIPTIONS = {
    ("english", "bm25"):      "english_underscore analyzer — BM25 ranking",
    ("english", "coverage"):  "english_underscore analyzer — token coverage scoring",
    ("simple",  "bm25"):      "simple analyzer — BM25 ranking",
    ("simple",  "coverage"):  "simple analyzer — token coverage scoring",
}

SEARCH_TIMEOUT_SECS = 5   # seconds — both HTTP and OpenSearch-side timeout
MAX_COVERAGE_TOKENS = 20  # cap for coverage token list; keep highest-IDF tokens


def _sort_by_informativeness(tokens: list[str]) -> list[str]:
    """Sort by IDF proxy: compound tokens (with _) first, then descending length.

    Compound tokens like workato_recipe_function are rare, domain-specific
    identifiers with high IDF.  Longer plain stems are rarer than short ones.
    Stop words are already removed by the analyzer before this is called.
    """
    return sorted(tokens, key=lambda t: (0 if "_" in t else 1, -len(t)))


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

class OsFtsEvaluator:
    """
    Full-text search evaluator using OpenSearch.

    Parameters
    ----------
    k       : number of results to retrieve per query
    config  : 'english' or 'simple'
    client  : OpenSearch client from clients.get_client()
    scoring : 'bm25' (default) or 'coverage'
    """

    # Analyzer name used by each config — must match the index mapping
    _ANALYZER = {
        "english": "english_underscore",
        "simple":  "simple",
    }

    def __init__(self, k: int, config: str, client, scoring: str = "bm25"):
        if config not in OS_FIELDS:
            raise ValueError(f"config must be one of {list(OS_FIELDS)}, got {config!r}")
        if scoring not in ("bm25", "coverage"):
            raise ValueError(f"scoring must be 'bm25' or 'coverage', got {scoring!r}")
        self.k        = k
        self.config   = config
        self.scoring  = scoring
        self.field    = OS_FIELDS[config]
        self.analyzer = self._ANALYZER[config]
        self.client   = client

    def _tokenize(self, query: str) -> list[str]:
        """Tokenize query using the same analyzer as the index field."""
        resp = self.client.indices.analyze(
            index="recipes",
            body={"analyzer": self.analyzer, "text": query},
        )
        # Deduplicate while preserving order
        seen, tokens = set(), []
        for t in resp["tokens"]:
            if t["token"] not in seen:
                seen.add(t["token"])
                tokens.append(t["token"])
        return tokens

    def _search(self, query: str) -> list[str]:
        if self.scoring == "coverage":
            return self._search_coverage(query)
        return self._search_bm25(query)

    def _search_bm25(self, query: str) -> list[str]:
        body = {
            "query": {
                "match": {
                    self.field: {
                        "query":    query,
                        "operator": "or",
                    }
                }
            },
            "size":    self.k,
            "_source": False,
            "timeout": f"{SEARCH_TIMEOUT_SECS}s",
        }
        try:
            resp = self.client.search(
                index="recipes", body=body,
                request_timeout=SEARCH_TIMEOUT_SECS,
            )
        except ConnectionTimeout:
            print(f"  [timeout] query={query[:60]!r}")
            return []
        except ConnectionError as exc:
            print(f"  [connection error] {exc}")
            return []
        except TransportError as exc:
            print(f"  [transport error] status={exc.status_code} {exc.error}")
            return []
        if resp.get("timed_out"):
            print(f"  [timed_out] query={query[:60]!r}")
            return []
        return [hit["_id"] for hit in resp["hits"]["hits"]]

    def _search_coverage(self, query: str) -> list[str]:
        """
        Token coverage scoring: each unique query token that appears in the
        document contributes exactly 1 to the score.  Implemented as a
        bool/should of constant_score term filters — length-blind by design.

        For long queries, tokens are sorted by IDF proxy (compound identifiers
        first, then descending length) and capped at MAX_COVERAGE_TOKENS so
        that common short stems don't inflate the clause count.
        """
        tokens = self._tokenize(query)
        if not tokens:
            return []
        if len(tokens) > MAX_COVERAGE_TOKENS:
            tokens = _sort_by_informativeness(tokens)[:MAX_COVERAGE_TOKENS]
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"constant_score": {
                            "filter": {"term": {self.field: t}},
                            "boost":  1,
                        }}
                        for t in tokens
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size":    self.k,
            "_source": False,
            "timeout": f"{SEARCH_TIMEOUT_SECS}s",
        }
        try:
            resp = self.client.search(
                index="recipes", body=body,
                request_timeout=SEARCH_TIMEOUT_SECS,
            )
        except ConnectionTimeout:
            print(f"  [timeout] query={query[:60]!r}")
            return []
        except ConnectionError as exc:
            print(f"  [connection error] {exc}")
            return []
        except TransportError as exc:
            print(f"  [transport error] status={exc.status_code} {exc.error}")
            return []
        if resp.get("timed_out"):
            print(f"  [timed_out] query={query[:60]!r}")
            return []
        return [hit["_id"] for hit in resp["hits"]["hits"]]

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
        print(f"  Queries with 0 BM25 hits: {no_hits}")
        return pd.DataFrame(records)

    # ── Full run ──────────────────────────────────────────────────────────────

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        k = self.k
        print(f"{'=' * 60}")
        print(f"OpenSearch FTS  |  config={self.config}  |  scoring={self.scoring}  |  k={k}")
        print(f"{OS_DESCRIPTIONS[(self.config, self.scoring)]}")
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
    )
    parser.add_argument(
        "--category", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3],
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--scoring", choices=["bm25", "coverage"], default="bm25",
        help="bm25 (default): standard BM25 match. coverage: token coverage scoring.",
    )
    args = parser.parse_args()

    k = args.k
    selected_cats = [
        (f"Category {n}", pd.read_csv(CAT_PATHS[n]))
        for n in sorted(args.category)
    ]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    client    = get_client()
    evaluator = OsFtsEvaluator(k=k, config=args.config, client=client, scoring=args.scoring)
    detail_frames, metrics = evaluator.run(selected_cats)

    # Per-category detail CSVs
    for frame, (cat_name, _) in zip(detail_frames, selected_cats):
        cat_slug = cat_name.lower().replace(" ", "")
        out_path = BASE_DIR / f"os_fts_{args.config}_{args.scoring}_{cat_slug}_k{k}.csv"
        frame.to_csv(out_path, index=False)
        print(f"Detailed results → {out_path.name}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    model_key   = f"os/fts/{args.config}/{args.scoring}"
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


if __name__ == "__main__":
    main()
