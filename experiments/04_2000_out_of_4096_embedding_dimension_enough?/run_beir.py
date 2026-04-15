from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math

from config import DEFAULT_OUTPUT_DIR, DEFAULT_SPEC, EmbeddingSpec, SUPPORTED_DIMS
from datasets import load_beir_dataset
from evaluate import ndcg_at_k, recall_at_k, reciprocal_rank
from qwen_client import QwenEmbeddingClient, truncate_normalize
from search import top_k_exact


@dataclass(frozen=True)
class QueryResult:
    query_id: str
    recall_at_10: float
    mrr: float
    ndcg_at_10: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True, help="Local BEIR-style dataset directory")
    parser.add_argument("--dims", type=int, choices=SUPPORTED_DIMS, default=4096)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--use-instruction", action="store_true")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_SPEC.batch_size)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--cache-dir",
        default="experiments/embedding_production/cache",
        help="Directory for embedding cache files",
    )
    return parser.parse_args()


def _sanitize(text: str) -> str:
    return text.replace("/", "_").replace(" ", "_")


def _cache_path(cache_dir: Path, dataset_name: str, dims: int, use_instruction: bool, kind: str) -> Path:
    suffix = "instr" if use_instruction else "plain"
    return cache_dir / f"{_sanitize(dataset_name)}_{kind}_{dims}_{suffix}.jsonl"


def _write_embedding_cache(path: Path, ids: list[str], vectors: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item_id, vec in zip(ids, vectors):
            f.write(json.dumps({"id": item_id, "embedding": vec}) + "\n")


def _read_embedding_cache(path: Path) -> tuple[list[str], list[list[float]]]:
    ids: list[str] = []
    vectors: list[list[float]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            ids.append(row["id"])
            vectors.append(row["embedding"])
    return ids, vectors


def _read_embedding_cache_ids(path: Path) -> list[str]:
    ids: list[str] = []
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            ids.append(row["id"])
    return ids


def _load_or_build_embeddings(
    client: QwenEmbeddingClient,
    dataset_name: str,
    ids: list[str],
    texts: list[str],
    dims: int,
    use_instruction: bool,
    kind: str,
    cache_dir: Path,
) -> list[list[float]]:
    direct_cache = _cache_path(cache_dir, dataset_name, dims, use_instruction, kind)
    if direct_cache.exists():
        cached_ids, cached_vecs = _read_embedding_cache(direct_cache)
        if cached_ids == ids:
            print(f"Using cached {kind} embeddings: {direct_cache.name}")
            return cached_vecs
        print(f"Cache id mismatch for {direct_cache.name}; rebuilding.")

    # Prefix-truncation reuse: derive smaller dims from a cached larger prefix.
    larger_dims = sorted((d for d in SUPPORTED_DIMS if d > dims), reverse=True)
    for larger_dim in larger_dims:
        larger_cache = _cache_path(cache_dir, dataset_name, larger_dim, use_instruction, kind)
        if not larger_cache.exists():
            continue
        cached_ids, cached_vecs = _read_embedding_cache(larger_cache)
        if cached_ids != ids:
            continue
        print(f"Deriving {kind} embeddings at {dims} dims from cache {larger_cache.name}")
        derived = [truncate_normalize(vec, dims) for vec in cached_vecs]
        _write_embedding_cache(direct_cache, ids, derived)
        return derived

    partial_cache = direct_cache.with_suffix(".partial.jsonl")
    partial_cache.parent.mkdir(parents=True, exist_ok=True)
    completed_ids = _read_embedding_cache_ids(partial_cache)
    completed = len(completed_ids)
    if completed and completed_ids != ids[:completed]:
        print(f"Partial cache mismatch for {partial_cache.name}; restarting.")
        partial_cache.unlink(missing_ok=True)
        completed = 0

    vectors: list[list[float]] = []
    if completed:
        _, vectors = _read_embedding_cache(partial_cache)
        print(f"Resuming {kind} embeddings from partial cache at {completed} / {len(ids)}")

    batch_size = client.spec.batch_size
    mode_label = "queries" if kind == "query" else "corpus"
    total = len(texts)
    for start in range(completed, total, batch_size):
        batch_texts = texts[start : start + batch_size]
        batch_ids = ids[start : start + batch_size]
        if kind == "query":
            prepared = [client._prepare_query(text) for text in batch_texts]
            batch_vecs = client.embed_batch(prepared)
        else:
            batch_vecs = client.embed_batch(batch_texts)
        with partial_cache.open("a", encoding="utf-8") as f:
            for item_id, vec in zip(batch_ids, batch_vecs):
                f.write(json.dumps({"id": item_id, "embedding": vec}) + "\n")
        vectors.extend(batch_vecs)
        print(f"  cached {mode_label} batch {start + 1}-{start + len(batch_texts)} / {total}")

    partial_cache.replace(direct_cache)
    return vectors


def main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache_dir)

    spec = EmbeddingSpec(
        model_name=DEFAULT_SPEC.model_name,
        predict_url=DEFAULT_SPEC.predict_url,
        dims=args.dims,
        use_instruction=args.use_instruction,
        instruction=DEFAULT_SPEC.instruction,
        batch_size=args.batch_size,
    )

    dataset = load_beir_dataset(args.dataset_dir)
    client = QwenEmbeddingClient(spec)

    print(f"Dataset        : {dataset.name}")
    print(f"Queries        : {len(dataset.query_ids)}")
    print(f"Corpus docs    : {len(dataset.corpus_ids)}")
    print(f"Dims           : {spec.dims}")
    print(f"Instruction    : {spec.use_instruction}")

    print("Embedding corpus ...")
    corpus_vecs = _load_or_build_embeddings(
        client=client,
        dataset_name=dataset.name,
        ids=dataset.corpus_ids,
        texts=dataset.corpus_texts,
        dims=spec.dims,
        use_instruction=False,
        kind="corpus",
        cache_dir=cache_dir,
    )

    print("Embedding queries ...")
    query_vecs = _load_or_build_embeddings(
        client=client,
        dataset_name=dataset.name,
        ids=dataset.query_ids,
        texts=dataset.query_texts,
        dims=spec.dims,
        use_instruction=spec.use_instruction,
        kind="query",
        cache_dir=cache_dir,
    )

    results: list[QueryResult] = []
    for query_id, query_vec in zip(dataset.query_ids, query_vecs):
        retrieved = top_k_exact(query_vec, dataset.corpus_ids, corpus_vecs, args.k)
        qrels = dataset.qrels.get(query_id, {})
        relevant = {doc_id for doc_id, score in qrels.items() if score > 0}
        results.append(
            QueryResult(
                query_id=query_id,
                recall_at_10=recall_at_k(retrieved, relevant, args.k),
                mrr=reciprocal_rank(retrieved, relevant),
                ndcg_at_10=ndcg_at_k(retrieved, qrels, args.k),
            )
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    detail_path = output_dir / f"{dataset.name}_qwen3_8b_{spec.dims}_exact_detail.csv"
    with detail_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["query_id", "recall_at_10", "mrr", "ndcg_at_10"])
        writer.writeheader()
        for row in results:
            writer.writerow(asdict(row))

    avg_recall = sum(r.recall_at_10 for r in results) / len(results)
    avg_mrr = sum(r.mrr for r in results) / len(results)
    avg_ndcg = sum(r.ndcg_at_10 for r in results) / len(results)

    summary_path = output_dir / "summary.csv"
    rows = []
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    rows = [
        row for row in rows
        if not (
            row["dataset"] == dataset.name
            and row["model"] == spec.model_name
            and int(row["dims"]) == spec.dims
            and row["search_mode"] == "exact"
            and row["instruction"] == str(spec.use_instruction)
            and int(row["k"]) == args.k
        )
    ]
    rows.append(
        {
            "dataset": dataset.name,
            "model": spec.model_name,
            "dims": spec.dims,
            "search_mode": "exact",
            "instruction": spec.use_instruction,
            "k": args.k,
            "recall_at_k": round(avg_recall, 4),
            "mrr": round(avg_mrr, 4),
            "ndcg_at_k": round(avg_ndcg, 4),
        }
    )

    with summary_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset",
                "model",
                "dims",
                "search_mode",
                "instruction",
                "k",
                "recall_at_k",
                "mrr",
                "ndcg_at_k",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Detail saved   : {detail_path}")
    print(f"Summary saved  : {summary_path}")
    print(f"Recall@{args.k}     : {avg_recall:.4f}")
    print(f"MRR            : {avg_mrr:.4f}")
    print(f"NDCG@{args.k}       : {avg_ndcg:.4f}")


if __name__ == "__main__":
    main()
