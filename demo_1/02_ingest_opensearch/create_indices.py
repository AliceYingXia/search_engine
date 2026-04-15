"""
create_indices.py
=================

Production entrypoint for creating the OpenSearch indices used by Demo 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sys

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from common.clients import ensure_opensearch_connection, get_client  # noqa: E402
from common.index_definitions import EMBEDDING_INDICES, RECIPES_BODY, RECIPES_INDEX, embedding_body  # noqa: E402


class IndexManager:
    def __init__(self, client, recreate: bool = False):
        self.client = client
        self.recreate = recreate

    def _create(self, name: str, body: dict) -> None:
        exists = self.client.indices.exists(index=name)
        if exists:
            if self.recreate:
                self.client.indices.delete(index=name)
                print(f"  dropped  : {name}")
            else:
                print(f"  exists   : {name}  (skipping — use --recreate to drop and rebuild)")
                return
        self.client.indices.create(index=name, body=body)
        print(f"  created  : {name}")

    def setup(self) -> None:
        print("Creating recipes index ...")
        self._create(RECIPES_INDEX, RECIPES_BODY)
        print("\nCreating embedding indices ...")
        for name, dim in EMBEDDING_INDICES:
            self._create(name, embedding_body(dim))
        print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    ensure_opensearch_connection()
    IndexManager(get_client(), recreate=args.recreate).setup()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
