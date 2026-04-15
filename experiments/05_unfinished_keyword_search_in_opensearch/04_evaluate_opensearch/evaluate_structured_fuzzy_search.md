# OpenSearch Structured Fuzzy Search Evaluation

This note explains how to run [evaluate_structured_fuzzy_search.py](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/evaluate_structured_fuzzy_search.py) in `pipeline/04_evaluate_opensearch`.

## How To Use `evaluate_structured_fuzzy_search.py`

This script evaluates OpenSearch structured fuzzy retrieval against the three evaluation query sets.

It searches structured recipe metadata instead of full recipe text.

### What It Searches

The script searches these OpenSearch fields from the `recipes` index:

- `connectors`
- `actions`
- `input_fields`
- `datapill_fields`

These fields are indexed with the `keyword_split` analyzer, which:

- splits on underscores and slashes
- lowercases tokens
- does not apply stemming

### Prerequisites

Before running it, make sure these earlier steps are ready:

1. Create the OpenSearch indices:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/create_opensearch_indices.py
```

2. Index the recipe corpus:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/index_recipe_corpus.py
```

You do not need dense embeddings for this structured fuzzy evaluation.

### Basic Usage

Run the default setup:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_structured_fuzzy_search.py
```

Default behavior:

- alias normalization: on
- exact-first boosts: on
- phrase-pair boosts: on
- stopword filtering: on
- minimum token matches: `2`
- maximum query tokens: `15`
- boundary-safe phrase alias normalization: on
- search error reporting: on
- field boosts:
  - `connectors.text = 3.0`
  - `actions.text = 3.0`
  - `input_fields.text = 1.0`
  - `datapill_fields.text = 1.0`
- `k=5`

Run with a different top-k:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_structured_fuzzy_search.py --k 10
```

### Outputs

The script writes:

- per-query detail CSVs for each category
- summary rows into `eval_summary_k<k>.csv`

These outputs are saved in [04_evaluate_opensearch](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch).

## Algorithm Overview

`evaluate_structured_fuzzy_search.py` is a non-embedding technical lookup baseline.

Instead of searching free text like [evaluate_full_text_search.py](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/evaluate_full_text_search.py), it searches structured metadata fields extracted from recipes.

The goal is to answer questions like:

- can we find recipes by connector names?
- can we find recipes by action names?
- can we find recipes by input field names?
- can we find recipes by datapill field names?

### Core Retrieval Logic

For each query, the script:

1. lowercases the query and applies phrase alias normalization
2. tokenizes the query
3. applies single-token alias normalization and deduplicates
4. removes generic stopwords
5. caps the remaining tokens at `MAX_QUERY_TOKENS = 15`
6. adds exact-match boosts for analyzed fields and raw structured fields
7. adds phrase-pair boosts for adjacent tokens
8. builds a structured OpenSearch query over connectors/actions/fields
9. retrieves the top-`k` recipes
10. evaluates them against `strong_list`

### Conservative Alias Normalization

The chosen alias layer is intentionally small to avoid overfitting.

Examples:

- `sfdc -> salesforce`
- `slackbot -> slack_bot`
- `slack bot -> slack_bot`
- `google sheets -> google_sheets`

The alias layer is query-side only. It does not change the OpenSearch index.

### Field Weighting

The script uses field boosts:

- `connectors.text`: `3.0`
- `actions.text`: `3.0`
- `input_fields.text`: `1.0`
- `datapill_fields.text`: `1.0`

These are the final chosen default weights after empirical tuning.

### Exact-First + Phrase-Pair Boosts

The final fixed mode restores two ranking refinements that improved retrieval materially:

- exact-match boosts before fuzzy fallback
- phrase-pair boosts for adjacent tokens such as `salesforce account` or `slack bot`

This keeps the implementation simpler than the earlier fully experimental version because it does not use token-type weighting, but it still recovers much of the lost Category 2 and Category 3 performance.

### Stopword Filtering and Hub Recipe Guard

Before building the query, the script strips a set of generic English words (`how`, `can`, `the`, `and`, and similar) from the token list.

Leaving these in causes hub recipes with hundreds of `datapill_fields` to accumulate spurious match scores on incidental overlaps with common words.

To further suppress hub recipe contamination, the query requires at least `MIN_TOKEN_MATCHES = 2` distinct query tokens to match a document (`minimum_should_match` at the outer token-grouped level). A single incidental match is not enough to retrieve a recipe.

### Query Length Cap

After stopword filtering, if the token list exceeds `MAX_QUERY_TOKENS = 15`, the script keeps the first 15 normalized tokens. This bounds clause count and keeps the query shape predictable.

### Fuzzy Matching Controls

The script uses `fuzziness=AUTO` (edit distance 0 for 1–2 char tokens, 1 for 3–5, 2 for 6+) with per-field parameters tuned to each field's dictionary size:

| Field                  | `max_expansions` | `prefix_length` |
| ---------------------- | ---------------- | --------------- |
| `connectors.text`      | 50               | 2               |
| `actions.text`         | 50               | 2               |
| `input_fields.text`    | 30               | 2               |
| `datapill_fields.text` | 10               | 3               |

Tighter settings on larger fields bound the Levenshtein automaton fan-out so that query latency stays predictable under load.

For `input_fields` (~1,377 unique terms) and `datapill_fields` (~17,905 unique terms), fuzzy matching is additionally restricted to **compound tokens only** (tokens containing `_`). Plain words like `status` or `records` only match exactly on these two fields. This prevents common English words from expanding into thousands of unrelated technical identifiers on the largest and noisiest fields.

### Search Error Reporting

If OpenSearch times out or returns a transport/connection error, the script now records that explicitly in the per-query output via the `search_error` column.

This is important because it distinguishes:

- a real zero-hit query
- an infrastructure failure

Without this separation, evaluation results can silently collapse to zero and look like a relevance problem.

### Evaluation Metrics

For each query, the script computes:

- `precision@k`
- `recall@k`
- `reciprocal rank`
- strong hits in top `k`
- weak hits in top `k`

As in the other evaluators, only `strong_list` counts as ground truth for the main metrics.

## Final Chosen Version

The final chosen version keeps:

- a conservative alias list
- exact-first boosts
- phrase-pair boosts
- stopword filtering
- `MIN_TOKEN_MATCHES = 2`
- `MAX_QUERY_TOKENS = 15`
- per-field fuzzy parameters (`FUZZY_PARAMS`)
- compound-token-only fuzzy on `input_fields` and `datapill_fields`
- explicit `search_error` reporting

We kept this version because:

- it is still simpler and less likely to overfit than the earlier experimental version
- the behavior is easier to reason about and maintain
- the final `3,3,1,1` weighting is still stronger than the earlier `4,3,2,0.5` default
- the alias layer stays useful without turning into a large ranking policy
- the error reporting makes the evaluation safer to trust
- it recovers most of the performance lost by the fully simplified fuzzy-only version

## Final Results At `k=5`

These are the current final metrics for the chosen version:

| Category     | Precision@5 | Recall@5 | MRR    | Avg Strong Hits@5 |
| ------------ | ----------- | -------- | ------ | ----------------- |
| Category 1   | 0.0560      | 0.2040   | 0.1623 | 0.2800            |
| Category 2   | 0.1800      | 0.8900   | 0.7747 | 0.9000            |
| Category 3   | 0.1959      | 0.8980   | 0.7745 | 0.9796            |

All three categories had `0` query errors in the latest rerun.

## What Improved During Iteration

We experimented with:

- alias normalization
- exact-first ranking
- token-type weighting
- phrase-pair boosts
- stopword filtering and hub recipe guard (`MIN_TOKEN_MATCHES`)
- per-field fuzzy parameters and compound-token-only fuzzy on large fields
- specificity-based token prioritization before the query length cap

Empirically:

- exact-first helped Category 2
- phrase-pair boosts helped Category 3 in some experiments
- token-type weighting had mixed benefit
- conservative aliases preserved practical normalization without obvious benchmark overfitting
- broader weight sweeps suggested the final `3,3,1,1` weighting was a better default than the earlier `4,3,2,0.5`
- stopword filtering and `MIN_TOKEN_MATCHES = 2` were the main fix for Category 1 weakness; hub recipes with 400+ datapill tokens had been monopolizing results by matching a single incidental word
- restricting fuzzy to compound tokens on `input_fields` / `datapill_fields` reduced noise on the two largest fields without hurting precision on exact technical lookups
- specificity-based token prioritization (field_like > connector_like > neutral, longer first) ensures the query length cap never silently discards the most informative tokens

## Practical Interpretation

This evaluator is strongest for:

- Category 2 technical feature queries
- Category 3 dependency and schema-impact queries

It is still weaker on:

- Category 1 business-language queries

So this method is best viewed as a strong structured technical retriever, not a complete replacement for dense or full-text search.
