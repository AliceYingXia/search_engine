"""
index_recipe_corpus.py
=================

Loads recipes_for_pgvector.csv into the OpenSearch recipes index.
Mirrors pipeline/03_evaluate_postgre/ingest_recipes.py.

Run this after create_opensearch_indices.py and before build_recipe_embeddings.py.

Usage
-----
    python pipeline/04_evaluate_opensearch/index_recipe_corpus.py

Environment variables
---------------------
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import json
import sys
from pathlib import Path

import pandas as pd
from opensearchpy.helpers import bulk

from clients import get_client

# Reuse the same CSV path as step 03
_SYNTH_DIR = Path(__file__).parent.parent / "02_synthesize_data"
sys.path.insert(0, str(_SYNTH_DIR))
from config import PGVECTOR_CSV_PATH as CSV_PATH, SUMMARIES_PATH  # noqa: E402

INDEX = "recipes"


def _parse_payload(raw) -> dict | str:
    """Try to parse the payload column as JSON; fall back to raw string."""
    if pd.isna(raw):
        return {}
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, ValueError):
        return str(raw)


def _to_str_list(val) -> list[str]:
    """Coerce a CSV string, Python list, or numpy array to a plain list[str]."""
    # numpy arrays and Python lists — already the right shape
    if hasattr(val, "__iter__") and not isinstance(val, str):
        return [str(v) for v in val]
    # scalar: check for NA then empty string
    if val is None:
        return []
    try:
        if pd.isna(val):
            return []
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if not s:
        return []
    # comma-separated string (connectors column in the CSV)
    return [p.strip() for p in s.split(",") if p.strip()]


class RecipeIngester:
    def __init__(self, csv_path: Path, client):
        self.csv_path = csv_path
        self.client   = client

    def _load(self) -> pd.DataFrame:
        """
        Join the recipes CSV with the structured fields from step-01 parquet.
        The parquet adds actions, input_fields, datapill_fields per recipe.
        """
        csv = pd.read_csv(self.csv_path)
        par = pd.read_parquet(SUMMARIES_PATH, columns=[
            "flow_id", "version_no", "actions", "input_fields", "datapill_fields",
        ])
        df = csv.merge(par, on=["flow_id", "version_no"], how="left")
        print(f"Loaded {len(csv)} rows from CSV  +  {len(par)} from parquet"
              f"  →  {df['actions'].notna().sum()} matched")
        return df

    def run(self) -> tuple[int, int]:
        df = self._load()

        actions = [
            {
                "_index": INDEX,
                "_id":    row["recipe_uid"],
                "_source": {
                    "author_id":        int(row["author_id"]),
                    "flow_id":          int(row["flow_id"]),
                    "version_no":       int(row["version_no"]),
                    "step_count":       int(row["step_count"]),
                    "text_no_comments": row["text_no_comments"] if pd.notna(row["text_no_comments"]) else "",
                    "payload":          _parse_payload(row["payload"]),
                    # keyword arrays — used for structured fuzzy search
                    "connectors":       _to_str_list(row["connectors"]),
                    "actions":          _to_str_list(row.get("actions")),
                    "input_fields":     _to_str_list(row.get("input_fields")),
                    "datapill_fields":  _to_str_list(row.get("datapill_fields")),
                },
            }
            for _, row in df.iterrows()
        ]

        success, errors = bulk(
            self.client,
            actions,
            chunk_size=200,
            raise_on_error=False,
        )
        failed = len(errors) if isinstance(errors, list) else 0
        return success, failed


def main():
    ingester = RecipeIngester(CSV_PATH, get_client())
    inserted, failed = ingester.run()
    print(f"Done — indexed: {inserted}  failed: {failed}")
    if failed:
        print("Re-run to retry failed documents, or check index mapping.")


if __name__ == "__main__":
    main()
