"""
add_embeddings.py
=================

Embeds the `text` column of the `recipes` table using a chosen model
and writes vectors into the corresponding embedding table.

Supported models
----------------
    See MODEL_REGISTRY in models.py. To add a new model, add an entry
    there and create the matching table in setup_schema.py.

Usage
-----
    # All models in one run (default):
    python pipeline/03_evaluate_embeddings/add_embeddings.py

    # Specific model(s):
    python pipeline/03_evaluate_embeddings/add_embeddings.py --model text-embedding-3-large
    python pipeline/03_evaluate_embeddings/add_embeddings.py --model "BAAI/bge-m3" "Qwen/Qwen3-Embedding-0.4B"

    # Only rows missing a vector (safe to re-run / resume):
    python pipeline/03_evaluate_embeddings/add_embeddings.py --missing-only

Environment variables
---------------------
    BASE_URL, API_KEY              — OpenAI-compatible gateway (text-embedding-3-*)
    BASETEN_API_KEY                — Baseten API key
    HF_TOKEN                       — HuggingFace token for gated model downloads (optional)
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD  (postgres connection)
"""

import argparse
import time

import psycopg2.extras

from clients import get_connection
from models import MODEL_REGISTRY, EmbeddingModel

BATCH_SIZE = 20   # texts per embedding API call

# Models that have a dimension (i.e. can be ingested — excludes eval-only +instruct variants)
INGESTABLE_MODELS = [name for name, cfg in MODEL_REGISTRY.items() if cfg.dimension is not None]


class EmbeddingPipeline:
    """
    Fetches recipes from Postgres, embeds them with one model, and writes
    the resulting vectors back into the appropriate embedding table.
    """

    def __init__(self, model_name: str, conn, missing_only: bool = False):
        self.model = EmbeddingModel(model_name)
        self.conn = conn
        self.cur = conn.cursor()
        self.missing_only = missing_only

    def _fetch_recipes(self) -> list[tuple[str, str]]:
        table = self.model.table
        col   = self.model.source_column
        if self.missing_only:
            self.cur.execute(f"""
                SELECT r.recipe_uid, r.{col}
                FROM   recipes r
                LEFT JOIN {table} e USING (recipe_uid)
                WHERE  e.recipe_uid IS NULL
                ORDER  BY r.recipe_uid
            """)
        else:
            self.cur.execute(
                f"SELECT recipe_uid, {col} FROM recipes ORDER BY recipe_uid"
            )
        return self.cur.fetchall()

    def run(self) -> int:
        """Embed all (or missing) recipes. Returns the number of vectors written."""
        cfg = self.model.config
        print(f"\nModel   : {self.model.name}  (dim={cfg.dimension}, backend={cfg.backend})")
        print(f"Table   : {self.model.table}")
        print(f"Source  : recipes.{self.model.source_column}")

        rows = self._fetch_recipes()
        print(f"{len(rows)} recipes to embed")

        if not rows:
            print("Nothing to do.")
            return 0

        total    = len(rows)
        inserted = 0

        for batch_start in range(0, total, BATCH_SIZE):
            batch  = rows[batch_start : batch_start + BATCH_SIZE]
            uids   = [r[0] for r in batch]
            texts  = [r[1] for r in batch]

            print(
                f"  [{batch_start + 1}–{batch_start + len(batch)}/{total}] embedding ...",
                end=" ",
                flush=True,
            )

            vectors = self.model.embed_texts(texts)

            pg_type = self.model.pg_type
            vec_strs = ["[" + ",".join(map(str, v)) + "]" for v in vectors]
            psycopg2.extras.execute_values(
                self.cur,
                f"""
                INSERT INTO {self.model.table} (recipe_uid, embedding)
                VALUES %s
                ON CONFLICT (recipe_uid) DO UPDATE SET embedding = EXCLUDED.embedding
                """,
                list(zip(uids, vec_strs)),
                template=f"(%s, %s::{pg_type})",
            )
            self.conn.commit()
            inserted += len(batch)
            print(f"done ({inserted}/{total})")

            if cfg.backend == "openai":
                time.sleep(0.1)   # light rate-limit buffer

        ops = "halfvec_cosine_ops" if self.model.pg_type == "halfvec" else "vector_cosine_ops"
        print(f"Finished — {inserted} vectors written to `{self.model.table}`")
        print(f"Create the HNSW index when ready:")
        print(f"  CREATE INDEX ON {self.model.table} USING hnsw (embedding {ops});")
        return inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        nargs="+",
        choices=INGESTABLE_MODELS + ["all"],
        default=["all"],
        help="Model(s) to embed. Pass one, several, or 'all' (default: all).",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Only embed rows not yet present in the embedding table.",
    )
    args = parser.parse_args()

    models = INGESTABLE_MODELS if "all" in args.model else args.model
    mode   = "missing only" if args.missing_only else "all recipes"

    print(f"Models : {', '.join(models)}")
    print(f"Mode   : {mode}")

    conn = get_connection()

    for model_name in models:
        pipeline = EmbeddingPipeline(model_name, conn, missing_only=args.missing_only)
        pipeline.run()

    conn.close()


if __name__ == "__main__":
    main()
