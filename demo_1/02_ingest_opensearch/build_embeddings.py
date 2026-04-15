"""
build_embeddings.py
===================

Production entrypoint for embedding recipes already indexed in OpenSearch.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import sys

from opensearchpy.helpers import bulk

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from common.clients import ensure_opensearch_connection, get_client  # noqa: E402
from common.logging_utils import get_logger  # noqa: E402
from common.models import DEFAULT_MODEL_NAME, EmbeddingModel  # noqa: E402

BATCH_SIZE = 20
logger = get_logger(__name__)


class EmbeddingPipeline:
    def __init__(self, model_name: str, client, missing_only: bool = False):
        self.model = EmbeddingModel(model_name)
        self.client = client
        self.missing_only = missing_only

    def _scroll_ids(self, index: str, source_fields: list[str] | None = None) -> list[dict]:
        body: dict = {"query": {"match_all": {}}, "size": 1000}
        body["_source"] = source_fields if source_fields is not None else False
        page = self.client.search(index=index, body=body, scroll="2m")
        scroll_id = page["_scroll_id"]
        hits = list(page["hits"]["hits"])
        try:
            while True:
                page = self.client.scroll(scroll_id=scroll_id, scroll="2m")
                scroll_id = page["_scroll_id"]
                batch = page["hits"]["hits"]
                if not batch:
                    break
                hits.extend(batch)
        finally:
            try:
                self.client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass
        return hits

    def _fetch_existing_ids(self) -> set[str]:
        try:
            return {hit["_id"] for hit in self._scroll_ids(self.model.table)}
        except Exception:
            return set()

    def _fetch_recipes(self) -> list[tuple[str, str]]:
        hits = self._scroll_ids("recipes", source_fields=[self.model.source_column])
        rows = [(hit["_id"], hit["_source"].get(self.model.source_column, "")) for hit in hits]
        if self.missing_only:
            existing = self._fetch_existing_ids()
            rows = [(uid, text) for uid, text in rows if uid not in existing]
        return rows

    def run(self) -> int:
        rows = self._fetch_recipes()
        logger.info("%s recipes to embed with %s", len(rows), self.model.name)
        inserted = 0
        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start: batch_start + BATCH_SIZE]
            uids = [row[0] for row in batch]
            texts = [row[1] for row in batch]
            try:
                vectors = self.model.embed_texts(texts)
            except Exception as exc:
                raise RuntimeError(
                    f"Embedding failed for batch starting at offset {batch_start}."
                ) from exc
            actions = [
                {"_index": self.model.table, "_id": uid, "_source": {"embedding": vec}}
                for uid, vec in zip(uids, vectors)
            ]
            try:
                bulk(self.client, actions, chunk_size=BATCH_SIZE, raise_on_error=True)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to write embedding batch starting at offset {batch_start}."
                ) from exc
            inserted += len(batch)
            logger.info("Embedded %s/%s", inserted, len(rows))
        return inserted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing-only", action="store_true")
    args = parser.parse_args()

    ensure_opensearch_connection()
    client = get_client()
    EmbeddingPipeline(DEFAULT_MODEL_NAME, client, missing_only=args.missing_only).run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
