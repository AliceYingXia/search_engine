"""
add_embeddings.py
=================

Embeds the `text` column of the `recipes` table using a chosen model
and writes vectors into the corresponding embedding table.

Supported models
----------------
    text-embedding-3-small    →  embeddings_text_embedding_3_small  (dim 1536, OpenAI gateway)
    text-embedding-3-large    →  embeddings_text_embedding_3_large  (dim 3072, OpenAI gateway)
    BAAI/bge-m3               →  embeddings_bge_m3                  (dim 1024, local HuggingFace)
    Qwen/Qwen3-Embedding-0.6B →  embeddings_qwen3_embedding_0_6b    (dim 1024, local HuggingFace)

HuggingFace models are downloaded once and cached locally by sentence-transformers.
Set HF_TOKEN in .env if the model requires authentication (e.g. gated repos).

To add a new model: add an entry to MODEL_CONFIG and create the matching
table in setup_schema.sql.

Usage
-----
    # All models in one run (default):
    python 06-pgvector/add_embeddings.py

    # Specific model(s):
    python 06-pgvector/add_embeddings.py --model text-embedding-3-large
    python 06-pgvector/add_embeddings.py --model "BAAI/bge-m3" "Qwen/Qwen3-Embedding-0.4B"

    # Only rows missing a vector (safe to re-run / resume):
    python 06-pgvector/add_embeddings.py --missing-only

Environment variables
---------------------
    BASE_URL, API_KEY              — OpenAI-compatible gateway (text-embedding-3-*)
    HF_TOKEN                       — HuggingFace token for gated model downloads (optional)
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD  (postgres connection)
"""

import argparse
import os
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests as _requests
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------
_openai_client = OpenAI(
    base_url=os.environ["BASE_URL"],
    api_key=os.environ["API_KEY"],
)

_baseten_client = OpenAI(
    base_url=os.environ["BASETEN_BASE_URL"],
    api_key=os.environ["BASETEN_API_KEY"],
)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------
MODEL_CONFIG = {
    "text-embedding-3-small": {
        "table":     "embeddings_text_embedding_3_small",
        "dimension": 1536,
        "backend":   "openai",
    },
    "text-embedding-3-large": {
        "table":     "embeddings_text_embedding_3_large",
        "dimension": 3072,
        "backend":   "openai",
    },
    "BAAI/bge-m3": {
        "table":     "embeddings_bge_m3",
        "dimension": 1024,
        "backend":   "huggingface",
    },
    "Qwen/Qwen3-Embedding-0.6B": {
        "table":     "embeddings_qwen3_embedding_0_6b",
        "dimension": 1024,
        "backend":   "huggingface",
    },
    "intfloat/multilingual-e5-large-instruct": {
        "table":     "embeddings_multilingual_e5_large_instruct",
        "dimension": 1024,
        "backend":   "huggingface",
    },
    "Qwen/Qwen3-Embedding-4B": {
        "table":       "embeddings_qwen3_embedding_4b",
        "dimension":   2560,
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-3yd060v3.api.baseten.co/environments/production/predict",
    },
    "mixedbread-ai/mxbai-embed-large-v1": {
        "table":       "embeddings_mxbai_embed_large_v1",
        "dimension":   1024,
        "backend":     "baseten_predict",
        "predict_url": "https://model-qvvpmnjq.api.baseten.co/environments/production/predict",
    },
    "Qwen/Qwen3-Embedding-8B": {
        "table":       "embeddings_qwen3_embedding_8b",
        "dimension":   4096,
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-wom8ozkq.api.baseten.co/environments/production/predict",
    },
    # ── No-comments variants (same model, different source column) ─────────────
    "text-embedding-3-large_nc": {
        "table":         "embeddings_text_embedding_3_large_nc",
        "dimension":     3072,
        "backend":       "openai",
        "model_name":    "text-embedding-3-large",
        "source_column": "text_no_comments",
    },
    "Qwen/Qwen3-Embedding-8B_nc": {
        "table":         "embeddings_qwen3_embedding_8b_nc",
        "dimension":     4096,
        "backend":       "baseten_predict_batch",
        "predict_url":   "https://model-wom8ozkq.api.baseten.co/environments/production/predict",
        "source_column": "text_no_comments",
    },
}

BATCH_SIZE = 20   # texts per embedding call

# ---------------------------------------------------------------------------
# Postgres connection
# ---------------------------------------------------------------------------
DSN = dict(
    host     = os.getenv("PGHOST",     "localhost"),
    port     = int(os.getenv("PGPORT", "5432")),
    dbname   = os.getenv("PGDATABASE", "postgres"),
    user     = os.getenv("PGUSER",     "postgres"),
    password = os.getenv("PGPASSWORD", "postgres"),
)

# ---------------------------------------------------------------------------
# HuggingFace model cache (downloaded once, reused for the process lifetime)
# ---------------------------------------------------------------------------
_hf_models: dict[str, SentenceTransformer] = {}

def get_hf_model(model: str) -> SentenceTransformer:
    if model not in _hf_models:
        print(f"  Loading {model} from HuggingFace (downloading if not cached) ...")
        hf_token = os.getenv("HF_TOKEN")
        _hf_models[model] = SentenceTransformer(model, token=hf_token)
    return _hf_models[model]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_recipes(cur, embedding_table: str, missing_only: bool, source_column: str = "text") -> list[tuple[str, str]]:
    """Return list of (recipe_uid, text) to embed."""
    if missing_only:
        cur.execute(f"""
            SELECT r.recipe_uid, r.{source_column}
            FROM   recipes r
            LEFT JOIN {embedding_table} e USING (recipe_uid)
            WHERE  e.recipe_uid IS NULL
            ORDER  BY r.recipe_uid
        """)
    else:
        cur.execute(f"SELECT recipe_uid, {source_column} FROM recipes ORDER BY recipe_uid")
    return cur.fetchall()


def _parse_predict_embedding(response_json) -> list[float]:
    """Parse an embedding from a Baseten /predict response."""
    if isinstance(response_json, list):
        return response_json
    if isinstance(response_json, dict):
        if "embedding" in response_json:
            return response_json["embedding"]
        if "data" in response_json:
            return response_json["data"][0]["embedding"]
    raise ValueError(f"Unexpected /predict response format: {type(response_json)}")


def _parse_predict_embeddings_batch(response_json) -> list[list[float]]:
    """Parse a list of embeddings from a Baseten /predict batch response."""
    if isinstance(response_json, list) and response_json and isinstance(response_json[0], list):
        return response_json
    if isinstance(response_json, dict) and "data" in response_json:
        return [d["embedding"] for d in sorted(response_json["data"], key=lambda x: x["index"])]
    raise ValueError(f"Unexpected /predict batch response format: {type(response_json)}")


def embed_batch(texts: list[str], model: str, backend: str) -> list[list[float]]:
    """Embed a batch of texts using the appropriate backend."""
    if backend == "openai":
        api_model = MODEL_CONFIG[model].get("model_name", model)
        resp = _openai_client.embeddings.create(model=api_model, input=texts)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
    elif backend == "baseten":
        resp = _baseten_client.embeddings.create(model="baseten-model", input=texts)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
    elif backend == "baseten_predict":
        cfg = MODEL_CONFIG[model]
        predict_url = cfg["predict_url"]
        embeddings = []
        for text in texts:
            r = _requests.post(
                predict_url,
                headers={"Authorization": f"Api-Key {os.environ['BASETEN_API_KEY']}"},
                json={"input": text, "model": "model", "encoding_format": "float"},
            )
            r.raise_for_status()
            embeddings.append(_parse_predict_embedding(r.json()))
        return embeddings
    elif backend == "baseten_predict_batch":
        cfg = MODEL_CONFIG[model]
        predict_url = cfg["predict_url"]
        r = _requests.post(
            predict_url,
            headers={"Authorization": f"Api-Key {os.environ['BASETEN_API_KEY']}"},
            json={"input": texts, "model": "model", "encoding_format": "float"},
        )
        r.raise_for_status()
        return _parse_predict_embeddings_batch(r.json())
    else:
        hf_model = get_hf_model(model)
        return hf_model.encode(texts, normalize_embeddings=True).tolist()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def embed_model(cur, conn, model: str, missing_only: bool):
    cfg     = MODEL_CONFIG[model]
    table   = cfg["table"]
    dim     = cfg["dimension"]
    backend = cfg["backend"]

    source_column = cfg.get("source_column", "text")
    print(f"\nModel   : {model}  (dim={dim}, backend={backend})")
    print(f"Table   : {table}")
    print(f"Source  : recipes.{source_column}")

    rows = fetch_recipes(cur, table, missing_only, source_column)
    print(f"{len(rows)} recipes to embed")

    if not rows:
        print("Nothing to do.")
        return

    total    = len(rows)
    inserted = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch  = rows[batch_start : batch_start + BATCH_SIZE]
        uids   = [r[0] for r in batch]
        texts  = [r[1] for r in batch]

        print(f"  [{batch_start + 1}–{batch_start + len(batch)}/{total}] embedding ...", end=" ", flush=True)

        vectors = embed_batch(texts, model, backend)

        psycopg2.extras.execute_values(
            cur,
            f"""
            INSERT INTO {table} (recipe_uid, embedding)
            VALUES %s
            ON CONFLICT (recipe_uid) DO UPDATE SET embedding = EXCLUDED.embedding
            """,
            [(uid, vec) for uid, vec in zip(uids, vectors)],
        )
        conn.commit()
        inserted += len(batch)
        print(f"done ({inserted}/{total})")

        if backend == "openai":
            time.sleep(0.1)   # light rate-limit buffer

    print(f"Finished — {inserted} vectors written to `{table}`")
    print(f"Create the HNSW index when ready:")
    print(f"  CREATE INDEX ON {table} USING hnsw (embedding vector_cosine_ops);")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        nargs="+",
        choices=list(MODEL_CONFIG) + ["all"],
        default=["all"],
        help="Model(s) to embed. Pass one, several, or 'all' (default: all).",
    )
    parser.add_argument("--missing-only", action="store_true",
                        help="Only embed rows not yet present in the embedding table")
    args = parser.parse_args()

    models = list(MODEL_CONFIG) if "all" in args.model else args.model
    mode   = "missing only" if args.missing_only else "all recipes"

    print(f"Models : {', '.join(models)}")
    print(f"Mode   : {mode}")

    conn = psycopg2.connect(**DSN)
    cur  = conn.cursor()

    for model in models:
        embed_model(cur, conn, model, args.missing_only)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
