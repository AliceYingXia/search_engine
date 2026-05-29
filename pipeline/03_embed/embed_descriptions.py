"""
embed_descriptions.py

Embed GPT-generated description and usage fields for all recipes
using Qwen3-Embedding-8B via Baseten.

Embeds three text fields per recipe:
  - description
  - usage
  - description + usage (combined)

Run:
    python embed_descriptions.py

Output:
    pipeline/03_embed/embedded_descriptions.parquet
    columns: recipe_uid, description_qwen, usage_qwen, combined_qwen
"""

import math
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INPUT_PARQUET  = Path(__file__).parent.parent / "02_generate_descriptions" / "recipes_with_descriptions.parquet"
OUTPUT_PARQUET = Path(__file__).parent / "embedded_descriptions.parquet"

PREDICT_URL  = "https://model-qrjgv4v3.api.baseten.co/environments/production/predict"
API_KEY      = os.environ["BASETEN_API_KEY"]
DIMS         = 4096
BATCH_SIZE   = 64
MAX_RETRIES  = 5

INSTRUCTION = "Instruct: Retrieve the most relevant document for this search query.\nQuery: "

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def truncate_normalize(vec: list[float], dims: int) -> list[float]:
    kept = vec[:dims]
    norm = math.sqrt(sum(x * x for x in kept))
    return [x / norm for x in kept] if norm > 0 else kept


def embed_batch(texts: list[str], is_query: bool = False) -> list[list[float]]:
    inputs = [f"{INSTRUCTION}{t}" if is_query else t for t in texts]
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(
                PREDICT_URL,
                headers={"Authorization": f"Api-Key {API_KEY}"},
                json={"input": inputs, "model": "model", "encoding_format": "float"},
                timeout=300,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                vectors = [row["embedding"] for row in sorted(data["data"], key=lambda x: x["index"])]
            elif isinstance(data, list) and data and isinstance(data[0], list):
                vectors = data
            else:
                raise ValueError(f"Unexpected response format: {type(data)}")
            return [truncate_normalize(v, DIMS) for v in vectors]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"Failed after {MAX_RETRIES} attempts") from e
            sleep = min(2 ** attempt, 30)
            print(f"  retry in {sleep}s ({e.__class__.__name__})")
            time.sleep(sleep)


def embed_texts(texts: list[str], label: str) -> list[list[float]]:
    all_vectors = []
    total = len(texts)
    for start in range(0, total, BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        print(f"  {label}: {start + len(batch)}/{total}")
        all_vectors.extend(embed_batch(batch))
    return all_vectors

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Loading {INPUT_PARQUET}")
    df = pd.read_parquet(INPUT_PARQUET)[["recipe_uid", "description", "usage"]]
    print(f"  {len(df)} recipes")

    descriptions = df["description"].tolist()
    usages       = df["usage"].tolist()
    combined     = (df["description"] + "\n\n" + df["usage"]).tolist()

    print("\nEmbedding descriptions...")
    desc_vecs = embed_texts(descriptions, "description")

    print("\nEmbedding usages...")
    usage_vecs = embed_texts(usages, "usage")

    print("\nEmbedding combined...")
    combined_vecs = embed_texts(combined, "combined")

    out_df = pd.DataFrame({
        "recipe_uid":       df["recipe_uid"].tolist(),
        "description_qwen": desc_vecs,
        "usage_qwen":       usage_vecs,
        "combined_qwen":    combined_vecs,
    })
    out_df.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"\nDone. Saved to {OUTPUT_PARQUET}  ({len(out_df)} rows, dim={DIMS})")


if __name__ == "__main__":
    main()
