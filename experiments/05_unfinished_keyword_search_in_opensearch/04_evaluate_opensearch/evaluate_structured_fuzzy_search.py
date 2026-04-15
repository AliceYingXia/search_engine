"""
evaluate_structured_fuzzy_search.py
===================

Keyword search using OpenSearch native fuzzy matching across four structured
fields extracted from each recipe:

    connectors      — app names (e.g. salesforce, workato_db_table)
    actions         — provider/action pairs (e.g. salesforce/search_records)
    input_fields    — input field keys configured in actions (e.g. table_id)
    datapill_fields — output schema field names produced by steps (e.g. records)

All four fields are indexed with the keyword_split analyzer which splits on
underscores and slashes then lowercases, so:
    workato_recipe_function → [workato, recipe, function]
    salesforce/search_records → [salesforce, search, records]

At query time, each token from the user query is normalized and alias-expanded,
then matched against the four structured fields using OpenSearch fuzzy
matching. This script intentionally uses one fixed balanced mode only:
aliases + exact-first boosts + phrase-pair boosts + token gating.

No Python vocabulary — fuzzy correction and index lookup run entirely inside
OpenSearch. Query fan-out is bounded with token caps, per-field fuzzy settings,
and token-shape gating, but production-scale latency should still be validated
with load testing.

Usage
-----
    python pipeline/04_evaluate_opensearch/evaluate_structured_fuzzy_search.py
    python pipeline/04_evaluate_opensearch/evaluate_structured_fuzzy_search.py --k 10

Environment variables
---------------------
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import argparse
import json
import re
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

# Tokenises the query into words and underscore-compound tokens.
# "find salesforce records with table_id" → ["find","salesforce","records","with","table_id"]
_TOKEN_RE = re.compile(r'\b\w+(?:_\w+)*\b')

CONFIG_PATH = BASE_DIR / "structured_fuzzy_config.json"
CONFIG = json.loads(CONFIG_PATH.read_text())

# Alias / abbreviation normalization for structured search.
# All targets should map to canonical connector names already present in the
# corpus. Multi-word aliases are applied with boundary-aware regexes.
ALIASES: dict[str, str] = CONFIG["aliases"]
PHRASE_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((src, dst) for src, dst in CONFIG["phrase_aliases"].items()),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)
PHRASE_ALIAS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (
        re.compile(rf"(?<!\w){re.escape(src)}(?!\w)"),
        dst,
    )
    for src, dst in PHRASE_ALIASES
)

# English stop words stripped from queries before matching.
# These are generic words that appear in natural-language Category-1 queries
# ("how", "we", "the", …) but have no useful signal against technical field
# names.  Leaving them in causes hub recipes with hundreds of datapill_fields
# to accumulate spurious match scores on incidental lexical overlaps.
_STOP_WORDS: frozenset[str] = frozenset(CONFIG["stop_words"])

# Field boosts: connectors > actions > input fields ≈ datapill fields.
# Connectors and actions are more specific identifiers so they rank higher.
FIELD_BOOSTS = CONFIG["field_boosts"]
RAW_FIELDS = CONFIG["raw_field_boosts"]

# fuzziness: "AUTO" = edit distance 0 for 1-2 chars, 1 for 3-5, 2 for 6+
FUZZINESS = "AUTO"

# Per-field fuzzy parameters tuned to each field's dictionary size.
# Larger dictionaries need tighter constraints to bound the Levenshtein
# automaton fan-out at query time:
#   max_expansions — caps candidate terms collected per clause
#   prefix_length  — chars that must match exactly before fuzzy begins;
#                    higher values shrink the search space significantly.
#
# Measured cardinalities (unique terms in the index):
#   connectors      ~288   — small, generous settings safe
#   actions         ~888   — small, generous settings safe
#   input_fields    ~1,377 — moderate, slightly tighter
#   datapill_fields ~17,905 — large, must be kept tight
FUZZY_PARAMS: dict[str, dict] = CONFIG["fuzzy_params"]

# Minimum number of distinct query tokens that must match a recipe.
# Setting this to 2 prevents hub recipes with hundreds of datapill_fields
# from ranking first by matching a single incidental token (e.g. "data",
# "send") across their vast vocabulary.  Category-2/3 queries (technical,
# multi-token) are unaffected since they always match several tokens.
MIN_TOKEN_MATCHES = CONFIG["min_token_matches"]

# Maximum number of tokens passed to OpenSearch after stop-word filtering.
# Bounds worst-case clause count for pathologically long queries.
MAX_QUERY_TOKENS = CONFIG["max_query_tokens"]

# Per-request timeout sent to OpenSearch (seconds).
# If the cluster does not respond within this window the query is aborted
# and an empty result is returned rather than hanging the caller.
SEARCH_TIMEOUT_SECS = CONFIG["search_timeout_secs"]

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


@dataclass
class SearchResult:
    uids: list[str]
    error: str | None = None


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class OsKeywordEvaluator:
    """
    Keyword search using OpenSearch native fuzzy matching on structured fields.

    For each query token, issues a multi-field bool/should query with
    fuzziness=AUTO and per-field prefix_length across connectors, actions,
    input_fields, and datapill_fields.  Recipes are ranked by the sum of
    boosted match scores.

    Parameters
    ----------
    k      : number of results to retrieve per query
    client : OpenSearch client from clients.get_client()
    """

    def __init__(
        self,
        k: int,
        client,
    ):
        self.k = k
        self.client = client

    def _normalize_query_text(self, query: str) -> str:
        """
        Lowercase and rewrite important multi-word aliases before tokenization.
        """
        text = query.lower()
        for pattern, dst in PHRASE_ALIAS_PATTERNS:
            text = pattern.sub(dst, text)
        return text

    def _normalize_alias(self, token: str) -> str:
        """Map common abbreviations/aliases to canonical structured tokens."""
        return ALIASES.get(token, token)

    def _extract_tokens(self, query: str) -> list[str]:
        """
        Tokenize, normalize aliases, deduplicate, drop stop words, then cap
        at MAX_QUERY_TOKENS while preserving the original query order.
        """
        raw_tokens = _TOKEN_RE.findall(self._normalize_query_text(query))
        seen, tokens = set(), []
        for raw in raw_tokens:
            token = self._normalize_alias(raw)
            if token in _STOP_WORDS or token in seen:
                continue
            seen.add(token)
            tokens.append(token)

        return tokens[:MAX_QUERY_TOKENS]

    def _allow_fuzzy(self, field: str, token: str) -> bool:
        """
        Gate fuzzy matching per field based on token shape and field cardinality.

        input_fields  (~1,377 terms) and datapill_fields (~17,905 terms) are
        large enough that fuzzy matching plain English words ("parameters",
        "status", "records") produces mostly noise.  For these fields we only
        fuzzy-match compound identifiers (tokens containing "_"), where a
        one-character typo is plausible and the expanded set stays small thanks
        to the shared prefix constraint.  Plain words produce no clause for
        these fields — they are silently skipped.

        connectors and actions have small dictionaries (~288 / ~888 terms) so
        fuzzy is always allowed there.
        """
        if field in ("input_fields.text", "datapill_fields.text"):
            return "_" in token
        return True

    def _fuzzy_clauses(self, token: str) -> list[dict]:
        """Fuzzy fallback clauses with per-field fan-out controls."""
        clauses: list[dict] = []
        for field, boost in FIELD_BOOSTS.items():
            if not self._allow_fuzzy(field, token):
                continue
            params = FUZZY_PARAMS[field]
            clauses.append({
                "match": {
                    field: {
                        "query":          token,
                        "fuzziness":      FUZZINESS,
                        "prefix_length":  params["prefix_length"],
                        "max_expansions": params["max_expansions"],
                        "boost":          boost,
                    }
                }
            })
        return clauses

    def _exact_clauses(self, token: str) -> list[dict]:
        """High-precision exact matches before fuzzy fallback."""
        clauses: list[dict] = []
        for field, boost in FIELD_BOOSTS.items():
            clauses.append({
                "constant_score": {
                    "filter": {"term": {field: token}},
                    "boost": boost * 2.0,
                }
            })

        for field, boost in RAW_FIELDS.items():
            clauses.append({
                "constant_score": {
                    "filter": {"term": {field: token}},
                    "boost": boost,
                }
            })
        return clauses

    def _pair_phrase_clauses(self, tokens: list[str]) -> list[dict]:
        """Bonus phrase clauses for adjacent informative token pairs."""
        clauses: list[dict] = []
        for left, right in zip(tokens, tokens[1:]):
            if left in _STOP_WORDS or right in _STOP_WORDS:
                continue
            phrase = f"{left} {right}"
            clauses.extend([
                {
                    "match_phrase": {
                        "actions.text": {
                            "query": phrase,
                            "boost": 4.0,
                        }
                    }
                },
                {
                    "match_phrase": {
                        "input_fields.text": {
                            "query": phrase,
                            "boost": 3.0,
                        }
                    }
                },
                {
                    "match_phrase": {
                        "connectors.text": {
                            "query": phrase,
                            "boost": 2.5,
                        }
                    }
                },
            ])
        return clauses

    def _build_query(self, query: str) -> dict:
        """
        Build a token-grouped bool/should query where each outer clause
        represents one meaningful query token, and the inner clauses fuzzy-
        match that token across all four keyword fields.

        minimum_should_match at the outer level requires MIN_TOKEN_MATCHES
        distinct query tokens to match — preventing hub recipes with huge
        datapill vocabularies from ranking first on a single incidental hit.

        Stop words are removed before building clauses so that generic words
        ("how", "we", "the", …) don't generate noise matches.
        """
        tokens = self._extract_tokens(query)
        if not tokens:
            return {"match_none": {}}

        # Outer clause per token; inner clause per field.
        # A recipe satisfies an outer clause if the token exact-matches
        # or fuzzy-matches any of its structured fields.
        token_clauses = []
        for token in tokens:
            field_clauses = self._exact_clauses(token) + self._fuzzy_clauses(token)
            token_clauses.append({
                "bool": {"should": field_clauses, "minimum_should_match": 1}
            })

        phrase_clauses = self._pair_phrase_clauses(tokens)

        return {
            "bool": {
                "should":               token_clauses + phrase_clauses,
                "minimum_should_match": min(MIN_TOKEN_MATCHES, len(token_clauses)),
            }
        }

    def _search(self, query: str) -> SearchResult:
        """Return top-k recipe UIDs for the query.

        Evaluation keeps going on timeout or OpenSearch error, but the failure
        mode is returned explicitly so callers can distinguish it from a real
        zero-hit query.
        """
        body = {
            "query":   self._build_query(query),
            "size":    self.k,
            "_source": False,
            "timeout": f"{SEARCH_TIMEOUT_SECS}s",
        }
        try:
            resp = self.client.search(
                index="recipes",
                body=body,
                request_timeout=SEARCH_TIMEOUT_SECS,
            )
        except ConnectionTimeout:
            print(f"  [timeout] query={query[:60]!r}")
            return SearchResult([], error="timeout")
        except ConnectionError as exc:
            print(f"  [connection error] {exc}")
            return SearchResult([], error="connection_error")
        except TransportError as exc:
            print(f"  [transport error] status={exc.status_code} {exc.error}")
            return SearchResult([], error="transport_error")
        if resp.get("timed_out"):
            print(f"  [timed_out] query={query[:60]!r}")
            return SearchResult([], error="timed_out")
        return SearchResult([hit["_id"] for hit in resp["hits"]["hits"]])

    # ── Per-category evaluation ───────────────────────────────────────────────

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

            search_result = self._search(row["query"])
            retrieved = search_result.uids

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
                "search_error":       search_result.error or "",
                "retrieved":          ", ".join(retrieved),
                "strong_list":        ", ".join(sorted(strong_set)),
                "weak_list":          ", ".join(sorted(weak_set)),
            })

        if skipped:
            print(f"  Skipped {skipped} queries (empty strong list)")
        return pd.DataFrame(records)

    # ── Full run ──────────────────────────────────────────────────────────────

    def run(
        self,
        category_dfs: list[tuple[str, pd.DataFrame]],
    ) -> tuple[list[pd.DataFrame], list[CategoryMetrics]]:
        k = self.k
        print(f"{'=' * 60}")
        print(f"OpenSearch keyword (fuzzy)  |  k={k}")
        print(f"Fields: connectors(×{FIELD_BOOSTS['connectors.text']})  "
              f"actions(×{FIELD_BOOSTS['actions.text']})  "
              f"input_fields(×{FIELD_BOOSTS['input_fields.text']})  "
              f"datapill_fields(×{FIELD_BOOSTS['datapill_fields.text']})")
        print(f"fuzziness={FUZZINESS}  prefix_length=per-field  "
              f"min_token_matches={MIN_TOKEN_MATCHES}  stop_words=on  "
              f"aliases=on  exact_first=on  phrase_pairs=on")

        detail_frames: list[pd.DataFrame] = []
        metrics:       list[CategoryMetrics] = []

        for cat_name, df in category_dfs:
            print(f"\n── {cat_name} ──")
            results    = self.evaluate_category(df, cat_name)
            detail_frames.append(results)

            p          = results[f"precision@{k}"].mean()
            r          = results[f"recall@{k}"].mean()
            mrr        = results["rr"].mean()
            avg_strong = results["strong_hits_top5"].mean()
            avg_weak   = results["weak_hits_top5"].mean()
            no_results = (results["n_retrieved"] == 0).sum()
            n_errors   = (results["search_error"] != "").sum()

            print(f"  Queries evaluated  : {len(results)}")
            print(f"  Queries with 0 hits: {no_results}")
            print(f"  Queries with errors: {n_errors}")
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
    )
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    k = args.k
    selected_cats = [
        (f"Category {n}", pd.read_csv(CAT_PATHS[n]))
        for n in sorted(args.category)
    ]
    print("  |  ".join(f"{name}: {len(df)} queries" for name, df in selected_cats))

    client    = get_client()
    evaluator = OsKeywordEvaluator(k, client)
    detail_frames, metrics = evaluator.run(selected_cats)

    # Per-category CSVs
    for frame, (cat_name, _) in zip(detail_frames, selected_cats):
        cat_slug = cat_name.lower().replace(" ", "")
        out_path = BASE_DIR / f"os_kw_fuzzy_{cat_slug}_k{k}.csv"
        frame.to_csv(out_path, index=False)
        print(f"Detailed results → {out_path.name}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    model_key   = "os/keyword/fuzzy"
    summary_rows = [
        {
            "model":                model_key,
            "category":             m.category,
            "n_queries":            m.n_queries,
            f"precision@{k}":        m.precision,
            f"recall@{k}":           m.recall,
            "MRR":                  m.mrr,
            f"avg_strong_hits@{k}":  m.avg_strong_hits,
            f"avg_weak_hits@{k}":    m.avg_weak_hits,
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
