from __future__ import annotations

import argparse
import statistics

from datasets import load_beir_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="Local BEIR-style dataset directory",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Top-k cutoff to contextualize recall (default: 10)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_beir_dataset(args.dataset_dir)

    relevant_counts = [
        sum(1 for _, score in dataset.qrels.get(query_id, {}).items() if score > 0)
        for query_id in dataset.query_ids
    ]

    avg_relevant = statistics.mean(relevant_counts)
    median_relevant = statistics.median(relevant_counts)
    min_relevant = min(relevant_counts)
    max_relevant = max(relevant_counts)

    theoretical_max_recall = min(args.k / avg_relevant, 1.0) if avg_relevant > 0 else 0.0

    print(f"Dataset                  : {dataset.name}")
    print(f"Queries                  : {len(dataset.query_ids)}")
    print(f"Avg relevant docs/query  : {avg_relevant:.2f}")
    print(f"Median relevant/query    : {median_relevant:.2f}")
    print(f"Min relevant/query       : {min_relevant}")
    print(f"Max relevant/query       : {max_relevant}")
    print()
    print(f"Why Recall@{args.k} can look small:")
    print(
        f"- With {avg_relevant:.2f} relevant docs/query on average, even a perfect top-{args.k} "
        f"list can only reach about {theoretical_max_recall:.4f} average Recall@{args.k} "
        f"if there are usually more than {args.k} relevant docs."
    )
    print(
        f"- Example: if a query has 300 relevant docs, retrieving 10 relevant docs in the top {args.k} "
        f"still gives Recall@{args.k} = 10/300 = 0.0333."
    )
    print(
        "- So low Recall@10 on this dataset often reflects a large denominator "
        "(many relevant docs), not necessarily poor top-rank quality."
    )


if __name__ == "__main__":
    main()
