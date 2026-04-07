-- setup_schema.sql
-- Run once to create the pgvector schema for recipe search.
-- Usage:
--   psql -h localhost -p 5432 -U postgres -d postgres -f 06-pgvector/setup_schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Core recipe table (no embeddings) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS recipes (
    recipe_uid   TEXT PRIMARY KEY,
    author_id    INT  NOT NULL,
    flow_id      INT  NOT NULL,
    version_no   INT  NOT NULL,
    connectors   TEXT,
    step_count   INT,
    text         TEXT,
    payload      JSONB
);

-- ── One embedding table per model ──────────────────────────────────────────
-- Add a new table here whenever you want to evaluate a new model.

CREATE TABLE IF NOT EXISTS embeddings_text_embedding_3_small (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'text-embedding-3-small',
    embedding   vector(1536)
);

CREATE TABLE IF NOT EXISTS embeddings_text_embedding_3_large (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'text-embedding-3-large',
    embedding   vector(3072)
);

-- ── HNSW indexes (create after embeddings are loaded for best performance) ─
-- Run these after running add_embeddings.py:
--
-- CREATE INDEX ON embeddings_text_embedding_3_small USING hnsw (embedding vector_cosine_ops);
-- CREATE INDEX ON embeddings_text_embedding_3_large USING hnsw (embedding vector_cosine_ops);
