"""
search_qdrant.py

Test semantic search against the workato_recipes collection using each
embedding model independently. No filters applied — both recipe and step
chunks compete freely (Approach 1).

Usage:
    # Single query
    python3 search_qdrant.py --query "create Salesforce opportunity" --model bge
    python3 search_qdrant.py --query "create Salesforce opportunity" --model sparse
    python3 search_qdrant.py --query "create Salesforce opportunity" --model voyage
    python3 search_qdrant.py --query "create Salesforce opportunity" --model openai
    python3 search_qdrant.py --query "create Salesforce opportunity" --model all

    # Run all 5 benchmark queries (results + scores)
    python3 search_qdrant.py --benchmark --model all

    # Scores only — no per-result output
    python3 search_qdrant.py --benchmark --model all --score-only

Models:  bge | sparse | voyage | openai | all
  bge    — BGE-M3 dense (1024-dim, local)
  sparse — BGE-M3 sparse (learned token weights, local)
  voyage — voyage-code-3 dense (1024-dim, API)
  openai — text-embedding-3-large dense (3072-dim, API)
  all    — all four models
"""

import argparse
import json
import os
import ssl

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector

load_dotenv()

COLLECTION_NAME = "workato_recipes"
TOP_K = 5
GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "benchmark_golden.json")


# ---------------------------------------------------------------------------
# Query embedding — one function per model
# ---------------------------------------------------------------------------

def _load_bge():
    import transformers.utils.import_utils as _tiu
    if not hasattr(_tiu, "is_torch_fx_available"):
        _tiu.is_torch_fx_available = lambda: False
    from FlagEmbedding import BGEM3FlagModel
    return BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)


def embed_query_bge(text: str) -> list:
    model = _load_bge()
    output = model.encode([text], return_dense=True, return_sparse=False)
    return output["dense_vecs"][0].tolist()


def embed_query_bge_sparse(text: str) -> SparseVector:
    model = _load_bge()
    output = model.encode([text], return_dense=False, return_sparse=True)
    weights = output["lexical_weights"][0]
    indices = [int(k) for k in weights.keys()]
    values  = [float(weights[k]) for k in weights.keys()]
    return SparseVector(indices=indices, values=values)


def embed_query_voyage(text: str) -> list:
    import voyageai
    client = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))
    result = client.embed([text], model="voyage-code-3", input_type="query")
    return result.embeddings[0]


def embed_query_openai(text: str) -> list:
    import httpx
    import certifi
    from openai import OpenAI
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    http_client = httpx.Client(verify=ssl_ctx)
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), http_client=http_client)
    response = client.embeddings.create(input=[text], model="text-embedding-3-large")
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Golden answers
# ---------------------------------------------------------------------------

def load_golden() -> dict:
    """Return {label: set(golden_chunk_ids)} if the file exists, else {}."""
    if not os.path.exists(GOLDEN_PATH):
        return {}
    with open(GOLDEN_PATH) as f:
        data = json.load(f)
    return {item["label"]: set(item["golden_chunk_ids"]) for item in data}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(client: QdrantClient, vector_name: str, vector: list,
           model_label: str, query: str, silent: bool = False) -> list[str]:
    """Run a search and return the ordered list of retrieved chunk_ids."""
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        using=vector_name,
        limit=TOP_K,
        with_payload=True,
    )

    if not silent:
        print(f"\n{'='*60}")
        print(f"Model: {model_label}  |  vector: {vector_name}  |  query: \"{query}\"")
        print(f"{'='*60}")
        for i, hit in enumerate(results.points, 1):
            p = hit.payload
            chunk_type = p.get("chunk_type", "")
            label_str  = f"[{chunk_type}]"
            name       = p.get("recipe_name", "")
            step_info  = (f"  {p.get('keyword','')} — {p.get('provider','')} / {p.get('name','')}"
                          if chunk_type == "step" else "")
            print(f"  {i}. {label_str} {name}{step_info}")
            print(f"     score: {hit.score:.4f}  |  chunk_id: {p.get('chunk_id','')}")
            print(f"     text: {p.get('text','')[:120].replace(chr(10),' ')}...")
            print()

    return [hit.payload.get("chunk_id", "") for hit in results.points]


# ---------------------------------------------------------------------------
# Benchmark queries
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES = [
    # --- Baseline ---
    (
        "Q1 — Baseline: recipe level, natural language",
        "which recipe handles approved sales orders and updates Salesforce?",
    ),
    (
        "Q2 — Baseline: step level, technical",
        "subscribe to pub sub topic and check if opportunity ID is missing",
    ),
    (
        "Q3 — Baseline: semantic gap, no shared keywords",
        "add document to knowledge base",
    ),
    (
        "Q4 — Baseline: conditional logic",
        "only create a record if it does not already exist",
    ),
    (
        "Q5 — Baseline: cross-recipe, different connector",
        "execute custom code to slow down the workflow",
    ),
    # --- Find by purpose ---
    (
        "Q6 — Find by purpose: Salesforce opportunity from sales order",
        "which recipe creates a new Salesforce opportunity from an approved sales order?",
    ),
    (
        "Q7 — Find by purpose: long-running API handler",
        "which recipe is designed to handle long-running API requests?",
    ),
    # --- Find by app ---
    (
        "Q8 — Find by app: Salesforce connector",
        "show me recipes that connect to Salesforce",
    ),
    (
        "Q9 — Find by app: logger connector",
        "which recipe uses the logger connector?",
    ),
    # --- Find by connection chain ---
    (
        "Q10 — Find by connection chain: pub sub trigger",
        "which recipe is triggered by a pub sub message?",
    ),
    (
        "Q11 — Find by connection chain: API endpoint",
        "which recipe receives an HTTP request and sends back a response?",
    ),
    # --- Ambiguous/broad ---
    (
        "Q12 — Ambiguous/broad: prevent duplicate records",
        "show me steps that prevent duplicate records from being created",
    ),
    (
        "Q13 — Ambiguous/broad: execution logging",
        "which recipes log information during execution?",
    ),
]


def _score_query(retrieved: list[str], golden: set) -> tuple[float, float, float]:
    """
    Return (Precision@K, Recall@K, Reciprocal Rank) for one query.

    Precision@K = |retrieved ∩ golden| / K
    Recall@K    = |retrieved ∩ golden| / |golden|
    RR          = 1 / rank of first relevant hit  (0 if none found)
    """
    k = len(retrieved)
    hits = sum(1 for c in retrieved if c in golden)
    precision = hits / k if k else 0.0
    recall    = hits / len(golden) if golden else 0.0
    rr = 0.0
    for rank, chunk_id in enumerate(retrieved, 1):
        if chunk_id in golden:
            rr = 1.0 / rank
            break
    return precision, recall, rr


MODEL_ORDER = ["BGE-M3 dense", "BGE-M3 sparse", "voyage-code-3", "text-embedding-3-large"]
MODEL_SHORT  = {
    "BGE-M3 dense":           "BGE-D",
    "BGE-M3 sparse":          "BGE-S",
    "voyage-code-3":          "VOY",
    "text-embedding-3-large": "OAI",
}


def run_queries(qdrant, queries, model, score_only: bool = False):
    run_bge    = model in ("bge",    "all")
    run_sparse = model in ("sparse", "all")
    run_voyage = model in ("voyage", "all")
    run_openai = model in ("openai", "all")

    golden = load_golden()
    has_golden = bool(golden)

    # scores[model_key]    = list of (P@K, R@K, RR) per query
    # retrieved[model_key] = list of ranked chunk_id lists per query
    scores:    dict[str, list[tuple[float, float, float]]] = {k: [] for k in MODEL_ORDER}
    retrieved: dict[str, list[list[str]]]                  = {k: [] for k in MODEL_ORDER}

    for label, query in queries:
        if not score_only:
            print(f"\n{'#'*60}")
            print(f"  {label}")
            print(f"{'#'*60}")

        q_golden = golden.get(label, set())

        if run_bge:
            vec = embed_query_bge(query)
            ids = search(qdrant, "dense_bge", vec, "BGE-M3 dense", query, silent=score_only)
            retrieved["BGE-M3 dense"].append(ids)
            if has_golden and q_golden:
                scores["BGE-M3 dense"].append(_score_query(ids, q_golden))

        if run_sparse:
            vec = embed_query_bge_sparse(query)
            ids = search(qdrant, "sparse_bge", vec, "BGE-M3 sparse", query, silent=score_only)
            retrieved["BGE-M3 sparse"].append(ids)
            if has_golden and q_golden:
                scores["BGE-M3 sparse"].append(_score_query(ids, q_golden))

        if run_voyage:
            vec = embed_query_voyage(query)
            ids = search(qdrant, "dense_voyage", vec, "voyage-code-3", query, silent=score_only)
            retrieved["voyage-code-3"].append(ids)
            if has_golden and q_golden:
                scores["voyage-code-3"].append(_score_query(ids, q_golden))

        if run_openai:
            vec = embed_query_openai(query)
            ids = search(qdrant, "dense_openai", vec, "text-embedding-3-large", query, silent=score_only)
            retrieved["text-embedding-3-large"].append(ids)
            if has_golden and q_golden:
                scores["text-embedding-3-large"].append(_score_query(ids, q_golden))

    # Print score tables if golden data was loaded
    if has_golden and any(v for v in scores.values()):
        _print_scores(scores, queries)
        _print_per_query(scores, retrieved, golden, queries)


def _print_scores(scores: dict, queries):
    n = len(queries)
    print(f"\n{'='*60}")
    print(f"  Benchmark Score Summary  (n={n} queries, K={TOP_K})")
    print(f"{'='*60}")
    print(f"  {'Model':<28}  P@{TOP_K}    R@{TOP_K}    MRR")
    print(f"  {'-'*28}  -----   -----   -----")
    for model_key in MODEL_ORDER:
        results = scores.get(model_key, [])
        if not results:
            continue
        mp  = sum(r[0] for r in results) / len(results)
        mr  = sum(r[1] for r in results) / len(results)
        mrr = sum(r[2] for r in results) / len(results)
        print(f"  {model_key:<28}  {mp:.3f}   {mr:.3f}   {mrr:.3f}")
    print()


def _print_per_query(scores, retrieved, golden, queries):
    """Per-query breakdown: RR per model + rank-1 chunk_id for each model."""
    active_models = [m for m in MODEL_ORDER if scores.get(m)]

    print(f"{'='*60}")
    print(f"  Per-query breakdown")
    print(f"{'='*60}")

    scored_labels = [label for label, _ in queries if golden.get(label)]

    for qi, label in enumerate(scored_labels):
        print(f"\n  {label}")
        golden_ids = golden.get(label, set())
        print(f"  Golden: {', '.join(sorted(golden_ids))}")
        for model_key in active_models:
            model_scores = scores[model_key]
            model_ids    = retrieved[model_key]
            if qi >= len(model_scores):
                continue
            rr      = model_scores[qi][2]
            top_ids = model_ids[qi] if qi < len(model_ids) else []
            rank1   = top_ids[0] if top_ids else "(none)"
            hit_marker = "✓" if rank1 in golden_ids else "✗"
            print(f"    [{MODEL_SHORT[model_key]}]  RR={rr:.3f}  rank-1: {hit_marker} {rank1}")
        # flag if all active models returned the exact same rank-1
        rank1s = [retrieved[m][qi][0] if qi < len(retrieved[m]) and retrieved[m][qi] else None
                  for m in active_models]
        if len(set(rank1s)) == 1 and rank1s[0] is not None:
            print(f"    → all models returned the same rank-1 chunk")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", help="Single search query")
    parser.add_argument("--benchmark", action="store_true",
                        help="Run all 5 benchmark queries")
    parser.add_argument("--model", default="all",
                        choices=["bge", "sparse", "voyage", "openai", "all"],
                        help="Which model to use (bge=BGE-M3 dense, sparse=BGE-M3 sparse, voyage, openai, all)")
    parser.add_argument("--score-only", action="store_true",
                        help="Print score table only (suppress per-result output); requires --benchmark")
    args = parser.parse_args()

    if not args.query and not args.benchmark:
        parser.error("Provide --query or --benchmark")

    qdrant = QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY") or None,
    )

    if args.benchmark:
        run_queries(qdrant, BENCHMARK_QUERIES, args.model, score_only=args.score_only)
    else:
        run_queries(qdrant, [("Custom query", args.query)], args.model)


if __name__ == "__main__":
    main()
