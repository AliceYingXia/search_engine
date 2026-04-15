# 03 — Evaluate Embeddings

Ingests recipes into pgvector, generates embeddings, and evaluates dense search quality against labelled eval datasets.

---

## Prerequisites

- PostgreSQL with the `vector` extension (pgvector) running
- `.env` file at the repo root with the variables listed below
- Eval datasets produced by `pipeline/02_synthesize_data/` (category1/2/3_dataset.csv)
- Recipe CSV produced by `pipeline/02_synthesize_data/` (`--phase prepare`)

---

## Environment variables

| Variable          | Used by            | Default     |
| ----------------- | ------------------ | ----------- |
| `PGHOST`          | all                | `localhost` |
| `PGPORT`          | all                | `5432`      |
| `PGDATABASE`      | all                | `postgres`  |
| `PGUSER`          | all                | `postgres`  |
| `PGPASSWORD`      | all                | `postgres`  |
| `BASE_URL`        | OpenAI models      | —           |
| `API_KEY`         | OpenAI models      | —           |
| `BASETEN_API_KEY` | Baseten models     | —           |
| `HF_TOKEN`        | HuggingFace models | optional    |

---

## Accessing PostgreSQL

```bash
psql -h localhost -U postgres -d postgres
```

Password: `postgres`

---

## Steps

### 1. Create the schema

```bash
python pipeline/03_evaluate_embeddings/setup_schema.py
```

Creates the `recipes` table and all `embeddings_*` tables (idempotent — safe to re-run).

To start fresh, drop everything first:

```sql
DROP TABLE IF EXISTS
  embeddings_text_embedding_3_large,
  embeddings_qwen3_embedding_8b
CASCADE;

DROP TABLE IF EXISTS recipes CASCADE;
```

### 2. Ingest recipes

```bash
python pipeline/03_evaluate_embeddings/ingest_recipes.py
```

Loads `recipes_for_pgvector.csv` into the `recipes` table (upsert — safe to re-run).

### 3. Generate embeddings

All models embed from the `text_no_comments` column (recipe text without comments).

```bash
# Both models
python pipeline/03_evaluate_embeddings/add_embeddings.py

# Specific model
python pipeline/03_evaluate_embeddings/add_embeddings.py --model text-embedding-3-large
python pipeline/03_evaluate_embeddings/add_embeddings.py --model "Qwen/Qwen3-Embedding-8B"

# Resume / fill gaps only
python pipeline/03_evaluate_embeddings/add_embeddings.py --missing-only
```

After embedding, create an HNSW index for fast search:

```sql
CREATE INDEX ON embeddings_text_embedding_3_large USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON embeddings_qwen3_embedding_8b USING hnsw (embedding vector_cosine_ops);
```

### 4a. Evaluate — dense embeddings

```bash
# Default model (text-embedding-3-large), all 3 categories, k=5
python pipeline/03_evaluate_embeddings/evaluate_pgvector.py

# Qwen3-Embedding-8B (base)
python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --model "Qwen/Qwen3-Embedding-8B"

# Qwen3-Embedding-8B with instruction prefix
python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --model "Qwen/Qwen3-Embedding-8B+instruct"

# Specific categories or k
python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --category 1 3
python pipeline/03_evaluate_embeddings/evaluate_pgvector.py --k 10
```

Outputs:

- `eval_results_<model>_k<k>.csv` — per-query detail
- `eval_summary_k<k>.csv` — aggregated metrics across all evaluated models (appended, not overwritten)

### 4b. Evaluate — PostgreSQL FTS baseline

Standard PostgreSQL full-text search with no domain customisation. Two
configurations are available via `--config`:

| Config              | Description                                          | Model key       |
| ------------------- | ---------------------------------------------------- | --------------- |
| `english` (default) | Porter stemmer + standard ~122-word English stoplist | `pgfts/english` |
| `simple`            | Lowercase only — no stemming, no stopword removal    | `pgfts/simple`  |

Query strategy: `plainto_tsquery` applies the chosen config to stem/normalise
terms; all surviving terms are OR-combined so that any matching term retrieves
a document. `ts_rank` promotes documents that match more query terms.
Requires the tsvector columns and GIN indexes created by `setup_schema.py`.

```bash
# english config (default), all categories, k=5
python pipeline/03_evaluate_embeddings/evaluate_pgfts.py

# simple (basic) config
python pipeline/03_evaluate_embeddings/evaluate_pgfts.py --config simple

# specific categories or k
python pipeline/03_evaluate_embeddings/evaluate_pgfts.py --category 1
python pipeline/03_evaluate_embeddings/evaluate_pgfts.py --config simple --category 2 3 --k 10
```

Outputs per category:

- `pgfts_{config}_category<N>_k<k>.csv` — per-query detail
- `eval_summary_k<k>.csv` — appended under `pgfts/english` or `pgfts/simple`

### 4c. Evaluate — keyword search benchmark

Vocabulary-driven ILIKE keyword search baseline. At startup, a technical
vocabulary (~2,000 terms) is built from the corpus (connector names, action
names, field names ≥ 8 chars, alphabetic sub-words of compound connector names).
Any query token matching the vocabulary becomes an ILIKE condition — no
hand-crafted rules or stopword lists.

Vocab tokens are split into two tiers:

- **underscore tokens** — compound identifiers containing `_` (e.g. `workato_db_table`, `get_records`). Precise and unambiguous.
- **word tokens** — single-word app names (e.g. `salesforce`, `snowflake`). Broader.

Four search strategies are available via `--strategy`:

| Strategy         | Model key                      | Description                                                                                                                                                                                                                                                                                               |
| ---------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `and_or`         | `keyword/ilike/and_or`         | Default. Two-pass fallback: ILIKE AND on underscore tokens first; falls back to ILIKE OR on all tokens.                                                                                                                                                                                                   |
| `weighted`       | `keyword/ilike/weighted`       | Single-pass. OR across all tokens; underscore matches score 3 pts, word matches score 1 pt. Higher = better.                                                                                                                                                                                              |
| `lexicographic`  | `keyword/ilike/lexicographic`  | Single-pass. OR across all tokens; ORDER BY underscore score DESC, then word score DESC. Strict hierarchy.                                                                                                                                                                                                |
| `weighted_pgfts` | `keyword/ilike/weighted_pgfts` | Weighted ILIKE (same as `weighted`) with a `pgfts/english` fallback: if ILIKE returns < k results, the gap is filled by PostgreSQL FTS results (Porter stemmer + stopword removal, ts_rank ≥ 0.03). Designed for robustness when query terms are not yet in the vocabulary (e.g. newly added connectors). |

Queries with no vocabulary overlap (pure business-language Category 1 queries) return empty (`no_vocab`) in `and_or`, `weighted`, and `lexicographic`. In `weighted_pgfts`, these queries fall through to the pgfts leg, but business-language words do not appear in recipe text and score below the ts_rank threshold, so results remain empty in practice.

Each result row in `weighted_pgfts` output is labelled by retrieval path:

| Label            | Meaning                                                  |
| ---------------- | -------------------------------------------------------- |
| `weighted`       | Returned by ILIKE — vocab match found                    |
| `weighted+pgfts` | ILIKE returned < k results; gap filled by pgfts fallback |
| `no_vocab+pgfts` | No vocab tokens in query; all results from pgfts         |

```bash
# Default strategy (and_or), all 3 categories, k=5
python pipeline/03_evaluate_embeddings/evaluate_fulltext.py

# Weighted strategy (underscore=3, word=1)
python pipeline/03_evaluate_embeddings/evaluate_fulltext.py --strategy weighted

# Lexicographic strategy (strict underscore-first ranking)
python pipeline/03_evaluate_embeddings/evaluate_fulltext.py --strategy lexicographic

# Weighted + pgfts fallback (robustness to out-of-vocab query terms)
python pipeline/03_evaluate_embeddings/evaluate_fulltext.py --strategy weighted_pgfts

# Combine with category / k flags
python pipeline/03_evaluate_embeddings/evaluate_fulltext.py --strategy weighted --category 2 3 --k 10
```

Outputs per run (strategy name is included in filenames so runs do not overwrite each other):

- `fts_category<N>_k<k>_<strategy>.csv` — per-query detail
- `eval_summary_k<k>.csv` — appended under `keyword/ilike/<strategy>`

### 4d. Evaluate — hybrid search

Combines Qwen3-Embedding-8B+instruct (dense) with a keyword/FTS leg, fused with
weighted Reciprocal Rank Fusion (RRF). The fusion weight between the two legs is
determined per-query by a vocab signal:

| Signal in query                        | w\_kw | w\_dense | Rationale                                              |
| -------------------------------------- | ----- | -------- | ------------------------------------------------------ |
| Underscore tokens (e.g. `get_records`) | 2.0   | 1.0      | Exact technical identifiers — keyword leg more precise |
| Word-only tokens (e.g. `salesforce`)   | 1.0   | 2.0      | Broad terms — dense handles ambiguity better           |
| No vocab tokens (business language)    | 0.0   | 1.0      | Keyword returns nothing → pure dense                   |

Each leg fetches k×3 candidates before fusion; the fused list is truncated to top-k.

Three fuse modes are available via `--mode`:

| Mode                    | Keyword leg                                                         | Model key                                         |
| ----------------------- | ------------------------------------------------------------------- | ------------------------------------------------- |
| `fuse` (default)        | Vocabulary-driven ILIKE (AND → OR fallback)                         | `hybrid/qwen3-8b+instruct/fuse`                   |
| `fts-fuse`              | PostgreSQL FTS, `english` config (Porter stemmer + stopwords)       | `hybrid/qwen3-8b+instruct/fts-fuse`               |
| `weighted-pgfts-fuse`   | Weighted ILIKE (underscore=3, word=1) + pgfts/english gap-fill      | `hybrid/qwen3-8b+instruct/weighted-pgfts-fuse`    |

A `route` mode is also available: hard routing that sends queries with underscore tokens to keyword-only and all others to dense-only.

```bash
# fuse mode (default), all categories, k=5
python pipeline/03_evaluate_embeddings/evaluate_hybrid.py

# FTS leg instead of ILIKE keyword leg
python pipeline/03_evaluate_embeddings/evaluate_hybrid.py --mode fts-fuse

# Weighted ILIKE + pgfts fallback leg (best on Category 3)
python pipeline/03_evaluate_embeddings/evaluate_hybrid.py --mode weighted-pgfts-fuse

# Hard routing (keyword for underscore queries, dense otherwise)
python pipeline/03_evaluate_embeddings/evaluate_hybrid.py --mode route

# Specific categories or k
python pipeline/03_evaluate_embeddings/evaluate_hybrid.py --mode fts-fuse --category 2 3 --k 10
```

Requires `BASETEN_API_KEY` to be set (Qwen3-Embedding-8B+instruct runs on Baseten).

Outputs:

- `hybrid_<mode>_k<k>.csv` — per-query detail with signal label, weights, n_kw, n_emb per row
- `eval_summary_k<k>.csv` — appended under `hybrid/qwen3-8b+instruct/<mode>`

## Database tables

### `recipes`

Core recipe corpus. Must be populated before any embeddings can be inserted.

| Column                      | Type     | Description                                                                                      |
| --------------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| `recipe_uid`                | TEXT PK  | Unique recipe identifier                                                                         |
| `author_id`                 | INT      | Author                                                                                           |
| `flow_id`                   | INT      | Flow                                                                                             |
| `version_no`                | INT      | Version                                                                                          |
| `connectors`                | TEXT     | Connector list                                                                                   |
| `step_count`                | INT      | Number of steps                                                                                  |
| `text_no_comments`          | TEXT     | Recipe text with comments stripped (used for embedding and search)                               |
| `payload`                   | JSONB    | Raw recipe payload                                                                               |
| `text_search_vector`        | TSVECTOR | Pre-computed tsvector using `english` config (Porter stemmer + stopwords); GIN-indexed           |
| `text_search_vector_simple` | TSVECTOR | Pre-computed tsvector using `simple` config (lowercase only, no stemming/stopwords); GIN-indexed |

### Embedding tables

All embedding tables share the same structure and reference `recipes(recipe_uid)` via FK with `ON DELETE CASCADE`.
All models embed from `text_no_comments`.

| Table                               | Model                              | Dim  | Backend | Notes                                                                          |
| ----------------------------------- | ---------------------------------- | ---- | ------- | ------------------------------------------------------------------------------ |
| `embeddings_text_embedding_3_large` | `text-embedding-3-large`           | 3072 | OpenAI  |                                                                                |
| `embeddings_qwen3_embedding_8b`     | `Qwen/Qwen3-Embedding-8B`          | 4096 | Baseten |                                                                                |
| `embeddings_qwen3_embedding_8b`     | `Qwen/Qwen3-Embedding-8B+instruct` | 4096 | Baseten | eval only — reuses base model vectors, prepends task instruction at query time |

---

## Evaluation metrics

Computed against `strong_list` from the eval datasets (recipe UIDs rated "Strongly Related" by both GPT and Claude).

| Metric              | Description                                         |
| ------------------- | --------------------------------------------------- |
| `precision@k`       | Fraction of top-k results that are relevant         |
| `recall@k`          | Fraction of relevant results found in top-k         |
| `MRR`               | Mean Reciprocal Rank of the first relevant result   |
| `avg_strong_hits@k` | Average count of strongly-relevant results in top-k |
| `avg_weak_hits@k`   | Average count of weakly-relevant results in top-k   |

---

## File overview

| File                   | Purpose                                                                                                                 |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `clients.py`           | Postgres connection, OpenAI client, HuggingFace model cache, Baseten response parsers                                   |
| `models.py`            | `MODEL_REGISTRY` — single source of truth for all model configs and backends                                            |
| `setup_schema.py`      | Creates pgvector extension, `recipes`, and all `embeddings_*` tables                                                    |
| `ingest_recipes.py`    | Loads recipe CSV into the `recipes` table                                                                               |
| `add_embeddings.py`    | Generates and stores embeddings for one or all models                                                                   |
| `evaluate_pgvector.py` | Dense embedding evaluation — Precision@k / Recall@k / MRR across Category 1, 2 & 3                                      |
| `evaluate_pgfts.py`    | PostgreSQL FTS baseline — standard `english` config (Porter stemmer + stopwords), OR-combined terms ranked by `ts_rank` |
| `evaluate_fulltext.py` | Vocabulary-driven ILIKE keyword search baseline — corpus-derived technical vocab, ILIKE AND → OR strategy               |
| `evaluate_hybrid.py`   | Hybrid search — weighted RRF fusion of Qwen3-8B+instruct dense search with a keyword/FTS leg; three fuse modes          |
