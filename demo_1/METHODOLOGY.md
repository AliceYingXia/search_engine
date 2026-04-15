# Demo 1 Methodology

This document explains how `demo_1` is organized, what each stage produces,
and why the retrieval system is designed this way for a production-oriented
demo.

## Goal

`demo_1` demonstrates a simple end-to-end semantic recipe search system with
three responsibilities:

1. process raw recipe JSON into normalized searchable records
2. ingest those records into OpenSearch
3. retrieve relevant recipes for live user queries

The demo is intentionally small enough to understand quickly, but structured in
the same way a production pipeline would be separated.

## System Overview

The folder is organized into three stages plus shared code:

```text
demo_1/
  common/
  01_process_json/
  02_ingest_opensearch/
  03_query/
```

- `common/`
  Shared OpenSearch clients, embedding model wrappers, index definitions, and
  retrieval helpers.
- `01_process_json/`
  Converts raw recipe JSON files into normalized recipe records.
- `02_ingest_opensearch/`
  Creates indices, indexes normalized recipes, and builds dense embeddings.
- `03_query/`
  Runs full-text search, dense search, and hybrid retrieval for live queries.

## Stage 1: Raw JSON Processing

Script:

- [process_recipe_json_files.py](/Users/alice/project/semantic_search/search_engine/demo_1/01_process_json/process_recipe_json_files.py)

### Input

A directory of raw recipe JSON files.

### Output

A parquet dataset at:

- `demo_1/01_process_json/processed/recipes.parquet`

### Why this stage exists

Raw recipe payloads are nested and difficult to search directly. This stage
extracts a normalized representation so later stages can index and retrieve
consistently.

### Extracted fields

For each recipe, the processor writes:

- `recipe_uid`
- `flow_id`
- `version_no`
- `author_id`
- `payload_json`
- `text_with_comments`
- `text_no_comments`
- `connectors`
- `actions`
- `input_fields`
- `datapill_fields`
- `step_count`

### Processing approach

The processor walks the recipe step tree and derives two kinds of search data:

1. readable summary text
2. structured lexical fields

Readable summary text:

- `text_with_comments`
  includes step summaries plus comments
- `text_no_comments`
  includes the same recipe structure without comment text

Structured lexical fields:

- `connectors`
  providers found in the recipe
- `actions`
  provider and action pairs such as `salesforce/search_records`
- `input_fields`
  non-UUID input field names
- `datapill_fields`
  non-UUID output field names from schemas

These structured fields are useful because they preserve exact technical
signals that are often diluted inside large free-text bodies.

## Stage 2: OpenSearch Ingestion

Scripts:

- [create_indices.py](/Users/alice/project/semantic_search/search_engine/demo_1/02_ingest_opensearch/create_indices.py)
- [index_processed_recipes.py](/Users/alice/project/semantic_search/search_engine/demo_1/02_ingest_opensearch/index_processed_recipes.py)
- [build_embeddings.py](/Users/alice/project/semantic_search/search_engine/demo_1/02_ingest_opensearch/build_embeddings.py)

### Index design

Index definitions live in:

- [index_definitions.py](/Users/alice/project/semantic_search/search_engine/demo_1/common/index_definitions.py)

Two index types are created:

1. `recipes`
   stores normalized recipe documents for full-text and metadata retrieval
2. embedding index
   stores dense vectors keyed by the same recipe ID

### Why the storage is split

The `recipes` index is optimized for lexical search and source retrieval.
The embedding index is optimized for nearest-neighbor vector lookup.

This separation keeps the retrieval logic simple:

- full-text search queries the `recipes` index
- dense search queries the embedding index
- both return the same recipe IDs

### Full-text mapping strategy

The `recipes` index uses:

- BM25 scoring
- custom analyzers for:
  - underscore-aware English text
  - keyword splitting for structured fields

The main searchable fields are:

- `text_no_comments`
- `connectors`
- `actions`
- `input_fields`
- `datapill_fields`

`text_no_comments` is indexed as analyzed text because it contains the readable
summary of the recipe.

The structured fields are indexed as keywords with text subfields so exact
technical tokens and split token variants are both available.

### Embedding strategy

Embedding model configuration lives in:

- [models.py](/Users/alice/project/semantic_search/search_engine/demo_1/common/models.py)

The demo currently supports:

- `Qwen/Qwen3-Embedding-8B-full+instruct`

The vector index stores:

- one `knn_vector` per recipe
- keyed by recipe ID

The embedding source text is currently:

- `text_no_comments`

This is a practical choice because it gives the dense retriever a readable,
compressed representation of the recipe rather than a raw nested payload.

## Stage 3: Query-Time Retrieval

Script:

- [search_recipes.py](/Users/alice/project/semantic_search/search_engine/demo_1/03_query/search_recipes.py)

Shared retrieval logic:

- [retrieval.py](/Users/alice/project/semantic_search/search_engine/demo_1/common/retrieval.py)

### Query flow

When a query comes in, the system:

1. classifies the query shape
2. decides how much to trust full-text and dense retrieval
3. runs both retrieval legs
4. fuses the ranked lists with weighted RRF
5. fetches source documents for the final recipe IDs

If dense retrieval fails and `--allow-fts-fallback` is enabled, the script
degrades to FTS-only instead of exiting. If the query would not normally run
FTS, the script issues a last-resort FTS search.

### Retrieval legs

Full-text search:

- queries `recipes`
- uses a `match` query against `text_no_comments`

Dense search:

- embeds the query
- runs OpenSearch `knn` against the embedding index

### Hybrid method

The demo uses a query-driven hybrid method rather than a result-driven
confidence model.

This means the query is classified before retrieval into one of:

- `structured_exact`
- `technical_words`
- `natural_language`

#### Query classes

`structured_exact`

- query includes exact technical structure like `_`, `/`, `-`, or digits
- examples: field-like names, action identifiers, connector/action pairs

`technical_words`

- query is short and technical, but does not show strong identifier structure

`natural_language`

- query is mostly plain business-language text

### Why query-driven weighting is used here

For a production demo, query-driven weighting is easier to explain and cheaper
to run than a heavier online confidence estimator. It avoids extra per-query
logic over retrieved candidates while still capturing the main retrieval
intuition:

- exact technical queries benefit from lexical retrieval
- natural-language queries benefit from dense retrieval
- mixed technical queries can benefit from both

### Fusion method

When both retrieval legs are active, the demo uses weighted Reciprocal Rank
Fusion (RRF).

The score contribution from each ranked list is:

```text
score(doc) += weight / (RRF_K + rank)
```

Where:

- `RRF_K = 60`
- `rank` starts at `1`

This means the system fuses by rank, not by raw BM25 or vector similarity
scores.

That is useful because:

- BM25 and vector scores are not directly comparable
- rank-based fusion is stable and simple to reason about

### Weighting policy

- `structured_exact`
  - `w_fts = 2.0`
  - `w_dense = 1.0`
- `technical_words`
  - `w_fts = 1.0`
  - `w_dense = 2.0`
- `natural_language`
  - `w_fts = 0.0`
  - `w_dense = 1.0`

This means the demo is fusion-only by default. It no longer supports a
separate route-only serving mode.

### Candidate depth

The retrieval system fetches more than the final `top_k` before fusion:

```text
candidate_k = top_k * candidate_multiplier
```

The default multiplier is `3`.

This gives RRF enough headroom to rescue useful candidates that may not already
be in the top few positions of either individual leg.

## Why This Design Is Production-Friendly

This demo is intentionally simple, but several design choices are meant to be
practical beyond a demo setting.

### Clear stage boundaries

Processing, ingestion, and retrieval are separated so they can be run
independently and scheduled differently in production.

### Shared code in `common/`

Shared modules reduce duplication and make it easier to keep:

- index definitions
- model config
- client configuration
- retrieval behavior

consistent across scripts.

### Searchable structured fields

The indexed fields are not only free text. Connectors, actions, and field names
are preserved as separate search surfaces so technical queries have stronger
lexical grounding.

### Rank-based hybrid

Weighted RRF avoids score calibration problems between lexical and dense
retrievers and gives a reliable baseline hybrid strategy.

## Known Simplifications

This demo intentionally keeps some parts lightweight:

- query classification is heuristic, not learned
- dense embeddings use one summary field rather than multiple document views
- the full-text query uses a simple `match` query rather than a more elaborate
  multi-field query
- online query rewriting is not used
- some short business-language queries may still be classified as
  `technical_words`

These are acceptable for a demo because they keep the system understandable and
easy to operate.

## Runtime Robustness

The demo scripts include a small amount of defensive error handling so the demo
fails cleanly:

- JSON processing validates the input directory and skips malformed files
- parquet ingestion validates file existence and required columns
- OpenSearch connection failures surface a short actionable message
- Baseten embedding failures surface a short actionable message
- embedding generation reports batch offsets when a batch fails
- query serving rejects empty queries
- CLI scripts exit with concise error messages instead of raw stack traces

This keeps the code simple while making demo runs much less brittle.

## Suggested Next Production Improvements

If this demo were extended further, the next improvements would likely be:

1. strengthen full-text retrieval with multi-field search over:
   - `text_no_comments`
   - `connectors.text`
   - `actions.text`
   - `input_fields.text`
   - `datapill_fields.text`
2. replace heuristic query classification with domain-vocabulary-aware routing
3. add evaluation scripts beside the runtime demo for regression tracking
4. add `fts_only` routing for very strong exact-token queries
5. expose the retrieval script as a service endpoint instead of a CLI-only tool

## Summary

`demo_1` is built around a simple principle:

- normalize recipe JSON into searchable records
- store lexical and dense search data separately but keyed by the same IDs
- choose or fuse retrievers based on query shape

This keeps the demo easy to explain while still reflecting a realistic
production retrieval architecture.
