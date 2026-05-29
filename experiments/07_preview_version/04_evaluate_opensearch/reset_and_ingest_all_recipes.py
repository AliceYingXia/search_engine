"""
reset_and_ingest_all_recipes.py
===============================

Recreates the application OpenSearch indices and ingests the full cleaned
recipe corpus, then builds dense vectors for a selected embedding model.

This script is intentionally separate from the existing pipeline selection flow.
It uses the full processed parquet instead of pipeline/02_synthesize_data/
recipes_for_pgvector.csv.

Default input:
    pipeline/01_process_data/cleaned/recipe_summaries_full.parquet

Usage:
    python pipeline/04_evaluate_opensearch/reset_and_ingest_all_recipes.py
    python pipeline/04_evaluate_opensearch/reset_and_ingest_all_recipes.py --input /path/to/file.parquet
    python pipeline/04_evaluate_opensearch/reset_and_ingest_all_recipes.py --model text-embedding-3-small
    python pipeline/04_evaluate_opensearch/reset_and_ingest_all_recipes.py --skip-recreate
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from build_recipe_embeddings import EmbeddingPipeline
from clients import get_client
from create_opensearch_indices import IndexManager
from index_processed_summaries import DEFAULT_INPUT, run as ingest_processed_summaries
from models import MODEL_REGISTRY

DEFAULT_MODEL = "text-embedding-3-small"
INGESTABLE_MODELS = [
    name for name, cfg in MODEL_REGISTRY.items() if cfg.dimension is not None
]


def _count_recipes(input_path: Path) -> int:
    return len(pd.read_parquet(input_path, columns=["recipe_uid"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Parquet file containing the full processed recipe corpus.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=200,
        help="Bulk indexing chunk size.",
    )
    parser.add_argument(
        "--model",
        choices=INGESTABLE_MODELS,
        default=DEFAULT_MODEL,
        help=f"Embedding model to build after ingesting recipes (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--skip-recreate",
        action="store_true",
        help="Keep existing app indices and only ingest documents.",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Only ingest recipes; do not call the embedding API.",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="When building embeddings, only embed recipes missing from the target embedding index.",
    )
    args = parser.parse_args()

    client = get_client()
    recipe_count = _count_recipes(args.input)

    if args.skip_recreate:
        print("Skipping index recreation.")
    else:
        print("Recreating application indices ...")
        IndexManager(client, recreate=True, models=[args.model]).setup()

    print(f"\nIngesting {recipe_count} processed recipes from: {args.input}")
    inserted, failed = ingest_processed_summaries(args.input, args.chunk_size)
    print(f"Done — indexed: {inserted}  failed: {failed}")
    if failed:
        print("Re-run to retry failed documents, or inspect the OpenSearch response.")
        return

    if args.skip_embeddings:
        print("Skipping embedding generation.")
        return

    print(f"\nBuilding embeddings with {args.model} ...")
    written = EmbeddingPipeline(
        args.model,
        client,
        missing_only=args.missing_only,
    ).run()
    print(f"Embedding ingest complete — wrote {written} vectors to {MODEL_REGISTRY[args.model].table}")


if __name__ == "__main__":
    main()
