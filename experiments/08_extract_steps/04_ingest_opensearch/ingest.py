"""
ingest.py

Ingest recipes from the embedded parquet into the bt_recipe OpenSearch index.
Embeddings are pre-computed — no embedding generation happens here.

Usage:
    python ingest.py [--recreate]

Env vars (or .env at project root):
    OPENSEARCH_URL   default http://localhost:9200
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from opensearchpy import OpenSearch, helpers

load_dotenv(Path(__file__).parent.parent.parent / ".env")

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
INDEX_NAME     = "bt_recipe"
INPUT_PARQUET  = Path(__file__).parent.parent / "03_embed" / "embedded_descriptions.parquet"
CHUNK_SIZE     = 50


def generate_docs(df: pd.DataFrame):
    for _, row in df.iterrows():
        yield {
            "_index": INDEX_NAME,
            "_id":    row["recipe_uid"],
            "_source": {
                "recipe_uid":       row["recipe_uid"],
                "flow_id":          int(row["flow_id"]),
                "version_no":       int(row["version_no"]),
                "author_id":        int(row["author_id"]),
                "step_count":       int(row["step_count"]),
                "tag":              row["tag"],
                "connectors":       row["connectors"],
                "actions":          row["actions"],
                "input_fields":     row["input_fields"],
                "datapill_fields":  row["datapill_fields"],
                "search_text":      row["search_text"],
                "description":      row["description"],
                "usage":            row["usage"],
                "description_qwen": row["description_qwen"].tolist(),
                "usage_qwen":       row["usage_qwen"].tolist(),
                "combined_qwen":    row["combined_qwen"].tolist(),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true",
                        help="Delete and recreate the index before ingesting")
    args = parser.parse_args()

    if args.recreate:
        import subprocess, sys
        subprocess.run([sys.executable, str(Path(__file__).parent / "create_index.py"), "--recreate"], check=True)

    client = OpenSearch(OPENSEARCH_URL)

    print(f"Loading {INPUT_PARQUET} ...")
    df = pd.read_parquet(INPUT_PARQUET)
    print(f"  {len(df)} recipes")

    print(f"Ingesting into '{INDEX_NAME}' ...")
    success, errors = helpers.bulk(client, generate_docs(df), chunk_size=CHUNK_SIZE, request_timeout=120)
    print(f"Done. Indexed: {success}  Errors: {len(errors) if errors else 0}")

    count = client.count(index=INDEX_NAME)["count"]
    print(f"Index now has {count} documents.")


if __name__ == "__main__":
    main()
