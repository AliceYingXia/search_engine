"""
build_step_df.py
================

Builds and saves the step-level DataFrame used for Category 2 evaluation
and step-level semantic search.

What this script does
---------------------
Joins four sources on (flow_id, version_no, as) / (flow_id, number):

  1. *_tracking.json → steps[]
        Structured payload: keyword, provider, name, depth, parent, has_comment.

  2. *_semantic.json → steps[]
        Context fields: block_context, prev_step, next_step.

  3. 03_step_text/step_texts/*.json
        Embed-ready text string for each step (Category 2 search).

  4. gpt-5.2-*_bt_prod_descriptions_step.parquet
        LLM-generated text: description, step_intent.
        NOTE: four structural step types have no entry in this parquet —
        see "Step types without descriptions" below.

Step identifier
---------------
Each step has two identifiers:
  as     — stable string handle from the recipe JSON (e.g. "8546a8b1").
            Used as the join key for sources 1–3 because it is unique and
            stable within a recipe.
  number — sequential 0-indexed integer position within the recipe.
            Used to join source 4 (descriptions parquet).

Number indexing offset
----------------------
Tracking JSONs use 0-indexed number (trigger = 0).
Descriptions parquet uses 1-indexed number (trigger = 1).
Fix: df_desc["number"] -= 1 before joining.

Step types excluded before merging
------------------------------------
Four structural/control-flow step types are dropped from the tracking base
before any join. They are containers or terminators with no meaningful action
of their own and have no entry in the descriptions parquet:

  else   (308 steps) — branch container
  try    (384 steps) — try-block container
  stop   (527 steps) — recipe terminator
  repeat  (33 steps) — loop container

All remaining keyword types have 100% description coverage:
  action, trigger, if, catch, foreach, elsif, while_condition.

Excluding these rows upfront keeps the DataFrame clean — no nulls in
description / step_intent from structural steps, no need for a has_description
flag.

Inputs
------
  02_cleaning/cleaned/*_tracking.json
  02_cleaning/cleaned/*_semantic.json
  03_step_text/step_texts/*.json
  data/gpt-5.2-*_bt_prod_descriptions_step.parquet

Output
------
  05_sythesize_eval_dataset/step_df.parquet   (~8,010 rows × 15 columns)
  Excludes structural steps: else (308), try (384), stop (527), repeat (33).

    Columns
    -------
    Identity:
      flow_id         : int   — recipe identifier
      version_no      : int   — recipe version
      author_id       : int   — tenant scope
      as              : str   — step handle (unique within recipe)
      number          : int   — 0-indexed step position within recipe

    Payload:
      keyword         : str   — step type (action / trigger / if / catch / …)
      provider        : str   — connector name
      name            : str   — action name
      parent_as       : str   — handle of the parent step (None for top-level)
      parent_keyword  : str   — keyword of the parent step (None for top-level)
      depth           : int   — nesting depth (0 = top level)
      has_comment     : bool  — True if this step carries a user comment

    Semantic context:
      block_context   : str   — description of the enclosing block (None if top-level)
      prev_step       : dict  — {keyword, provider, name} of the preceding step
      next_step       : dict  — {keyword, provider, name} of the following step

    Embed text:
      step_text       : str   — embed-ready string for Category 2 step-level search

    LLM descriptions:
      description     : str   — technical prose describing what this step does
      step_intent     : str   — one-line natural-language intent for this step

Usage
-----
    python 05_sythesize_eval_dataset/build_step_df.py
"""

import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR       = Path(__file__).parent
CLEANED_DIR    = BASE_DIR.parent / "02_cleaning" / "cleaned"
STEP_TEXTS_DIR = BASE_DIR.parent / "03_step_text" / "step_texts"
DATA_DIR       = BASE_DIR.parent / "data"
OUTPUT_PATH    = BASE_DIR / "step_df.parquet"

DESCRIPTIONS_GLOB = "gpt-5.2-*_bt_prod_descriptions_step.parquet"

# Step types that intentionally have no LLM description
NO_DESCRIPTION_KEYWORDS = {"else", "try", "stop", "repeat"}


def main():
    # ── 1. Tracking steps ────────────────────────────────────────────────────
    tracking_files = sorted(CLEANED_DIR.glob("*_tracking.json"))
    print(f"Loading {len(tracking_files)} tracking files ...")

    tracking_rows = []
    for tf in tracking_files:
        trk = json.loads(tf.read_text())
        for s in trk["steps"]:
            tracking_rows.append({
                "flow_id":        trk["flow_id"],
                "version_no":     trk["version_no"],
                "author_id":      trk["author_id"],
                "as":             s["as"],
                "number":         s["number"],
                "keyword":        s["keyword"],
                "provider":       s.get("provider"),
                "name":           s.get("name"),
                "parent_as":      s.get("parent_as"),
                "parent_keyword": s.get("parent_keyword"),
                "depth":          s.get("depth"),
                "has_comment":    s.get("has_comment", False),
            })

    df_tracking = pd.DataFrame(tracking_rows)
    before = len(df_tracking)
    df_tracking = df_tracking[~df_tracking["keyword"].isin(NO_DESCRIPTION_KEYWORDS)].copy()
    dropped = before - len(df_tracking)
    print(f"  {len(df_tracking)} steps retained across "
          f"{df_tracking['flow_id'].nunique()} recipes "
          f"({dropped} structural steps dropped: else/try/stop/repeat)\n")

    # ── 2. Semantic steps ─────────────────────────────────────────────────────
    semantic_files = sorted(CLEANED_DIR.glob("*_semantic.json"))
    print(f"Loading {len(semantic_files)} semantic files ...")

    semantic_rows = []
    for sf in semantic_files:
        sem = json.loads(sf.read_text())
        for s in sem.get("steps", []):
            semantic_rows.append({
                "flow_id":       sem["flow_id"],
                "version_no":    sem["version_no"],
                "as":            s["as"],
                "block_context": s.get("block_context"),
                "prev_step":     s.get("prev_step"),
                "next_step":     s.get("next_step"),
            })

    df_semantic = pd.DataFrame(semantic_rows)
    print(f"  {len(df_semantic)} semantic step rows loaded\n")

    # ── 3. Step texts ─────────────────────────────────────────────────────────
    step_text_files = sorted(STEP_TEXTS_DIR.glob("*.json"))
    print(f"Loading {len(step_text_files)} step text files ...")

    step_text_rows = []
    for sf in step_text_files:
        for entry in json.loads(sf.read_text()):
            step_text_rows.append({
                "flow_id":    entry["flow_id"],
                "version_no": entry["version_no"],
                "as":         entry["as"],
                "step_text":  entry["step_text"],
            })

    df_step_texts = pd.DataFrame(step_text_rows)
    print(f"  {len(df_step_texts)} step text rows loaded\n")

    # ── 4. Descriptions ───────────────────────────────────────────────────────
    desc_files = sorted(DATA_DIR.glob(DESCRIPTIONS_GLOB))
    if not desc_files:
        raise FileNotFoundError(
            f"No step descriptions parquet found matching {DESCRIPTIONS_GLOB} in {DATA_DIR}"
        )
    print(f"Loading step descriptions from {desc_files[0].name} ...")
    df_desc = pd.read_parquet(desc_files[0])
    # Shift from 1-indexed to 0-indexed to align with tracking
    df_desc = df_desc.copy()
    df_desc["number"] = df_desc["number"] - 1
    print(f"  {len(df_desc)} description rows loaded (number shifted to 0-indexed)\n")

    # ── Join ──────────────────────────────────────────────────────────────────
    df = (
        df_tracking
        .merge(df_semantic,   on=["flow_id", "version_no", "as"], how="left")
        .merge(df_step_texts, on=["flow_id", "version_no", "as"], how="left")
        .merge(df_desc,       on=["flow_id", "number"],           how="left")
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"Final DataFrame: {len(df)} rows × {len(df.columns)} columns")
    print(f"  Recipes  : {df['flow_id'].nunique()}")
    print(f"  Authors  : {df['author_id'].nunique()}")
    print()

    print("Step counts by keyword:")
    keyword_counts = df["keyword"].value_counts()
    for kw, cnt in keyword_counts.items():
        print(f"  {kw:<20} {cnt}")
    print()

    null_counts = df[["block_context", "step_text", "description", "step_intent"]].isnull().sum()
    if null_counts.any():
        print("Null counts for joined columns (unexpected — investigate):")
        for col, cnt in null_counts[null_counts > 0].items():
            print(f"  {col:<20} {cnt}")
    else:
        print("  Coverage: 100% — no nulls in joined columns")

    # ── Save ──────────────────────────────────────────────────────────────────
    df.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved → {OUTPUT_PATH}")
    print(f"Columns: {df.columns.tolist()}")


if __name__ == "__main__":
    main()
