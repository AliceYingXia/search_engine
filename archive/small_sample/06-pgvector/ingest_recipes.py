"""
ingest_recipes.py
=================

Loads recipes_for_pgvector.csv into the `recipes` table.
Run this once before add_embeddings.py.

Usage
-----
    python 06-pgvector/ingest_recipes.py

Environment variables
---------------------
    PGHOST     (default: localhost)
    PGPORT     (default: 5432)
    PGDATABASE (default: postgres)
    PGUSER     (default: postgres)
    PGPASSWORD (default: postgres)
"""

import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Paths & connection
# ---------------------------------------------------------------------------
BASE_DIR    = Path(__file__).parent
CSV_PATH    = BASE_DIR / "recipes_for_pgvector.csv"

DSN = dict(
    host     = os.getenv("PGHOST",     "localhost"),
    port     = int(os.getenv("PGPORT", "5432")),
    dbname   = os.getenv("PGDATABASE", "postgres"),
    user     = os.getenv("PGUSER",     "postgres"),
    password = os.getenv("PGPASSWORD", "postgres"),
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} rows from {CSV_PATH.name}")

    conn = psycopg2.connect(**DSN)
    cur  = conn.cursor()

    inserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        cur.execute("""
            INSERT INTO recipes
                (recipe_uid, author_id, flow_id, version_no, connectors, step_count, text, text_no_comments, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (recipe_uid) DO UPDATE
                SET text_no_comments = EXCLUDED.text_no_comments
        """, (
            row["recipe_uid"],
            int(row["author_id"]),
            int(row["flow_id"]),
            int(row["version_no"]),
            row["connectors"],
            int(row["step_count"]),
            row["text"],
            row["text_no_comments"] if "text_no_comments" in row.index else row["text"],
            row["payload"],
        ))
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"Done — inserted: {inserted}  skipped (already existed): {skipped}")


if __name__ == "__main__":
    main()
