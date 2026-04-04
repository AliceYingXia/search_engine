"""
setup_schema.py
===============

Creates the pgvector schema (replaces running setup_schema.sql via psql).

Usage
-----
    python 06-pgvector/setup_schema.py
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

DSN = dict(
    host     = os.getenv("PGHOST",     "localhost"),
    port     = int(os.getenv("PGPORT", "5432")),
    dbname   = os.getenv("PGDATABASE", "postgres"),
    user     = os.getenv("PGUSER",     "postgres"),
    password = os.getenv("PGPASSWORD", "postgres"),
)

SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS recipes (
    recipe_uid        TEXT PRIMARY KEY,
    author_id         INT  NOT NULL,
    flow_id           INT  NOT NULL,
    version_no        INT  NOT NULL,
    connectors        TEXT,
    step_count        INT,
    text              TEXT,
    text_no_comments  TEXT,
    payload           JSONB
);

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

CREATE TABLE IF NOT EXISTS embeddings_bge_m3 (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'BAAI/bge-m3',
    embedding   vector(1024)
);

CREATE TABLE IF NOT EXISTS embeddings_qwen3_embedding_0_6b (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'Qwen/Qwen3-Embedding-0.6B',
    embedding   vector(1024)
);

CREATE TABLE IF NOT EXISTS embeddings_multilingual_e5_large_instruct (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'intfloat/multilingual-e5-large-instruct',
    embedding   vector(1024)
);

CREATE TABLE IF NOT EXISTS embeddings_qwen3_embedding_4b (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'Qwen/Qwen3-Embedding-4B',
    embedding   vector(2560)
);

CREATE TABLE IF NOT EXISTS embeddings_mxbai_embed_large_v1 (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'mixedbread-ai/mxbai-embed-large-v1',
    embedding   vector(1024)
);

CREATE TABLE IF NOT EXISTS embeddings_qwen3_embedding_8b (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'Qwen/Qwen3-Embedding-8B',
    embedding   vector(4096)
);

CREATE TABLE IF NOT EXISTS embeddings_text_embedding_3_large_nc (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'text-embedding-3-large',
    embedding   vector(3072)
);

CREATE TABLE IF NOT EXISTS embeddings_qwen3_embedding_8b_nc (
    recipe_uid  TEXT PRIMARY KEY REFERENCES recipes(recipe_uid) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'Qwen/Qwen3-Embedding-8B',
    embedding   vector(4096)
);
"""

def main():
    conn = psycopg2.connect(**DSN)
    conn.autocommit = True
    cur = conn.cursor()

    for statement in SQL.strip().split(";"):
        statement = statement.strip()
        if not statement:
            continue
        cur.execute(statement)
        print(f"OK: {statement[:60].replace(chr(10), ' ')} ...")

    cur.close()
    conn.close()
    print("\nSchema ready.")
    print("Next: python 06-pgvector/ingest_recipes.py")

if __name__ == "__main__":
    main()
