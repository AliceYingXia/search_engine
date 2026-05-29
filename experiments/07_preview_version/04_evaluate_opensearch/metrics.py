"""
metrics.py
==========

Shared evaluation metrics and summary-writing utilities used by all
evaluate_*.py scripts.

Functions
---------
    precision_at_k   — fraction of top-k results that are relevant
    recall_at_k      — fraction of relevant results found in top-k
    reciprocal_rank  — 1/rank of the first relevant result (0 if none)
    write_summary    — append/replace rows in eval_summary_k<k>.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    return sum(1 for uid in retrieved[:k] if uid in relevant) / k


def recall_at_k(retrieved: list[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    return sum(1 for uid in retrieved if uid in relevant) / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for rank, uid in enumerate(retrieved, 1):
        if uid in relevant:
            return 1.0 / rank
    return 0.0


def write_summary(
    path: Path,
    new_rows: pd.DataFrame,
    model_key: str | list[str],
    *,
    categories: list[str] | None = None,
    search_mode: str | None = None,
) -> None:
    """Append new_rows to the summary CSV, replacing any existing rows for the
    same model / search_mode / category combination.

    Parameters
    ----------
    path        : path to eval_summary_k<k>.csv
    new_rows    : DataFrame of rows to add
    model_key   : model name(s) whose existing rows should be replaced
    categories  : if given, only replace rows whose category is in this list
                  (allows partial re-runs without wiping other categories)
    search_mode : if given, also match on the search_mode column
                  (used by evaluate_dense.py which stores one row per search mode)
    """
    models = [model_key] if isinstance(model_key, str) else list(model_key)

    if path.exists():
        existing = pd.read_csv(path)
        mask = existing["model"].isin(models)
        if search_mode is not None and "search_mode" in existing.columns:
            mask = mask & existing["search_mode"].eq(search_mode)
        if categories is not None and "category" in existing.columns:
            mask = mask & existing["category"].isin(categories)
        existing = existing[~mask]
        new_rows = pd.concat([existing, new_rows], ignore_index=True)

    new_rows.to_csv(path, index=False)
    print(f"\nSummary saved → {path.name}")
