"""
tune_bm25_parameters.py
=======================

Grid search over BM25 `k1` and `b` parameters for the OpenSearch recipes index.

Default behavior:
    - recreates the `recipes` index for each (k1, b) pair
    - uses the same analyzer setup as create_opensearch_indices.py
    - evaluates BM25 full-text search with config="english" by default

The default `english` config means the custom `english_underscore` analyzer,
not OpenSearch's built-in plain `english` analyzer.

Usage
-----
    # Default grid, english_underscore analyzer
    python pipeline/04_evaluate_opensearch/tune_bm25_parameters.py

    # Tune simple analyzer instead
    python pipeline/04_evaluate_opensearch/tune_bm25_parameters.py --config simple

    # Custom grid
    python pipeline/04_evaluate_opensearch/tune_bm25_parameters.py \
        --k1 0.3 0.5 0.8 1.2 1.8 2.5 \
        --b  0.0 0.1 0.25 0.4 0.6 0.75

Environment variables
---------------------
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD
"""

from __future__ import annotations

import argparse
import copy
import importlib.util as _ilu
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
EVAL_DIR = BASE_DIR.parent / "02_synthesize_data"
CAT_PATHS = {
    1: EVAL_DIR / "category1_dataset.csv",
    2: EVAL_DIR / "category2_dataset.csv",
    3: EVAL_DIR / "category3_dataset.csv",
}

DEFAULT_K1 = [0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0]
DEFAULT_B = [0.0, 0.1, 0.25, 0.4, 0.5, 0.75]


def _load_local(name: str, relpath: str):
    spec = _ilu.spec_from_file_location(name, BASE_DIR / relpath)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_indices_mod = _load_local("_indices04", "create_opensearch_indices.py")
_ingest_mod = _load_local("_ingest04", "index_recipe_corpus.py")
_fts_mod = _load_local("_fts04", "evaluate_full_text_search.py")

RECIPES_BODY = _indices_mod.RECIPES_BODY
get_client = _indices_mod.get_client
RecipeIngester = _ingest_mod.RecipeIngester
CSV_PATH = _ingest_mod.CSV_PATH
OsFtsEvaluator = _fts_mod.OsFtsEvaluator


def _recipes_body(k1: float, b: float) -> dict:
    """
    Return the recipes index body with BM25 tuned to (k1, b).

    Starts from the production recipes index definition so analyzer behavior
    stays aligned with create_opensearch_indices.py, including:
        - english_underscore analyzer
        - underscore_split preserve_original=True
        - simple sub-field on text_no_comments
    """
    body = copy.deepcopy(RECIPES_BODY)
    body["settings"]["similarity"]["default"]["k1"] = k1
    body["settings"]["similarity"]["default"]["b"] = b
    return body


def _recreate_and_ingest(client, k1: float, b: float) -> None:
    """Drop, recreate, and re-ingest the recipes index."""
    if client.indices.exists(index="recipes"):
        client.indices.delete(index="recipes")
        print("  dropped recipes")

    client.indices.create(index="recipes", body=_recipes_body(k1, b))
    print(f"  created recipes with BM25(k1={k1}, b={b})")

    ingester = RecipeIngester(CSV_PATH, client)
    indexed, failed = ingester.run()
    print(f"  indexed={indexed} failed={failed}")
    client.indices.refresh(index="recipes")


def run_grid(
    k1_values: list[float],
    b_values: list[float],
    *,
    config: str = "english",
    k: int = 5,
) -> pd.DataFrame:
    client = get_client()
    cat_dfs = [(f"Category {n}", pd.read_csv(CAT_PATHS[n])) for n in [1, 2, 3]]

    total = len(k1_values) * len(b_values)
    records = []
    run_no = 0

    for k1 in k1_values:
        for b in b_values:
            run_no += 1
            print(f"\n[{run_no}/{total}] config={config}  k1={k1}  b={b}", flush=True)

            _recreate_and_ingest(client, k1, b)

            evaluator = OsFtsEvaluator(k=k, config=config, client=client, scoring="bm25")
            _, metrics = evaluator.run(cat_dfs)

            row = {
                "config": config,
                "scoring": "bm25",
                "k1": k1,
                "b": b,
            }
            recalls = []
            mrrs = []

            for m in metrics:
                cat = m.category.replace(" ", "_").lower()
                row[f"{cat}_recall@{k}"] = m.recall
                row[f"{cat}_mrr"] = m.mrr
                recalls.append(m.recall)
                mrrs.append(m.mrr)

            row[f"mean_recall@{k}"] = round(sum(recalls) / len(recalls), 4)
            row["mean_mrr"] = round(sum(mrrs) / len(mrrs), 4)
            records.append(row)

            print(
                f"  Cat1 Recall={row[f'category_1_recall@{k}']:.4f}  "
                f"Cat2 Recall={row[f'category_2_recall@{k}']:.4f}  "
                f"Cat3 Recall={row[f'category_3_recall@{k}']:.4f}  "
                f"Mean Recall={row[f'mean_recall@{k}']:.4f}  "
                f"Mean MRR={row['mean_mrr']:.4f}"
            )

    return pd.DataFrame(records).sort_values(
        [f"mean_recall@{k}", "mean_mrr"], ascending=False
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        choices=["english", "simple"],
        default="english",
        help="FTS config to evaluate. Default: english (custom english_underscore analyzer).",
    )
    parser.add_argument("--k1", nargs="+", type=float, default=DEFAULT_K1)
    parser.add_argument("--b", nargs="+", type=float, default=DEFAULT_B)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    print(f"Config: {args.config}")
    print(f"k1 grid: {args.k1}")
    print(f"b grid : {args.b}")
    print(f"Total combinations: {len(args.k1) * len(args.b)}")

    results = run_grid(args.k1, args.b, config=args.config, k=args.k)

    out_name = f"bm25_tuning_{args.config}_k{args.k}.csv"
    out_path = BASE_DIR / out_name
    results.to_csv(out_path, index=False)

    print(f"\n{'=' * 88}")
    print(f"BM25 TUNING RESULTS ({args.config}, sorted by mean Recall@{args.k})")
    print(f"{'=' * 88}")
    print(results.to_string(index=False))
    print(f"\nFull results saved → {out_path.name}")

    best = results.iloc[0]
    print(
        f"\nBest combination: config={best['config']}  k1={best['k1']}  b={best['b']}"
    )
    print(
        f"  Mean Recall@{args.k}={best[f'mean_recall@{args.k}']}  "
        f"Mean MRR={best['mean_mrr']}"
    )


if __name__ == "__main__":
    main()
