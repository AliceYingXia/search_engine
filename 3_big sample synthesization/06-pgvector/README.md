# pgvector Data Preparation

## Overview

Scripts for preparing and ingesting recipe data into a local pgvector instance,
with support for multiple embedding models stored in separate tables.

---

## Run Order

```bash
# 0. Start pgvector (if not running)
docker run -d --name pgvector -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg16

# 0. If the container already exsits (if running)
docker start pgvector

# 1. Create tables
python 06-pgvector/setup_schema.py

# 2. Build the seed CSV (if not already done)
python 06-pgvector/prepare_pgvector_data.py

# 3. Load recipes (text + metadata, no embeddings yet)
python 06-pgvector/ingest_recipes.py

# 4. Add embeddings — all models in one run (default)
python 06-pgvector/add_embeddings.py

# 4b. Or a specific model only
python 06-pgvector/add_embeddings.py --model text-embedding-3-large

# 4c. No-comments variants (embeds text_no_comments column)
python 06-pgvector/add_embeddings.py --model text-embedding-3-large_nc "Qwen/Qwen3-Embedding-8B_nc"

# 4d. Resume after interruption (skips already-embedded rows)
python 06-pgvector/add_embeddings.py --missing-only
```

After embeddings are loaded, create HNSW indexes for fast search:

```sql
CREATE INDEX ON embeddings_text_embedding_3_small USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON embeddings_text_embedding_3_large USING hnsw (embedding vector_cosine_ops);
```

---

## Scripts

| Script                     | Purpose                                                          |
| -------------------------- | ---------------------------------------------------------------- |
| `prepare_pgvector_data.py` | Select seed recipes → `recipes_for_pgvector.csv`                 |
| `setup_schema.py`          | Create `recipes` table + one embedding table per model           |
| `setup_schema.sql`         | Same schema as SQL (reference only)                              |
| `ingest_recipes.py`        | Load CSV into `recipes` table (safe to re-run, skips duplicates) |
| `add_embeddings.py`        | Embed `text` column for all models (or specific ones) in one run |

---

## Seed Selection Filters

`prepare_pgvector_data.py` applies these filters (via `eval_utils.select_recipe_seeds()`):

1. Recipes ranked by distinct connector count and step count (descending).
2. Infrastructure connectors (present in >50% of an author's recipes) are excluded from the diversity check.
3. A recipe is selected only if its signal connector set overlaps ≤50% with every already-selected seed for that author.
4. Recipes with fewer than 3 distinct connectors are skipped.

Output: `recipes_for_pgvector.csv` (115 seeds across 10 authors).

---

## Seed Recipe Statistics

### Step Count Summary (115 recipes)

| Stat | Value |
|------|-------|
| Min | 3 |
| Max | 77 |
| Median | 14 |
| Mean | 20.4 |
| Std dev | 18.6 |
| p25 | 7 |
| p75 | 28 |

### Step Count Distribution

| Bucket | Count |
|--------|-------|
| 1–10 | 47 |
| 11–20 | 28 |
| 21–30 | 14 |
| 31–40 | 10 |
| 41–50 | 7 |
| 51–60 | 5 |
| 61–77 | 4 |

The distribution is right-skewed: most recipes are small (≤20 steps), with a long tail of larger workflows up to 77 steps.

See `step_count_histogram.png` for a visual breakdown.

---

## Schema

### `recipes` table

| Column       | Type    | Description                                |
| ------------ | ------- | ------------------------------------------ |
| `recipe_uid` | TEXT PK | `"{author_id}_{flow_id}_v{version_no}"`    |
| `author_id`  | INT     | Author who owns the recipe                 |
| `flow_id`    | INT     | Recipe flow ID                             |
| `version_no` | INT     | Recipe version                             |
| `connectors` | TEXT    | Comma-separated sorted connector list      |
| `step_count` | INT     | Number of steps in the recipe              |
| `text`       | TEXT    | `recipe_summary` — the field to embed      |
| `payload`    | JSONB   | All metadata fields for pgvector filtering |

### Embedding tables (one per model)

Each embedding table has the same structure:

| Column       | Type               | Description                                |
| ------------ | ------------------ | ------------------------------------------ |
| `recipe_uid` | TEXT PK FK→recipes | Links back to `recipes`                    |
| `model`      | TEXT               | Model name (set by default)                |
| `embedding`  | vector(N)          | Embedding vector (dimension matches model) |

| Table                                    | Model                          | Dimension | Source column       |
| ---------------------------------------- | ------------------------------ | --------- | ------------------- |
| `embeddings_text_embedding_3_small`      | `text-embedding-3-small`       | 1536      | `text`              |
| `embeddings_text_embedding_3_large`      | `text-embedding-3-large`       | 3072      | `text`              |
| `embeddings_bge_m3`                      | `BAAI/bge-m3`                  | 1024      | `text`              |
| `embeddings_qwen3_embedding_0_6b`        | `Qwen/Qwen3-Embedding-0.6B`    | 1024      | `text`              |
| `embeddings_multilingual_e5_large_instruct` | `intfloat/multilingual-e5-large-instruct` | 1024 | `text`       |
| `embeddings_qwen3_embedding_4b`          | `Qwen/Qwen3-Embedding-4B`      | 2560      | `text`              |
| `embeddings_mxbai_embed_large_v1`        | `mixedbread-ai/mxbai-embed-large-v1` | 1024 | `text`           |
| `embeddings_qwen3_embedding_8b`          | `Qwen/Qwen3-Embedding-8B`      | 4096      | `text`              |
| `embeddings_text_embedding_3_large_nc`   | `text-embedding-3-large`       | 3072      | `text_no_comments`  |
| `embeddings_qwen3_embedding_8b_nc`       | `Qwen/Qwen3-Embedding-8B`      | 4096      | `text_no_comments`  |

To add a new model: add a `CREATE TABLE` block to `setup_schema.py` and
add an entry to `MODEL_CONFIG` in `add_embeddings.py`.

---

## Similarity Search

```sql
SELECT r.recipe_uid, r.text, r.payload,
       1 - (e.embedding <=> '[...]'::vector) AS cosine_similarity
FROM   embeddings_text_embedding_3_large e
JOIN   recipes r USING (recipe_uid)
ORDER  BY e.embedding <=> '[...]'::vector
LIMIT  10;
```

---

## Environment Variables (Postgres connection)

| Variable     | Default     |
| ------------ | ----------- |
| `PGHOST`     | `localhost` |
| `PGPORT`     | `5432`      |
| `PGDATABASE` | `postgres`  |
| `PGUSER`     | `postgres`  |
| `PGPASSWORD` | `postgres`  |

Override any of these before running the scripts:

```bash
export PGPASSWORD=mypassword
python 06-pgvector/ingest_recipes.py
```
