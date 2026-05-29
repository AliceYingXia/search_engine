"""
ingest_from_ndjson.py
=====================

Transforms and ingests recipes.ndjson into OpenSearch.

For each document the script produces two bulk actions:

  1. ``recipes`` index  — text/keyword fields, with field renames:
       - ``connectors_used``  →  ``connectors``
       - ``search_text``      →  ``text_no_comments``
       - ``payload``          reconstructed as the full source document
                              (minus the embedding vector)
       - ``embedding``        stripped (lives in its own index)

  2. ``embeddings_qwen3_embedding_8b_full`` index  — just the 4096-dim
     vector keyed by the same ``_id``, so no re-embedding is needed.

Usage
-----
    python pipeline/04_evaluate_opensearch/ingest_from_ndjson.py \\
        --ndjson pipeline/05_demo/recipes.ndjson

    # dry run — parse & transform without writing to OpenSearch
    python pipeline/04_evaluate_opensearch/ingest_from_ndjson.py \\
        --ndjson pipeline/05_demo/recipes.ndjson --dry-run

Environment variables
---------------------
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import argparse
import json
import sys
from pathlib import Path

from opensearchpy.helpers import bulk

from clients import get_client
from create_opensearch_indices import IndexManager

RECIPES_INDEX    = "recipes"
EMBEDDINGS_INDEX = "embeddings_qwen3_embedding_8b_full"
CHUNK_SIZE       = 200

# Fields that exist in ndjson but belong neither in the recipes index nor
# in the embeddings index (GPT annotations, redundant counts, etc.)
_EXTRA_FIELDS = {
    "gpt_description",
    "gpt_usage",
    "gpt_short_user_intent",
    "gpt_verbose_user_intent",
    "trigger_type",
    "trigger_provider",
    "action_count",
    "comments",
    "referenced_objects",
    "step_descriptions",
    "keyword_terms",
    "name",
    "recipe_uid",
}


def _transform(meta: dict, doc: dict) -> tuple[dict, dict | None]:
    """
    Return (recipe_action, embedding_action).

    embedding_action is None when the document has no embedding vector.
    """
    doc_id = meta["index"]["_id"]

    embedding = doc.get("embedding")

    # Build the payload stored in the recipes index: full doc minus vector
    payload = {k: v for k, v in doc.items() if k != "embedding"}

    recipe_doc = {
        "author_id":        doc.get("author_id"),
        "flow_id":          doc.get("flow_id"),
        "version_no":       doc.get("version_no"),
        "step_count":       doc.get("step_count"),
        "connectors":       doc.get("connectors_used", []),
        "actions":          doc.get("actions", []),
        "input_fields":     doc.get("input_fields", []),
        "datapill_fields":  doc.get("datapill_fields", []),
        "text_no_comments": doc.get("search_text", ""),
        "payload":          payload,
    }

    recipe_action = {
        "_index":  RECIPES_INDEX,
        "_id":     doc_id,
        "_source": recipe_doc,
    }

    embedding_action = None
    if embedding:
        embedding_action = {
            "_index":  EMBEDDINGS_INDEX,
            "_id":     doc_id,
            "_source": {"embedding": embedding},
        }

    return recipe_action, embedding_action


def _iter_ndjson(path: Path):
    """Yield (meta, doc) pairs from a bulk-format NDJSON file."""
    with path.open() as fh:
        lines = fh.readlines()

    if len(lines) % 2 != 0:
        sys.exit(f"ERROR: {path} has an odd number of lines — not valid bulk NDJSON")

    for i in range(0, len(lines), 2):
        meta = json.loads(lines[i])
        doc  = json.loads(lines[i + 1])
        yield meta, doc


def ingest(ndjson_path: Path, dry_run: bool = False, recreate: bool = False) -> tuple[int, int]:
    """
    Parse, transform, and bulk-ingest all documents.

    Returns (recipe_count, embedding_count).
    """
    recipe_actions    = []
    embedding_actions = []

    for meta, doc in _iter_ndjson(ndjson_path):
        ra, ea = _transform(meta, doc)
        recipe_actions.append(ra)
        if ea:
            embedding_actions.append(ea)

    total_docs = len(recipe_actions)
    total_embs = len(embedding_actions)
    print(f"Parsed   {total_docs} recipe documents")
    print(f"Parsed   {total_embs} embedding vectors")

    if dry_run:
        print("Dry run — skipping OpenSearch writes")
        return total_docs, total_embs

    client = get_client()

    if recreate:
        print("\nDropping and recreating indices ...")
        IndexManager(client, recreate=True).setup()

    print(f"\nIngesting into `{RECIPES_INDEX}` ...")
    ok, errors = bulk(client, recipe_actions, chunk_size=CHUNK_SIZE, raise_on_error=False)
    if errors:
        print(f"  WARNING: {len(errors)} recipe documents failed")
        for err in errors[:5]:
            print(f"    {err}")
    print(f"  {ok} / {total_docs} recipes indexed")

    print(f"\nIngesting into `{EMBEDDINGS_INDEX}` ...")
    ok_emb, errors_emb = bulk(client, embedding_actions, chunk_size=CHUNK_SIZE, raise_on_error=False)
    if errors_emb:
        print(f"  WARNING: {len(errors_emb)} embedding documents failed")
        for err in errors_emb[:5]:
            print(f"    {err}")
    print(f"  {ok_emb} / {total_embs} embeddings indexed")

    return ok, ok_emb


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ndjson",
        type=Path,
        default=Path(__file__).parent.parent / "05_demo" / "recipes.ndjson",
        help="Path to the bulk-format NDJSON file (default: pipeline/05_demo/recipes.ndjson)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and transform without writing to OpenSearch",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate both indices before ingesting (clears all existing data)",
    )
    args = parser.parse_args()

    if not args.ndjson.exists():
        sys.exit(f"ERROR: {args.ndjson} not found")

    ingest(args.ndjson, dry_run=args.dry_run, recreate=args.recreate)


if __name__ == "__main__":
    main()
