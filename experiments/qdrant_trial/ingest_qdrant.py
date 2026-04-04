"""
ingest_qdrant.py

Create the Qdrant collection and ingest all embedded recipe chunks.

One collection stores all three dense vectors + sparse vector per point,
so each dense model can be queried independently without re-ingesting.

Run:
    python3 ingest_qdrant.py

Requires:
    pip install qdrant-client python-dotenv
"""

import json
import os
import glob
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
    PointStruct,
    SparseVector,
    PayloadSchemaType,
)

load_dotenv()

COLLECTION_NAME = "workato_recipes"

# Deterministic UUID namespace — same chunk_id always maps to the same point ID
_UUID_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def point_id(chunk_id: str) -> str:
    """Convert a string chunk_id to a deterministic UUID for Qdrant."""
    return str(uuid.uuid5(_UUID_NS, chunk_id))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def connect() -> QdrantClient:
    url     = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if not url:
        raise ValueError("QDRANT_URL not set in .env")
    client = QdrantClient(url=url, api_key=api_key or None)
    print(f"Connected to Qdrant: {url}")
    return client


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def create_collection(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        print(f"Collection '{COLLECTION_NAME}' already exists — skipping creation.")
        return

    print(f"Creating collection '{COLLECTION_NAME}'...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense_bge":    VectorParams(size=1024, distance=Distance.COSINE),
            "dense_voyage": VectorParams(size=1024, distance=Distance.COSINE),
            "dense_openai": VectorParams(size=3072, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse_bge": SparseVectorParams(
                index=SparseIndexParams(on_disk=False)
            )
        },
    )

    # Payload indexes for filtering
    for field, schema in [
        ("chunk_type",   PayloadSchemaType.KEYWORD),
        ("recipe_name",  PayloadSchemaType.KEYWORD),
        ("provider",     PayloadSchemaType.KEYWORD),
        ("keyword",      PayloadSchemaType.KEYWORD),
        ("source_file",  PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(COLLECTION_NAME, field, schema)

    print(f"  Collection created with indexes on: chunk_type, recipe_name, provider, keyword, source_file")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def build_point(chunk: dict) -> PointStruct:
    vectors = chunk["vectors"]
    payload = {k: v for k, v in chunk.items() if k != "vectors"}

    return PointStruct(
        id=point_id(chunk["chunk_id"]),
        vector={
            "dense_bge":    vectors["dense_bge"],
            "dense_voyage": vectors["dense_voyage"],
            "dense_openai": vectors["dense_openai"],
            "sparse_bge": SparseVector(
                indices=vectors["sparse_bge"]["indices"],
                values=vectors["sparse_bge"]["values"],
            ),
        },
        payload=payload,
    )


UPSERT_BATCH_SIZE = 64


def ingest_file(client: QdrantClient, embedded_path: str):
    basename = os.path.basename(embedded_path).replace("_embedded.json", "")
    print(f"Ingesting: {basename}")

    with open(embedded_path) as f:
        chunks = json.load(f)

    points = [build_point(c) for c in chunks]

    for i in range(0, len(points), UPSERT_BATCH_SIZE):
        batch = points[i : i + UPSERT_BATCH_SIZE]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)

    print(f"  {len(points)} points upserted "
          f"({sum(1 for c in chunks if c['chunk_type'] == 'recipe')} recipe, "
          f"{sum(1 for c in chunks if c['chunk_type'] == 'step')} step)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = connect()
    create_collection(client)
    print()

    embedded_dir = os.path.join(os.path.dirname(__file__), "example", "embedded")
    embedded_files = sorted(glob.glob(os.path.join(embedded_dir, "*_embedded.json")))

    if not embedded_files:
        print("No embedded files found in example/embedded/")
        return

    for path in embedded_files:
        ingest_file(client, path)

    print()
    info = client.get_collection(COLLECTION_NAME)
    print(f"Collection '{COLLECTION_NAME}': {info.points_count} total points")
    print("\nDone.")


if __name__ == "__main__":
    main()
