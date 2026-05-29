"""
ingest_recipes.py
=================

Loads recipes_for_pgvector.csv into the `recipes` table.
Run this once before add_embeddings.py.

Usage
-----
    python pipeline/03_evaluate_postgre/ingest_recipes.py

Environment variables
---------------------
    PGHOST     (default: localhost)
    PGPORT     (default: 5432)
    PGDATABASE (default: postgres)
    PGUSER     (default: postgres)
    PGPASSWORD (default: postgres)
"""

import sys
from pathlib import Path

import pandas as pd

from clients import get_connection

# The corpus CSV is produced by 02_synthesize_data — run:
#   python pipeline/02_synthesize_data/run.py --phase prepare
_SYNTH_DIR = Path(__file__).parent.parent / "02_synthesize_data"
sys.path.insert(0, str(_SYNTH_DIR))
from config import PGVECTOR_CSV_PATH as CSV_PATH  # noqa: E402


class RecipeIngester:
    """Loads a recipes CSV into the `recipes` Postgres table."""

    def __init__(self, csv_path: Path, conn):
        self.csv_path = csv_path
        self.conn = conn
        self.cur = conn.cursor()

    def run(self) -> tuple[int, int]:
        """Insert all rows, upsert on conflict. Returns (inserted, skipped)."""
        df = pd.read_csv(self.csv_path)
        print(f"Loaded {len(df)} rows from {self.csv_path.name}")

        inserted = skipped = 0

        for _, row in df.iterrows():
            self.cur.execute(
                """
                INSERT INTO recipes
                    (recipe_uid, author_id, flow_id, version_no,
                     connectors, step_count, text_no_comments, payload,
                     text_search_vector, text_search_vector_simple)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        to_tsvector('english', coalesce(%s, '')),
                        to_tsvector('simple',  coalesce(%s, '')))
                ON CONFLICT (recipe_uid) DO UPDATE
                    SET text_no_comments          = EXCLUDED.text_no_comments,
                        text_search_vector        = EXCLUDED.text_search_vector,
                        text_search_vector_simple = EXCLUDED.text_search_vector_simple
                """,
                (
                    row["recipe_uid"],
                    int(row["author_id"]),
                    int(row["flow_id"]),
                    int(row["version_no"]),
                    row["connectors"],
                    int(row["step_count"]),
                    row["text_no_comments"],
                    row["payload"],
                    row["text_no_comments"],
                    row["text_no_comments"],
                ),
            )
            if self.cur.rowcount:
                inserted += 1
            else:
                skipped += 1

        self.conn.commit()
        self.cur.close()
        return inserted, skipped


def main():
    ingester = RecipeIngester(CSV_PATH, get_connection())
    inserted, skipped = ingester.run()
    print(f"Done — inserted: {inserted}  skipped (already existed): {skipped}")


if __name__ == "__main__":
    main()
