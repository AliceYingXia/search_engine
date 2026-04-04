"""
embed_chunks.py

Embed all chunks using three models:
  - BGE-M3      (local)   → dense_bge (1024-dim) + sparse_bge
  - voyage-code-3  (API)  → dense_voyage (1024-dim)
  - text-embedding-3-large (API) → dense_openai (3072-dim)

Outputs one embedded file per recipe into example/embedded/.

Run:
    python3 embed_chunks.py

Requires:
    pip install FlagEmbedding voyageai openai python-dotenv
"""

import json
import os
import glob

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# BGE-M3 (local)
# ---------------------------------------------------------------------------

# FlagEmbedding 1.3.x uses is_torch_fx_available which was removed in
# transformers 5.x. Patch it back before importing FlagEmbedding.
import transformers.utils.import_utils as _tiu
if not hasattr(_tiu, "is_torch_fx_available"):
    _tiu.is_torch_fx_available = lambda: False

from FlagEmbedding import BGEM3FlagModel

BGE_BATCH_SIZE = 16


def load_bge_model():
    print("Loading BGE-M3...")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    print("  BGE-M3 ready.")
    return model


def sparse_to_qdrant(lexical_weights: dict) -> dict:
    """Convert BGE-M3 lexical_weights to Qdrant sparse format."""
    indices = [int(k) for k in lexical_weights.keys()]
    values  = [float(lexical_weights[k]) for k in lexical_weights.keys()]
    return {"indices": indices, "values": values}


def embed_bge(model, texts: list) -> list:
    """Returns list of {"dense_bge": [...], "sparse_bge": {...}} per text."""
    output = model.encode(
        texts,
        batch_size=BGE_BATCH_SIZE,
        max_length=8192,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    return [
        {
            "dense_bge":  d.tolist(),
            "sparse_bge": sparse_to_qdrant(s),
        }
        for d, s in zip(output["dense_vecs"], output["lexical_weights"])
    ]


# ---------------------------------------------------------------------------
# Voyage AI — voyage-code-3 (API)
# ---------------------------------------------------------------------------

VOYAGE_BATCH_SIZE = 128


def load_voyage_client():
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        print("  VOYAGE_API_KEY not set — skipping voyage-code-3.")
        return None
    import voyageai
    client = voyageai.Client(api_key=api_key)
    print("  Voyage AI client ready.")
    return client


def embed_voyage(client, texts: list) -> list:
    """Returns list of dense_voyage vectors (1024-dim) per text."""
    vectors = []
    for i in range(0, len(texts), VOYAGE_BATCH_SIZE):
        batch = texts[i : i + VOYAGE_BATCH_SIZE]
        result = client.embed(batch, model="voyage-code-3", input_type="document")
        vectors.extend(result.embeddings)
    return vectors


# ---------------------------------------------------------------------------
# OpenAI — text-embedding-3-large (API)
# ---------------------------------------------------------------------------

OPENAI_BATCH_SIZE = 512


def load_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("  OPENAI_API_KEY not set — skipping text-embedding-3-large.")
        return None
    import ssl
    import httpx
    import certifi
    from openai import OpenAI
    # macOS Homebrew Python does not trust the system cert store by default;
    # build an explicit SSL context from certifi's bundle.
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    http_client = httpx.Client(verify=ssl_ctx)
    client = OpenAI(api_key=api_key, http_client=http_client)
    print("  OpenAI client ready.")
    return client


def embed_openai(client, texts: list) -> list:
    """Returns list of dense_openai vectors (3072-dim) per text."""
    vectors = []
    for i in range(0, len(texts), OPENAI_BATCH_SIZE):
        batch = texts[i : i + OPENAI_BATCH_SIZE]
        response = client.embeddings.create(
            input=batch,
            model="text-embedding-3-large",
        )
        response.data.sort(key=lambda x: x.index)
        vectors.extend([item.embedding for item in response.data])
    return vectors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    chunks_dir = os.path.join(os.path.dirname(__file__), "example", "chunks")
    output_dir = os.path.join(os.path.dirname(__file__), "example", "embedded")
    os.makedirs(output_dir, exist_ok=True)

    chunk_files = sorted(glob.glob(os.path.join(chunks_dir, "*_chunks.json")))
    if not chunk_files:
        print("No chunk files found in example/chunks/")
        return

    print("Initialising models...")
    bge_model     = load_bge_model()
    voyage_client = load_voyage_client()
    openai_client = load_openai_client()
    print()

    for chunk_path in chunk_files:
        basename = os.path.basename(chunk_path).replace("_chunks.json", "")
        print(f"Processing: {basename}")

        with open(chunk_path) as f:
            chunks = json.load(f)

        texts = [c["text"] for c in chunks]

        print(f"  [{len(texts)} chunks] embedding with BGE-M3...")
        bge_results = embed_bge(bge_model, texts)

        voyage_results = None
        if voyage_client:
            print(f"  [{len(texts)} chunks] embedding with voyage-code-3...")
            voyage_results = embed_voyage(voyage_client, texts)

        openai_results = None
        if openai_client:
            print(f"  [{len(texts)} chunks] embedding with text-embedding-3-large...")
            openai_results = embed_openai(openai_client, texts)

        embedded = []
        for i, chunk in enumerate(chunks):
            point = dict(chunk)
            point["vectors"] = {**bge_results[i]}
            if voyage_results:
                point["vectors"]["dense_voyage"] = voyage_results[i]
            if openai_results:
                point["vectors"]["dense_openai"] = openai_results[i]
            embedded.append(point)

        output_path = os.path.join(output_dir, f"{basename}_embedded.json")
        with open(output_path, "w") as f:
            json.dump(embedded, f, indent=2)

        active_models = ["BGE-M3"]
        if voyage_results:  active_models.append("voyage-code-3")
        if openai_results:  active_models.append("text-embedding-3-large")

        print(f"  -> {os.path.relpath(output_path)}")
        print(f"     models: {', '.join(active_models)}")
        print(f"     {len(embedded)} points: "
              f"{sum(1 for c in embedded if c['chunk_type'] == 'recipe')} recipe, "
              f"{sum(1 for c in embedded if c['chunk_type'] == 'step')} step\n")

    print("Done.")


if __name__ == "__main__":
    main()
