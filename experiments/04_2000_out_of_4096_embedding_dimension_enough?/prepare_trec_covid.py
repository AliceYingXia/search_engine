from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="experiments/embedding_production/data/trec-covid-20k",
        help="Where to write the BEIR-style subset",
    )
    parser.add_argument(
        "--target-docs",
        type=int,
        default=20_000,
        help="Target corpus size for the subset (default: 20000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for distractor sampling (default: 42)",
    )
    return parser.parse_args()


def _require_hf_hub():
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'huggingface_hub'. Install it first with "
            "`python -m pip install datasets pyarrow`."
        ) from exc
    return hf_hub_download


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _load_jsonl_gz(path: Path) -> list[dict]:
    rows: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> None:
    args = parse_args()
    hf_hub_download = _require_hf_hub()

    print("Downloading TREC-COVID docs, queries, and qrels from Hugging Face ...")
    corpus_gz = Path(
        hf_hub_download(
            repo_id="BeIR/trec-covid",
            filename="corpus.jsonl.gz",
            repo_type="dataset",
        )
    )
    queries_gz = Path(
        hf_hub_download(
            repo_id="BeIR/trec-covid",
            filename="queries.jsonl.gz",
            repo_type="dataset",
        )
    )
    qrels_tsv = Path(
        hf_hub_download(
            repo_id="BeIR/trec-covid-qrels",
            filename="test.tsv",
            repo_type="dataset",
        )
    )

    docs = _load_jsonl_gz(corpus_gz)
    queries = _load_jsonl_gz(queries_gz)

    query_rows = [{"_id": row["_id"], "text": row["text"]} for row in queries]
    query_ids = {row["_id"] for row in query_rows}

    qrels_rows = []
    with qrels_tsv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["query-id"] in query_ids and int(row["score"]) > 0:
                qrels_rows.append(
                    {
                        "query_id": row["query-id"],
                        "doc_id": row["corpus-id"],
                        "relevance": int(row["score"]),
                    }
                )

    relevant_doc_ids = {row["doc_id"] for row in qrels_rows}
    print(f"Queries kept           : {len(query_rows)}")
    print(f"Relevant docs required : {len(relevant_doc_ids)}")

    docs_by_id = {}
    all_doc_ids: list[str] = []
    for row in docs:
        doc_id = row["_id"]
        docs_by_id[doc_id] = row
        all_doc_ids.append(doc_id)

    if len(relevant_doc_ids) > args.target_docs:
        raise RuntimeError(
            f"target_docs={args.target_docs} is too small; qrels already require "
            f"{len(relevant_doc_ids)} docs."
        )

    distractor_pool = [doc_id for doc_id in all_doc_ids if doc_id not in relevant_doc_ids]
    rng = random.Random(args.seed)
    rng.shuffle(distractor_pool)

    extra_needed = args.target_docs - len(relevant_doc_ids)
    selected_doc_ids = list(relevant_doc_ids) + distractor_pool[:extra_needed]
    selected_doc_ids.sort()

    corpus_rows = []
    selected_doc_set = set(selected_doc_ids)
    for doc_id in selected_doc_ids:
        row = docs_by_id[doc_id]
        corpus_rows.append(
            {
                "_id": row["_id"],
                "title": row.get("title", "") or "",
                "text": row.get("text", "") or "",
            }
        )

    filtered_qrels = [
        {
            "query-id": row["query_id"],
            "corpus-id": row["doc_id"],
            "score": int(row["relevance"]),
        }
        for row in qrels_rows
        if row["doc_id"] in selected_doc_set
    ]

    output_dir = Path(args.output_dir)
    qrels_dir = output_dir / "qrels"
    qrels_dir.mkdir(parents=True, exist_ok=True)

    _write_jsonl(output_dir / "corpus.jsonl", corpus_rows)
    _write_jsonl(output_dir / "queries.jsonl", query_rows)

    with (qrels_dir / "test.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["query-id", "corpus-id", "score"], delimiter="\t")
        writer.writeheader()
        for row in filtered_qrels:
            writer.writerow(row)

    print(f"Corpus docs written    : {len(corpus_rows)}")
    print(f"Queries written        : {len(query_rows)}")
    print(f"Qrels written          : {len(filtered_qrels)}")
    print(f"Output dir             : {output_dir}")


if __name__ == "__main__":
    main()
