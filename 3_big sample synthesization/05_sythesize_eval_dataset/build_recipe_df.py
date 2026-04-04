"""
build_recipe_df.py
==================

Builds and saves the recipe-level DataFrame used throughout the Category 1
evaluation pipeline.

What this script does
---------------------
Joins three sources on flow_id / (flow_id, version_no):

  1. *_tracking.json  — structured payload: connectors, step count, trigger, etc.
  2. *_semantic.json  — text: recipe_summary (connector list + step outline)
  3. gpt-5.2-*_bt_prod_descriptions_recipe.parquet
                      — LLM-generated text: description, usage, short_user_intent,
                        verbose_user_intent

The result is one row per recipe (801 rows, 14 columns, full coverage).

Inputs
------
  02_cleaning/cleaned/*_tracking.json
  02_cleaning/cleaned/*_semantic.json
  data/gpt-5.2-*_bt_prod_descriptions_recipe.parquet

Output
------
  05_sythesize_eval_dataset/recipe_df.parquet

    Columns
    -------
    Payload (Qdrant metadata):
      flow_id          : int   — recipe identifier
      version_no       : int   — recipe version
      author_id        : int   — tenant scope
      connectors       : list  — sorted list of distinct connectors used
      connector_count  : int   — number of distinct connectors
      step_count       : int   — total number of steps
      has_comment      : bool  — True if any step carries a comment
      trigger_provider : str   — connector that triggers the recipe (None if absent)
      trigger_action   : str   — trigger action name (None if absent)

    Text (embedding / search):
      recipe_summary      : str — connector list + indented step tree
      description         : str — technical prose describing what the recipe does
      usage               : str — when and why to use this recipe
      short_user_intent   : str — one-line natural-language user intent
      verbose_user_intent : str — full paragraph natural-language user intent

Usage
-----
    python 05_sythesize_eval_dataset/build_recipe_df.py
"""

import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR    = Path(__file__).parent
CLEANED_DIR = BASE_DIR.parent / "02_cleaning" / "cleaned"
DATA_DIR    = BASE_DIR.parent / "data"
OUTPUT_PATH = BASE_DIR / "recipe_df.parquet"

DESCRIPTIONS_GLOB = "gpt-5.2-*_bt_prod_descriptions_recipe.parquet"


def main():
    # ── Tracking ─────────────────────────────────────────────────────────────
    tracking_files = sorted(CLEANED_DIR.glob("*_tracking.json"))
    print(f"Loading {len(tracking_files)} tracking files ...")

    tracking_rows = []
    for tf in tracking_files:
        trk    = json.loads(tf.read_text())
        steps  = trk.get("steps", [])
        trigger = next((s for s in steps if s["keyword"] == "trigger"), None)
        tracking_rows.append({
            "flow_id":          trk["flow_id"],
            "version_no":       trk["version_no"],
            "author_id":        trk["author_id"],
            "connectors":       trk.get("connectors", []),
            "connector_count":  len(set(trk.get("connectors", []))),
            "step_count":       len(steps),
            "has_comment":      any(s.get("has_comment") for s in steps),
            "trigger_provider": trigger["provider"] if trigger else None,
            "trigger_action":   trigger["name"]     if trigger else None,
        })

    df_tracking = pd.DataFrame(tracking_rows)
    print(f"  {len(df_tracking)} tracking rows loaded\n")

    # ── Semantic ──────────────────────────────────────────────────────────────
    semantic_files = sorted(CLEANED_DIR.glob("*_semantic.json"))
    print(f"Loading {len(semantic_files)} semantic files ...")

    semantic_rows = []
    for sf in semantic_files:
        sem = json.loads(sf.read_text())
        semantic_rows.append({
            "flow_id":        sem["flow_id"],
            "version_no":     sem["version_no"],
            "recipe_summary": sem.get("recipe_summary", ""),
        })

    df_semantic = pd.DataFrame(semantic_rows)
    print(f"  {len(df_semantic)} semantic rows loaded\n")

    # ── Descriptions ──────────────────────────────────────────────────────────
    desc_files = sorted(DATA_DIR.glob(DESCRIPTIONS_GLOB))
    if not desc_files:
        raise FileNotFoundError(
            f"No descriptions parquet found matching {DESCRIPTIONS_GLOB} in {DATA_DIR}"
        )
    print(f"Loading descriptions from {desc_files[0].name} ...")
    df_desc = pd.read_parquet(desc_files[0])
    print(f"  {len(df_desc)} description rows loaded\n")

    # ── Join ──────────────────────────────────────────────────────────────────
    df = (
        df_tracking
        .merge(df_semantic, on=["flow_id", "version_no"], how="left")
        .merge(df_desc,     on="flow_id",                 how="left")
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"Final DataFrame: {len(df)} rows × {len(df.columns)} columns")
    print(f"  Authors  : {df['author_id'].nunique()}")
    print(f"  Recipes  : {df['flow_id'].nunique()}")
    null_counts = df.isnull().sum()
    if null_counts.any():
        print("  Null counts:")
        for col, cnt in null_counts[null_counts > 0].items():
            print(f"    {col}: {cnt}")
    else:
        print("  Coverage : 100% — no nulls")
    print(f"\nColumns: {df.columns.tolist()}")

    # ── Save ──────────────────────────────────────────────────────────────────
    df.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
