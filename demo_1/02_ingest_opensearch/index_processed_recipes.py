"""
index_processed_recipes.py
==========================

Indexes processed recipe records from `01_process_json/processed/recipes.parquet`
into the OpenSearch `recipes` index.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from opensearchpy.helpers import bulk

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from common.clients import ensure_opensearch_connection, get_client  # noqa: E402
from common.logging_utils import get_logger  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BASE_DIR / "01_process_json" / "processed" / "recipes.parquet"
INDEX = "recipes"
REQUIRED_COLUMNS = {
    "recipe_uid",
    "author_id",
    "flow_id",
    "version_no",
    "step_count",
    "text_no_comments",
    "payload_json",
    "connectors",
    "actions",
    "input_fields",
    "datapill_fields",
}

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--chunk-size", type=int, default=200)
    args = parser.parse_args()

    input_path = args.input
    if not input_path.exists():
        raise FileNotFoundError(f"Processed parquet not found: {input_path}")

    ensure_opensearch_connection()
    df = pd.read_parquet(input_path)
    missing_columns = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing_columns:
        raise ValueError(
            "Processed parquet is missing required columns: "
            + ", ".join(missing_columns)
        )

    actions = []
    skipped = 0
    for _, row in df.iterrows():
        try:
            actions.append({
                "_index": INDEX,
                "_id": row["recipe_uid"],
                "_source": {
                    "author_id": int(row.get("author_id", 0) or 0),
                    "flow_id": int(row.get("flow_id", 0) or 0),
                    "version_no": int(row.get("version_no", 0) or 0),
                    "step_count": int(row.get("step_count", 0) or 0),
                    "text_no_comments": row.get("text_no_comments", "") or "",
                    "payload": json.loads(row.get("payload_json", "{}") or "{}"),
                    "connectors": row.get("connectors", []) or [],
                    "actions": row.get("actions", []) or [],
                    "input_fields": row.get("input_fields", []) or [],
                    "datapill_fields": row.get("datapill_fields", []) or [],
                },
            })
        except Exception:
            skipped += 1

    success, errors = bulk(get_client(), actions, chunk_size=args.chunk_size, raise_on_error=False)
    failed = len(errors) if isinstance(errors, list) else 0
    logger.info("Indexed documents: %s  failed: %s", success, failed)
    if skipped:
        logger.warning("Skipped malformed rows: %s", skipped)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
