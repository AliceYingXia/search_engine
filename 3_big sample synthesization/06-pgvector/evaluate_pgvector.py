"""
evaluate_pgvector.py
====================

Evaluates pgvector dense search for Category 1 and Category 2 queries.

Ground truth: `strong_list` column from the eval datasets (recipe UIDs that
both GPT-5.2 and Claude rated as "Strongly Related").  The eval datasets were
built against the same 115 seed recipes that are loaded into pgvector, so the
ground truth is fully covered by the index.

Metrics
-------
    Precision@k  = |retrieved[:k] ∩ relevant| / k
    Recall@k     = |retrieved[:k] ∩ relevant| / |relevant|
    MRR          = mean(1 / rank_of_first_relevant)   (0 if none in top-k)

Usage
-----
    python 06-pgvector/evaluate_pgvector.py
    python 06-pgvector/evaluate_pgvector.py --model text-embedding-3-small
    python 06-pgvector/evaluate_pgvector.py --model text-embedding-3-large --k 10
    python 06-pgvector/evaluate_pgvector.py --model "BAAI/bge-m3" "Qwen/Qwen3-Embedding-0.6B"
    python 06-pgvector/evaluate_pgvector.py --model "Qwen/Qwen3-Embedding-0.6B" "Qwen/Qwen3-Embedding-0.6B+instruct"

Notes
-----
    - Results are appended to eval_summary_k{k}.csv (existing rows for the
      same model are replaced, all others are preserved).
    - The "+instruct" variant reuses the same document vectors as the base
      model but prepends a task instruction to each query at evaluation time.

Environment variables
---------------------
    BASE_URL, API_KEY   — OpenAI-compatible gateway (text-embedding-3-*)
    HF_TOKEN            — HuggingFace token for gated model downloads (optional)
"""

import argparse
import os
from pathlib import Path

import pandas as pd
import psycopg2
import requests as _requests
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
EVAL_DIR  = BASE_DIR.parent / "05_sythesize_eval_dataset"
CAT1_PATH = EVAL_DIR / "category1_eval_dataset.csv"
CAT2_PATH = EVAL_DIR / "category2_eval_dataset.csv"

# ── Model registry ────────────────────────────────────────────────────────────
# Optional fields:
#   hf_model    — actual HuggingFace model ID to load (defaults to the key)
#   instruction — query-side prompt prefix; applied only during evaluation,
#                 not during ingestion (document vectors are unchanged)
MODEL_CONFIG = {
    "text-embedding-3-small": {
        "table":   "embeddings_text_embedding_3_small",
        "backend": "openai",
    },
    "text-embedding-3-large": {
        "table":   "embeddings_text_embedding_3_large",
        "backend": "openai",
    },
    "BAAI/bge-m3": {
        "table":   "embeddings_bge_m3",
        "backend": "huggingface",
    },
    "Qwen/Qwen3-Embedding-0.6B": {
        "table":       "embeddings_qwen3_embedding_0_6b",
        "backend":     "huggingface",
    },
    "Qwen/Qwen3-Embedding-0.6B+instruct": {
        "table":       "embeddings_qwen3_embedding_0_6b",   # same doc vectors
        "backend":     "huggingface",
        "hf_model":    "Qwen/Qwen3-Embedding-0.6B",
        "instruction": (
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    },
    "intfloat/multilingual-e5-large-instruct": {
        "table":       "embeddings_multilingual_e5_large_instruct",
        "backend":     "huggingface",
        "instruction": (
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    },
    "Qwen/Qwen3-Embedding-4B": {
        "table":       "embeddings_qwen3_embedding_4b",
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-3yd060v3.api.baseten.co/environments/production/predict",
    },
    "Qwen/Qwen3-Embedding-4B+instruct": {
        "table":       "embeddings_qwen3_embedding_4b",   # same doc vectors
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-3yd060v3.api.baseten.co/environments/production/predict",
        "instruction": (
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    },
    "mixedbread-ai/mxbai-embed-large-v1": {
        "table":       "embeddings_mxbai_embed_large_v1",
        "backend":     "baseten_predict",
        "predict_url": "https://model-qvvpmnjq.api.baseten.co/environments/production/predict",
    },
    "Qwen/Qwen3-Embedding-8B": {
        "table":       "embeddings_qwen3_embedding_8b",
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-wom8ozkq.api.baseten.co/environments/production/predict",
    },
    "Qwen/Qwen3-Embedding-8B+instruct": {
        "table":       "embeddings_qwen3_embedding_8b",   # same doc vectors
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-wom8ozkq.api.baseten.co/environments/production/predict",
        "instruction": (
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    },
    # ── No-comments variants ───────────────────────────────────────────────────
    "text-embedding-3-large_nc": {
        "table":      "embeddings_text_embedding_3_large_nc",
        "backend":    "openai",
        "model_name": "text-embedding-3-large",
    },
    "Qwen/Qwen3-Embedding-8B+instruct_nc": {
        "table":       "embeddings_qwen3_embedding_8b_nc",
        "backend":     "baseten_predict_batch",
        "predict_url": "https://model-wom8ozkq.api.baseten.co/environments/production/predict",
        "instruction": (
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    },
}

# ── API clients ───────────────────────────────────────────────────────────────
_openai_client = OpenAI(
    base_url=os.environ["BASE_URL"],
    api_key=os.environ["API_KEY"],
)

_baseten_client = OpenAI(
    base_url=os.environ["BASETEN_BASE_URL"],
    api_key=os.environ["BASETEN_API_KEY"],
)

DSN = dict(
    host     = os.getenv("PGHOST",     "localhost"),
    port     = int(os.getenv("PGPORT", "5432")),
    dbname   = os.getenv("PGDATABASE", "postgres"),
    user     = os.getenv("PGUSER",     "postgres"),
    password = os.getenv("PGPASSWORD", "postgres"),
)

# ── HuggingFace model cache (downloaded once, reused for the process lifetime) ─
_hf_models: dict[str, SentenceTransformer] = {}

def get_hf_model(model: str) -> SentenceTransformer:
    if model not in _hf_models:
        print(f"Loading {model} from HuggingFace (downloading if not cached) ...")
        hf_token = os.getenv("HF_TOKEN")
        _hf_models[model] = SentenceTransformer(model, token=hf_token)
    return _hf_models[model]


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_uid_list(s) -> list[str]:
    """Parse a comma-separated string of recipe UIDs."""
    if pd.isna(s) or str(s).strip() == "":
        return []
    return [uid.strip() for uid in str(s).split(",") if uid.strip()]


def _parse_predict_embedding(response_json) -> list[float]:
    """Parse an embedding from a Baseten /predict response."""
    if isinstance(response_json, list):
        return response_json
    if isinstance(response_json, dict):
        if "embedding" in response_json:
            return response_json["embedding"]
        if "data" in response_json:
            return response_json["data"][0]["embedding"]
    raise ValueError(f"Unexpected /predict response format: {type(response_json)}")


def _parse_predict_embeddings_batch(response_json) -> list[list[float]]:
    """Parse a list of embeddings from a Baseten /predict batch response."""
    if isinstance(response_json, list) and response_json and isinstance(response_json[0], list):
        return response_json
    if isinstance(response_json, dict) and "data" in response_json:
        return [d["embedding"] for d in sorted(response_json["data"], key=lambda x: x["index"])]
    raise ValueError(f"Unexpected /predict batch response format: {type(response_json)}")


def embed_query(text: str, cfg: dict) -> list[float]:
    instruction = cfg.get("instruction")
    if cfg["backend"] == "openai":
        model = cfg.get("model_name") or next(k for k, v in MODEL_CONFIG.items() if v is cfg)
        resp = _openai_client.embeddings.create(model=model, input=[text])
        return resp.data[0].embedding
    elif cfg["backend"] == "baseten":
        query = instruction + text if instruction else text
        resp = _baseten_client.embeddings.create(model="baseten-model", input=[query])
        return resp.data[0].embedding
    elif cfg["backend"] == "baseten_predict":
        query = instruction + text if instruction else text
        r = _requests.post(
            cfg["predict_url"],
            headers={"Authorization": f"Api-Key {os.environ['BASETEN_API_KEY']}"},
            json={"input": query, "model": "model", "encoding_format": "float"},
        )
        r.raise_for_status()
        return _parse_predict_embedding(r.json())
    elif cfg["backend"] == "baseten_predict_batch":
        query = instruction + text if instruction else text
        r = _requests.post(
            cfg["predict_url"],
            headers={"Authorization": f"Api-Key {os.environ['BASETEN_API_KEY']}"},
            json={"input": [query], "model": "model", "encoding_format": "float"},
        )
        r.raise_for_status()
        return _parse_predict_embeddings_batch(r.json())[0]
    else:
        hf_model_name = cfg.get("hf_model") or next(k for k, v in MODEL_CONFIG.items() if v is cfg)
        hf_model = get_hf_model(hf_model_name)
        kwargs: dict = {"normalize_embeddings": True}
        if instruction:
            kwargs["prompt"] = instruction
        return hf_model.encode([text], **kwargs)[0].tolist()


def search_pgvector(cur, embedding: list[float], table: str, k: int) -> list[str]:
    vec_str = "[" + ",".join(map(str, embedding)) + "]"
    cur.execute(
        f"""
        SELECT r.recipe_uid
        FROM   {table} e
        JOIN   recipes r USING (recipe_uid)
        ORDER  BY e.embedding <=> %s::vector
        LIMIT  %s
        """,
        (vec_str, k),
    )
    return [row[0] for row in cur.fetchall()]


# ── Metric functions ──────────────────────────────────────────────────────────
def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    hits = sum(1 for uid in retrieved[:k] if uid in relevant)
    return hits / k


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for uid in retrieved[:k] if uid in relevant)
    return hits / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, uid in enumerate(retrieved, 1):
        if uid in relevant:
            return 1.0 / rank
    return 0.0


# ── Per-category evaluation ───────────────────────────────────────────────────
def evaluate_category(
    df: pd.DataFrame,
    cur,
    cfg: dict,
    k: int,
    category_name: str,
) -> pd.DataFrame:
    table = cfg["table"]
    records = []
    skipped = 0

    for _, row in df.iterrows():
        strong_set = set(parse_uid_list(row["strong_list"]))
        weak_set   = set(parse_uid_list(row["weak_list"]))

        if not strong_set:
            skipped += 1
            continue

        embedding = embed_query(row["query"], cfg)
        retrieved = search_pgvector(cur, embedding, table, k)

        records.append({
            "category":         category_name,
            "query_id":         row["query_id"],
            "query":            row["query"],
            "n_strong":         len(strong_set),
            "n_weak":           len(weak_set),
            f"precision@{k}":   precision_at_k(retrieved, strong_set, k),
            f"recall@{k}":      recall_at_k(retrieved, strong_set, k),
            "rr":               reciprocal_rank(retrieved, strong_set),
            "strong_hits_top5": sum(1 for u in retrieved[:k] if u in strong_set),
            "weak_hits_top5":   sum(1 for u in retrieved[:k] if u in weak_set),
            "retrieved":        ", ".join(retrieved),
            "strong_list":      ", ".join(sorted(strong_set)),
            "weak_list":        ", ".join(sorted(weak_set)),
        })

    if skipped:
        print(f"  Skipped {skipped} queries (empty strong list)")

    return pd.DataFrame(records)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        nargs="+",
        choices=list(MODEL_CONFIG),
        default=["text-embedding-3-large"],
        help="Embedding model(s) to evaluate (default: text-embedding-3-large)",
    )
    parser.add_argument(
        "--k", type=int, default=5,
        help="Number of results to retrieve (default: 5)",
    )
    args = parser.parse_args()

    k = args.k

    cat1_df = pd.read_csv(CAT1_PATH)
    cat2_df = pd.read_csv(CAT2_PATH)
    print(f"Category 1: {len(cat1_df)} queries  |  Category 2: {len(cat2_df)} queries")

    conn = psycopg2.connect(**DSN)
    cur  = conn.cursor()

    summary_rows = []

    for model in args.model:
        cfg     = MODEL_CONFIG[model]
        backend = cfg["backend"]
        instruction_note = " +instruction" if cfg.get("instruction") else ""

        print(f"{'='*60}")
        print(f"Model: {model}  |  backend={backend}{instruction_note}  |  k={k}")
        print(f"{'='*60}")

        all_results = []

        for cat_name, df in [("Category 1", cat1_df), ("Category 2", cat2_df)]:
            print(f"\n── {cat_name} ──")
            results = evaluate_category(df, cur, cfg, k, cat_name)
            all_results.append(results)

            p          = results[f"precision@{k}"].mean()
            r          = results[f"recall@{k}"].mean()
            mrr        = results["rr"].mean()
            avg_strong = results["strong_hits_top5"].mean()
            avg_weak   = results["weak_hits_top5"].mean()

            print(f"  Queries evaluated    : {len(results)}")
            print(f"  Precision@{k}         : {p:.4f}")
            print(f"  Recall@{k}            : {r:.4f}")
            print(f"  MRR                  : {mrr:.4f}")
            print(f"  Avg strong hits@{k}   : {avg_strong:.4f}")
            print(f"  Avg weak hits@{k}     : {avg_weak:.4f}")

            summary_rows.append({
                "model":               model,
                "category":            cat_name,
                "n_queries":           len(results),
                f"precision@{k}":       round(p, 4),
                f"recall@{k}":          round(r, 4),
                "MRR":                 round(mrr, 4),
                f"avg_strong_hits@{k}": round(avg_strong, 4),
                f"avg_weak_hits@{k}":   round(avg_weak, 4),
            })

        # Save per-query detail
        combined  = pd.concat(all_results, ignore_index=True)
        safe_name = model.replace("/", "_").replace("-", "_")
        out_path  = BASE_DIR / f"eval_results_{safe_name}_k{k}.csv"
        combined.to_csv(out_path, index=False)
        print(f"\nDetailed results → {out_path.name}")

    cur.close()
    conn.close()

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))

    summary_path = BASE_DIR / f"eval_summary_k{k}.csv"
    if summary_path.exists():
        existing = pd.read_csv(summary_path)
        existing = existing[~existing["model"].isin(args.model)]
        summary_df = pd.concat([existing, summary_df], ignore_index=True)
    summary_df.to_csv(summary_path, index=False)
    print(f"\nSummary saved → {summary_path.name}")


if __name__ == "__main__":
    main()
