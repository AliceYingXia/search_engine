"""
run.py — SynthesizePipeline entry point
========================================

Usage
-----
    # Run all phases for category 1
    python run.py --style cat1

    # Run only query generation for category 2
    python run.py --style cat2 --phase queries

    # Run multiple specific phases
    python run.py --style cat1 --phase queries,relevance

    # Run all phases for all categories back-to-back
    python run.py --style all

    # If queries are already generated, run selection then relevance
    python run.py --style cat1 --phase select,relevance

Styles  : cat1 | cat2 | cat3 | all
Phases  : queries | select | relevance | adjudicate | dataset | evaluate  (comma-separated, or omit for all)

Phase order
-----------
    0.   prepare    — select seed recipes → recipes_for_pgvector.csv (style-independent, run once)
    1.   queries    — generate one query per seed recipe (LLM)
    1.5  select     — deduplicate with Qwen3-Embedding-8B, keep 50 diverse queries
    2.   relevance  — score every (query, recipe) pair with two models
    2.5  adjudicate — resolve model disagreements with a third LLM call
    3.   dataset    — filter, aggregate, and export the final dataset
    eval evaluate   — GPT-5.2 quality review of sampled example files
"""

import argparse

from pipeline.query_styles import CAT1, CAT2, CAT3
from pipeline.synthesize_pipeline import ALL_PHASES, SynthesizePipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize evaluation dataset pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--style",
        choices=["cat1", "cat2", "cat3", "all"],
        default="cat1",
        help="Query style to run (default: cat1)",
    )
    parser.add_argument(
        "--phase",
        default="all",
        help=(
            "Comma-separated phases to run: "
            "prepare, queries, select, relevance, adjudicate, dataset, evaluate — or 'all' (default)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args   = parse_args()
    phases = ALL_PHASES if args.phase == "all" else tuple(args.phase.split(","))
    styles = {"cat1": [CAT1], "cat2": [CAT2], "cat3": [CAT3], "all": [CAT1, CAT2, CAT3]}[args.style]

    for style in styles:
        SynthesizePipeline(style).run(phases)


if __name__ == "__main__":
    main()
