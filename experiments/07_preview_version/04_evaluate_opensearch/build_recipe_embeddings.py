"""
build_recipe_embeddings.py
=================

Reads recipes from the OpenSearch recipes index, generates embeddings,
and writes vectors into the corresponding embeddings_* index.
Mirrors pipeline/03_evaluate_postgre/add_embeddings.py.

Usage
-----
    # All ingestable models
    python pipeline/04_evaluate_opensearch/build_recipe_embeddings.py

    # Specific model(s)
    python pipeline/04_evaluate_opensearch/build_recipe_embeddings.py --model text-embedding-3-large
    python pipeline/04_evaluate_opensearch/build_recipe_embeddings.py --model "Qwen/Qwen3-Embedding-8B-full"

    # Only recipes not yet in the embedding index (safe to resume)
    python pipeline/04_evaluate_opensearch/build_recipe_embeddings.py --missing-only

Environment variables
---------------------
    BASE_URL, API_KEY              — OpenAI-compatible gateway (text-embedding-3-*)
    BASETEN_API_KEY                — Baseten API key
    HF_TOKEN                       — HuggingFace token (optional)
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

import argparse
import time

from opensearchpy.helpers import bulk

from clients import get_client
from models import MODEL_REGISTRY, EmbeddingModel

BATCH_SIZE = 20

INGESTABLE_MODELS = [
    name for name, cfg in MODEL_REGISTRY.items() if cfg.dimension is not None
]


class EmbeddingPipeline:
    """
    Reads recipes from OpenSearch, embeds them with one model, and writes
    the resulting vectors into the corresponding embeddings_* index.
    """

    def __init__(self, model_name: str, client, missing_only: bool = False):
        self.model        = EmbeddingModel(model_name)
        self.client       = client
        self.missing_only = missing_only

    def _scroll_ids(self, index: str, source_fields: list[str] | None = None) -> list[dict]:
        """Fetch all documents from an index via scroll (no 10K cap)."""
        body: dict = {"query": {"match_all": {}}, "size": 1000}
        if source_fields is not None:
            body["_source"] = source_fields
        else:
            body["_source"] = False

        page      = self.client.search(index=index, body=body, scroll="2m")
        scroll_id = page["_scroll_id"]
        hits      = list(page["hits"]["hits"])
        try:
            while True:
                page      = self.client.scroll(scroll_id=scroll_id, scroll="2m")
                scroll_id = page["_scroll_id"]
                batch     = page["hits"]["hits"]
                if not batch:
                    break
                hits.extend(batch)
        finally:
            try:
                self.client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass
        return hits

    def _fetch_recipes(self) -> list[tuple[str, str]]:
        """Return (recipe_uid, text) pairs to embed."""
        hits = self._scroll_ids("recipes", source_fields=[self.model.source_column])
        rows = [
            (hit["_id"], hit["_source"].get(self.model.source_column, ""))
            for hit in hits
        ]

        if self.missing_only:
            existing_ids = self._fetch_existing_ids()
            rows = [(uid, text) for uid, text in rows if uid not in existing_ids]

        return rows

    def _fetch_existing_ids(self) -> set[str]:
        """Return the set of recipe_uids already present in the embedding index."""
        try:
            hits = self._scroll_ids(self.model.table)
            return {hit["_id"] for hit in hits}
        except Exception:
            return set()

    def run(self) -> int:
        """Embed all (or missing) recipes. Returns the number of vectors written."""
        cfg = self.model.config
        print(f"\nModel : {self.model.name}  (dim={cfg.dimension}, backend={cfg.backend})")
        print(f"Index : {self.model.table}")
        print(f"Source: recipes.{self.model.source_column}")

        rows = self._fetch_recipes()
        print(f"{len(rows)} recipes to embed")

        if not rows:
            print("Nothing to do.")
            return 0

        total    = len(rows)
        inserted = 0

        for batch_start in range(0, total, BATCH_SIZE):
            batch   = rows[batch_start : batch_start + BATCH_SIZE]
            uids    = [r[0] for r in batch]
            texts   = [r[1] for r in batch]

            print(
                f"  [{batch_start + 1}–{batch_start + len(batch)}/{total}] embedding ...",
                end=" ",
                flush=True,
            )

            vectors = self.model.embed_texts(texts)

            actions = [
                {
                    "_index":  self.model.table,
                    "_id":     uid,
                    "_source": {"embedding": vec},
                }
                for uid, vec in zip(uids, vectors)
            ]
            bulk(self.client, actions, chunk_size=BATCH_SIZE, raise_on_error=True)
            inserted += len(batch)
            print(f"done ({inserted}/{total})")

            if cfg.backend == "openai":
                time.sleep(0.1)  # light rate-limit buffer

        print(f"Finished — {inserted} vectors written to `{self.model.table}`")
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
        help="Only embed recipes not yet present in the embedding index.",
    )
    args = parser.parse_args()

    models = INGESTABLE_MODELS if "all" in args.model else args.model
    mode   = "missing only" if args.missing_only else "all recipes"

    print(f"Models : {', '.join(models)}")
    print(f"Mode   : {mode}")

    client = get_client()

    for model_name in models:
        pipeline = EmbeddingPipeline(model_name, client, missing_only=args.missing_only)
        pipeline.run()


if __name__ == "__main__":
    main()
