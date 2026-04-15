# OpenSearch Full-Text Search Evaluation

This note explains how to run [evaluate_full_text_search.py](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/evaluate_full_text_search.py) in `pipeline/04_evaluate_opensearch`.

## How To Use `evaluate_full_text_search.py`

This script evaluates OpenSearch full-text retrieval against the three evaluation query sets.

It supports:

- `--config english` or `--config simple`
- `--scoring bm25` or `--scoring coverage`
- `--category 1 2 3`
- `--k <top_k>`

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

You do not need dense embeddings for this full-text search evaluation.

### Basic Usage

Run the default setup:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py
```

Default behavior:

- config: `english` = custom `english_underscore` analyzer
- scoring: `bm25`
- BM25 parameters in the default recipes index: `k1=0.5`, `b=0.75`
- categories: `1 2 3`
- `k=5`

### Common Examples

Run with the custom coverage scoring:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --scoring coverage
```

Run with the `simple` analyzer:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --config simple
```

Run only selected categories:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --category 1 2
```

Run with a different top-k:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --k 10
```

Run `simple` + `coverage` together:

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --config simple --scoring coverage
```

### Outputs

The script writes:

- per-query detail CSVs for each category
- summary rows into `eval_summary_k<k>.csv`

These outputs are saved in [04_evaluate_opensearch](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch).

## Algorithm Overview

`evaluate_full_text_search.py` is a retrieval benchmark for OpenSearch text search.

It does not create embeddings. Instead, it tests how well OpenSearch can retrieve the correct recipes using only indexed text fields and analyzer-based matching.

The script has two main decisions:

1. Which analyzed text field to search
2. How to score matching documents

### 1. Search Field Choice

The script supports two configurations:

- `english`
- `simple`

These map to different indexed fields in the `recipes` index:

- `english` uses `text_no_comments`
- `simple` uses `text_no_comments.simple`

Important clarification:

- `english` here does **not** mean the plain built-in OpenSearch `english` analyzer
- it means the custom `english_underscore` analyzer configured for `text_no_comments`
- this custom analyzer is the default used by `evaluate_full_text_search.py`

#### `english`

This uses the custom `english_underscore` analyzer defined during index creation.

So when you run the script with the default `--config english`, you are actually using this project-specific analyzer.

Its behavior is:

- split text into tokens
- split underscore-compound identifiers into parts
- lowercase text
- remove English stopwords
- stem words to their root forms

Example:

- `workato_recipe_function` can become tokens like `workato`, `recipe`, `function`
- `running` can match `run`

This is useful when users write natural-language queries that only partially overlap with technical recipe text.

#### `simple`

This uses a much lighter analyzer:

- lowercase only
- no stemming
- no stopword removal

This is useful as a baseline because it preserves the original terms more literally.

### 2. Scoring Strategy

The script supports two scoring modes:

- `bm25`
- `coverage`

Both use OpenSearch retrieval, but they rank documents differently.

#### `bm25`

This is the default text search ranking used in many search systems.

The script sends a standard OpenSearch `match` query with `operator: "or"`.

That means:

- any matching analyzed query term can retrieve a document
- documents are ranked using BM25

BM25 generally rewards:

- matching more query terms
- rare terms more than common terms
- reasonable term concentration

BM25 also includes document-length normalization, so longer documents are not automatically favored just because they contain more words.

#### `coverage`

This is a custom ranking mode added for this project.

Instead of using BM25 weights, the script:

1. tokenizes the query using the same analyzer as the indexed field
2. builds one OpenSearch clause per unique query token
3. gives each matched token the same score contribution

So the score becomes closer to:

- “how many distinct query tokens appear in the document?”

This makes `coverage`:

- length-blind
- frequency-blind
- easier to compare to lexeme-count style ranking

In code terms, the script uses:

- `indices.analyze()` to get analyzed query tokens
- `bool/should` with `constant_score` clauses

Each matched token contributes exactly `1`.

### End-to-End Flow Per Query

For each evaluation query, the script does the following:

1. Read the query text from the evaluation dataset
2. Read `strong_list` and `weak_list`
3. Search OpenSearch with the selected config and scoring mode
4. Collect the top-`k` recipe ids
5. Compute metrics against `strong_list`

The metrics include:

- `precision@k`
- `recall@k`
- `reciprocal rank`
- number of strong hits in top `k`
- number of weak hits in top `k`

Only `strong_list` counts as ground-truth relevance for the main metrics.

### Why This Script Exists

This script gives you a pure full-text baseline for OpenSearch.

It helps answer questions like:

- Does stemming help on our recipe corpus?
- Does a simple lowercase analyzer work better for some categories?
- Is BM25 better than a token-coverage score for these queries?
- How far can we go with text search before needing embeddings?

### Practical Interpretation

Use `english + bm25` when you want the most standard OpenSearch text-search baseline.
In this repo, the default recipes index now uses BM25 with `k1=0.5` and `b=0.75`.

Use `english + coverage` when you want ranking based more directly on analyzed token overlap than BM25 weighting.

## Comparison Of The Four Configurations

We ran these four combinations:

- `english + coverage`
- `english + bm25`
- `simple + coverage`
- `simple + bm25`

Here:

- `english` means the custom `english_underscore` analyzer
- `simple` means the lowercase-only simple analyzer
- `coverage` ranks by analyzed token overlap
- `bm25` uses standard BM25 relevance scoring

### Results At `k=5`

#### Category 1

| Configuration        | Precision@5 | Recall@5 | MRR    | Avg Strong Hits@5 |
| -------------------- | ----------- | -------- | ------ | ----------------- |
| `english + coverage` | 0.0400      | 0.1307   | 0.1207 | 0.2000            |
| `english + bm25`     | 0.0640      | 0.2373   | 0.1837 | 0.3200            |
| `simple + coverage`  | 0.0400      | 0.1129   | 0.1073 | 0.2000            |
| `simple + bm25`      | 0.0480      | 0.1396   | 0.1147 | 0.2400            |

Best result in Category 1:

- `english + bm25`

#### Category 2

| Configuration        | Precision@5 | Recall@5 | MRR    | Avg Strong Hits@5 |
| -------------------- | ----------- | -------- | ------ | ----------------- |
| `english + coverage` | 0.1840      | 0.9100   | 0.7353 | 0.9200            |
| `english + bm25`     | 0.1680      | 0.8300   | 0.6967 | 0.8400            |
| `simple + coverage`  | 0.1560      | 0.7700   | 0.6383 | 0.7800            |
| `simple + bm25`      | 0.1560      | 0.7700   | 0.6707 | 0.7800            |

Best result in Category 2:

- `english + coverage`

#### Category 3

| Configuration        | Precision@5 | Recall@5 | MRR    | Avg Strong Hits@5 |
| -------------------- | ----------- | -------- | ------ | ----------------- |
| `english + coverage` | 0.1959      | 0.8639   | 0.7398 | 0.9796            |
| `english + bm25`     | 0.2122      | 0.9456   | 0.8143 | 1.0612            |
| `simple + coverage`  | 0.1633      | 0.7422   | 0.6156 | 0.8163            |
| `simple + bm25`      | 0.1796      | 0.8027   | 0.7082 | 0.8980            |

Best result in Category 3:

- `english + bm25`

### Main Takeaways

- `english` is consistently better than `simple` across all categories.
- The custom `english_underscore` analyzer is clearly important for this recipe corpus.
- `english + bm25` is strongest for Category 1 and Category 3.
- `english + coverage` is strongest for Category 2.
- With BM25 tuned to the default `k1=0.5, b=0.75`, `english + bm25` gets a noticeable lift on Category 3 and a small lift on Category 1.
- The main tradeoff is not `english` vs `simple` anymore — it is `english + bm25` vs `english + coverage`.

### Practical Recommendation

If you want one strong default OpenSearch full-text baseline, use:

- `english + bm25` when you want the strongest standard BM25 ranking
- `english + coverage` when you want token-overlap-oriented ranking

For this dataset:

- `english + bm25` is the strongest overall general-purpose choice
- `english + coverage` is especially strong for action-oriented Category 2 queries
- the current default BM25 setting is `k1=0.5, b=0.75`

Use `simple` when you want to test a more literal no-stemming baseline.
