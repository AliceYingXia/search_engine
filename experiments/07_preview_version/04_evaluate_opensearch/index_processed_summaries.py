"""
index_processed_summaries.py
============================

Indexes cleaned recipe summaries from pipeline/01_process_data into the
existing OpenSearch `recipes` index.

Default input:
    pipeline/01_process_data/cleaned/recipe_summaries_full.parquet

Usage:
    python pipeline/04_evaluate_opensearch/index_processed_summaries.py
    python pipeline/04_evaluate_opensearch/index_processed_summaries.py --input /path/to/file.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from opensearchpy.helpers import bulk

from clients import get_client

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BASE_DIR / "01_process_data" / "cleaned" / "recipe_summaries_full.parquet"
INDEX = "recipes"
REQUIRED_COLUMNS = {
    "recipe_uid",
    "author_id",
    "flow_id",
    "version_no",
    "step_count",
    "payload_json",
    "text_no_comments",
    "connectors",
    "actions",
    "input_fields",
    "datapill_fields",
}


def _to_str_list(val) -> list[str]:
    if hasattr(val, "__iter__") and not isinstance(val, str):
        return [str(v) for v in val]
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
    return [p.strip() for p in s.split(",") if p.strip()]


def _parse_payload(raw) -> dict | str:
    if pd.isna(raw):
        return {}
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, ValueError):
        return str(raw)


def run(input_path: Path, chunk_size: int) -> tuple[int, int]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input parquet not found: {input_path}")

    df = pd.read_parquet(input_path)
    missing = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise ValueError(
            "Input parquet is missing required columns: " + ", ".join(missing)
        )

    actions = [
        {
            "_index": INDEX,
            "_id": row["recipe_uid"],
            "_source": {
                "author_id": int(row["author_id"]),
                "flow_id": int(row["flow_id"]),
                "version_no": int(row["version_no"]),
                "step_count": int(row["step_count"]),
                "text_no_comments": row["text_no_comments"] if pd.notna(row["text_no_comments"]) else "",
                "payload": _parse_payload(row["payload_json"]),
                "connectors": _to_str_list(row["connectors"]),
                "actions": _to_str_list(row["actions"]),
                "input_fields": _to_str_list(row["input_fields"]),
                "datapill_fields": _to_str_list(row["datapill_fields"]),
            },
        }
        for _, row in df.iterrows()
    ]

    success, errors = bulk(
        get_client(),
        actions,
        chunk_size=chunk_size,
        raise_on_error=False,
    )
    failed = len(errors) if isinstance(errors, list) else 0
    return success, failed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--chunk-size", type=int, default=200)
    args = parser.parse_args()

    inserted, failed = run(args.input, args.chunk_size)
    print(f"Done — indexed: {inserted}  failed: {failed}")
    if failed:
        print("Re-run to retry failed documents, or inspect the OpenSearch response.")


if __name__ == "__main__":
    main()
