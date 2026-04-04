"""
sample_recipes.py

Samples recipes from bt_prod.parquet for development and evaluation use.

Sampling criteria:
  1. Only rows that have a GPT-generated description (inner join with descriptions parquet).
  2. Restricted to 10 authors whose post-filter recipe count is strictly between
     50 and 100 (i.e. 51–99). The top 10 by recipe count are selected.

Input:  data/bt_prod.parquet
        data/gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet
Output: data/bt_prod_sample.parquet   (all recipes from the 10 authors)

Usage:
    python 01_sampling/sample_recipes.py
"""

from pathlib import Path
import pandas as pd

DATA_DIR          = Path(__file__).parent.parent / "data"
RECIPES_PATH      = DATA_DIR / "bt_prod.parquet"
DESCRIPTIONS_PATH = DATA_DIR / "gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet"
OUTPUT_PATH       = DATA_DIR / "bt_prod_sample.parquet"

N_AUTHORS   = 10      # number of authors to select
MIN_RECIPES = 50      # strictly more than this
MAX_RECIPES = 100     # strictly fewer than this


def main():
    # ── Load ────────────────────────────────────────────────────────────────
    print(f"Loading recipes from {RECIPES_PATH} ...")
    df = pd.read_parquet(RECIPES_PATH)
    print(f"  Rows: {len(df):,}  |  Authors: {df['author_id'].nunique()}")

    print(f"Loading descriptions from {DESCRIPTIONS_PATH} ...")
    desc = pd.read_parquet(DESCRIPTIONS_PATH)
    print(f"  Described recipes: {len(desc):,}")

    # ── Step 1: filter to rows with GPT descriptions ─────────────────────
    df = df.merge(
        desc[["flow_id", "description", "short_user_intent", "verbose_user_intent"]],
        on="flow_id",
        how="inner",
    )
    print(f"\nAfter description filter: {len(df):,} rows  |  Authors: {df['author_id'].nunique()}")

    # ── Step 2: select authors with MIN_RECIPES < count < MAX_RECIPES ────
    author_counts = df.groupby("author_id").size().sort_values(ascending=False)
    eligible = author_counts[
        (author_counts > MIN_RECIPES) & (author_counts < MAX_RECIPES)
    ]
    print(f"\nEligible authors ({MIN_RECIPES} < recipes < {MAX_RECIPES}): {len(eligible)}")

    selected = eligible.head(N_AUTHORS)
    print(f"Selected top {N_AUTHORS} by recipe count:")
    for aid, cnt in selected.items():
        print(f"  author_id={aid:>10}  recipes={cnt}")

    # ── Step 3: filter to selected authors ──────────────────────────────
    sample = df[df["author_id"].isin(selected.index)].copy()

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\nFinal sample: {len(sample):,} rows across {sample['author_id'].nunique()} authors")
    print(f"  has_comment=True : {sample['has_comment'].sum()} ({100*sample['has_comment'].mean():.1f}%)")
    print(f"  flow_ids         : {sample['flow_id'].nunique()} unique recipes")

    # ── Save ────────────────────────────────────────────────────────────
    sample.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved → {OUTPUT_PATH}")
    print(f"Columns: {sample.columns.tolist()}")


if __name__ == "__main__":
    main()
