"""
setup_schema.py
===============

Creates the pgvector schema (replaces running setup_schema.sql via psql).

Usage
-----
    python pipeline/03_evaluate_embeddings/setup_schema.py
"""

from clients import get_connection


SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS recipes (
    recipe_uid          TEXT PRIMARY KEY,
    author_id           INT  NOT NULL,
    flow_id             INT  NOT NULL,
    version_no          INT  NOT NULL,
    connectors          TEXT,
    step_count          INT,
    text_no_comments    TEXT,
    payload             JSONB,
    text_search_vector         TSVECTOR,
    text_search_vector_simple  TSVECTOR
);

-- Migration: add column to existing tables that pre-date this field
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS text_search_vector TSVECTOR;

-- Backfill: populate for any rows ingested before this column existed
UPDATE recipes
SET    text_search_vector = to_tsvector('english', coalesce(text_no_comments, ''))
WHERE  text_search_vector IS NULL;

-- GIN index for fast FTS lookups (english)
CREATE INDEX IF NOT EXISTS recipes_fts_idx ON recipes USING GIN(text_search_vector);

-- simple config: lowercase only, no stemming, no stopword removal
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS text_search_vector_simple TSVECTOR;

UPDATE recipes
SET    text_search_vector_simple = to_tsvector('simple', coalesce(text_no_comments, ''))
WHERE  text_search_vector_simple IS NULL;

CREATE INDEX IF NOT EXISTS recipes_fts_simple_idx ON recipes USING GIN(text_search_vector_simple);

CREATE TABLE IF NOT EXISTS embeddings_text_embedding_3_large (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'text-embedding-3-large',
    embedding   vector(3072)
);

CREATE TABLE IF NOT EXISTS embeddings_qwen3_embedding_8b (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'Qwen/Qwen3-Embedding-8B',
    embedding   vector(4096)
)
"""


class SchemaManager:
    """Creates (or verifies) the pgvector schema for this pipeline."""

    def __init__(self, conn):
        self.conn = conn
        self.conn.autocommit = True
        self.cur = conn.cursor()

    def setup(self) -> None:
        for statement in SQL.strip().split(";"):
            statement = statement.strip()
            if not statement:
                continue
            self.cur.execute(statement)
            print(f"OK: {statement[:60].replace(chr(10), ' ')} ...")

        self.cur.close()
        print("\nSchema ready.")
        print("Next: python pipeline/03_evaluate_embeddings/ingest_recipes.py")


def main():
    manager = SchemaManager(get_connection())
    manager.setup()


if __name__ == "__main__":
    main()
