from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkDataset:
    name: str
    corpus_ids: list[str]
    corpus_texts: list[str]
    query_ids: list[str]
    query_texts: list[str]
    qrels: dict[str, dict[str, int]]


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_beir_dataset(dataset_dir: str | Path) -> BenchmarkDataset:
    root = Path(dataset_dir)
    corpus_path = root / "corpus.jsonl"
    queries_path = root / "queries.jsonl"
    qrels_path = root / "qrels" / "test.tsv"

    corpus_rows = _load_jsonl(corpus_path)
    query_rows = _load_jsonl(queries_path)

    corpus_ids = [row["_id"] for row in corpus_rows]
    corpus_texts = [
        " ".join(part for part in [row.get("title", ""), row.get("text", "")] if part).strip()
        for row in corpus_rows
    ]
    query_ids = [row["_id"] for row in query_rows]
    query_texts = [row["text"] for row in query_rows]

    qrels: dict[str, dict[str, int]] = {}
    with qrels_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            qid = row["query-id"]
            cid = row["corpus-id"]
            score = int(row["score"])
            qrels.setdefault(qid, {})[cid] = score

    return BenchmarkDataset(
        name=root.name,
        corpus_ids=corpus_ids,
        corpus_texts=corpus_texts,
        query_ids=query_ids,
        query_texts=query_texts,
        qrels=qrels,
    )
