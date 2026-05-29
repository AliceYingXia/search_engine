"""
build_golden_dataset.py — Build golden datasets from the cleaned recipe parquet.

Filters the structural-summary parquet (output of process_data.py) by required
connector terms — exact match against the lowercased `connectors` list.

Usage:
    python build_golden_dataset.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

CLEANED_PARQUET = (
    Path(__file__).parent.parent / "01_process_data" / "cleaned" / "recipe_summaries_full.parquet"
)
OUT_DIR = Path(__file__).parent / "output"

FIELDNAMES = ["recipe_uid", "flow_id", "version_no", "connectors", "actions", "step_count", "search_text"]


def filter_recipes(df: pd.DataFrame, **constraints: list[str]) -> pd.DataFrame:
    """
    Return rows where each list-column matches ALL required values (lowercased).

    Example:
        filter_recipes(df, connectors=["salesforce"], actions=["create_record"])
        → recipes that connect Salesforce AND have a create_record action
    """
    out = df
    for field, required in constraints.items():
        needed = {v.lower() for v in required}
        out = out[out[field].apply(lambda lst, n=needed: n.issubset(set(lst)))]
    return out


def save_csv(name: str, rows: pd.DataFrame) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for _, r in rows.iterrows():
            writer.writerow({
                "recipe_uid":  r["recipe_uid"],
                "flow_id":     int(r["flow_id"]),
                "version_no":  int(r["version_no"]),
                "connectors":  " ".join(r["connectors"]),
                "actions":     " ".join(r["actions"]),
                "step_count":  int(r["step_count"]),
                "search_text": r["search_text"],
            })
    print(f"[golden] {len(rows)} recipes → {path}")


if __name__ == "__main__":
    print(f"Loading {CLEANED_PARQUET} ...")
    df = pd.read_parquet(CLEANED_PARQUET)
    print(f"  {len(df):,} recipes loaded")

    save_csv("salesforce_and_netsuite",    filter_recipes(df, connectors=["salesforce", "netsuite"]))
    save_csv("salesforce_and_slack",       filter_recipes(df, connectors=["salesforce", "slack"]))
    save_csv("salesforce_create_record",   filter_recipes(df, connectors=["salesforce"], actions=["create_record"]))
    save_csv("slack_post_bot_message",     filter_recipes(df, connectors=["slack"],      actions=["post_bot_message"]))
    save_csv("salesforce_sobject_name",    filter_recipes(df, connectors=["salesforce"], fields=["sobject_name"]))
    save_csv("slack_channel",              filter_recipes(df, connectors=["slack"],      fields=["channel"]))
