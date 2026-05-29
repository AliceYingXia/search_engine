"""Phase 1.5 — Query Selection.

Selects 50 diverse queries per category by:
  1. Ranking all queries by length (longest first).
  2. Embedding every query with Qwen3-Embedding-8B via Baseten.
  3. Greedily selecting queries: a candidate is kept only if its cosine
     similarity to every already-selected query is ≤ 0.5.
     Shorter (later-ranked) queries are dropped when a longer query is too
     similar to them.
  4. Stopping once 50 queries are selected.

The selected queries are saved to output_path.
"""

import json
import os
from pathlib import Path

import numpy as np
import requests

_QWEN3_8B_URL   = "https://model-wom8ozkq.api.baseten.co/environments/production/predict"
_EMBED_BATCH_SZ = 20
_TARGET         = 50
_SIM_THRESHOLD  = 0.85


def select_queries(queries_path: Path, output_path: Path) -> list[dict]:
    """Load queries, deduplicate by embedding similarity, save 50 to output_path."""
    queries = json.loads(queries_path.read_text())
    print(f"Loaded {len(queries)} queries from {queries_path}")

    if len(queries) <= _TARGET:
        print(f"Only {len(queries)} queries — fewer than {_TARGET}, saving all without filtering.")
        output_path.write_text(json.dumps(queries, indent=2, ensure_ascii=False))
        print(f"Saved → {output_path}")
        return queries

    # ── 1. Rank by query length (longest first) ───────────────────────────────
    ranked = sorted(queries, key=lambda q: len(q["query"]), reverse=True)
    print(f"Ranked {len(ranked)} queries by length (longest first)")

    # ── 2. Embed all queries ──────────────────────────────────────────────────
    texts = [q["query"] for q in ranked]
    embeddings = _embed_texts(texts)
    print(f"Embedded {len(embeddings)} queries")

    # Normalise so dot product == cosine similarity
    vecs = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs = vecs / norms

    # ── 3. Greedy selection ───────────────────────────────────────────────────
    selected_indices: list[int] = []
    selected_vecs:    list[np.ndarray] = []

    for i, (q, vec) in enumerate(zip(ranked, vecs)):
        if selected_vecs:
            sims = np.dot(np.stack(selected_vecs), vec)
            if sims.max() > _SIM_THRESHOLD:
                continue
        selected_indices.append(i)
        selected_vecs.append(vec)
        if len(selected_indices) == _TARGET:
            break

    selected = [ranked[i] for i in selected_indices]
    print(
        f"Selected {len(selected)} queries after similarity filtering "
        f"(threshold={_SIM_THRESHOLD}, target={_TARGET})"
    )

    if len(selected) < _TARGET:
        print(
            f"WARNING: could only find {len(selected)} sufficiently diverse queries "
            f"(wanted {_TARGET}). Consider lowering the similarity threshold."
        )

    # ── 4. Print summary ──────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"SELECTED {len(selected)} QUERIES")
    print("=" * 70)
    for q in selected:
        print(f"  {q['query_id']:25s}  {q['query']}")
    print()

    output_path.write_text(json.dumps(selected, indent=2, ensure_ascii=False))
    print(f"Saved → {output_path}")
    return selected


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed all texts in batches using Qwen3-Embedding-8B via Baseten."""
    api_key = os.environ["BASETEN_API_KEY"]
    all_embeddings: list[list[float]] = []

    for start in range(0, len(texts), _EMBED_BATCH_SZ):
        batch = texts[start : start + _EMBED_BATCH_SZ]
        end   = start + len(batch)
        print(f"  Embedding [{start + 1}–{end}/{len(texts)}] ...", end=" ", flush=True)

        r = requests.post(
            _QWEN3_8B_URL,
            headers={"Authorization": f"Api-Key {api_key}"},
            json={"input": batch, "model": "model", "encoding_format": "float"},
            timeout=120,
        )
        r.raise_for_status()
        all_embeddings.extend(_parse_batch_response(r.json()))
        print("done")

    return all_embeddings


def _parse_batch_response(response_json) -> list[list[float]]:
    if isinstance(response_json, list) and response_json and isinstance(response_json[0], list):
        return response_json
    if isinstance(response_json, dict) and "data" in response_json:
        return [d["embedding"] for d in sorted(response_json["data"], key=lambda x: x["index"])]
    raise ValueError(f"Unexpected Baseten response format: {type(response_json)}")
