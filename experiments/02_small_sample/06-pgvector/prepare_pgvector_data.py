"""
prepare_pgvector_data.py
========================

Prepares the recipe dataset for pgvector ingestion.

Applies the same seed-selection filters used in the evaluation pipeline:
  - Recipes ranked by distinct connector count and step count (descending).
  - Infrastructure connectors (present in >50% of an author's recipes)
    are excluded from the diversity overlap check.
  - A recipe is selected only if its signal connector set overlaps <=50%
    with every already-selected seed for that author.
  - Recipes with fewer than 3 distinct connectors are skipped.

Output columns
--------------
  recipe_uid        — "{author_id}_{flow_id}_v{version_no}"  (unique row key)
  author_id         — int
  flow_id           — int
  version_no        — int
  connectors        — comma-separated connector list
  step_count        — int
  text              — recipe_summary with inline step comments (the field to embed)
  text_no_comments  — recipe_summary with inline step comments stripped
  payload           — JSON string with all metadata fields for pgvector filtering

Usage
-----
    python 06-pgvector/prepare_pgvector_data.py
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths — reuse eval_utils from the sibling pipeline folder
# ---------------------------------------------------------------------------
BASE_DIR   = Path(__file__).parent
PROJ_DIR   = BASE_DIR.parent
UTILS_DIR  = PROJ_DIR / "05_sythesize_eval_dataset"
OUTPUT_PATH = BASE_DIR / "recipes_for_pgvector.csv"

sys.path.insert(0, str(UTILS_DIR))
from eval_utils import load_tracking_data, select_recipe_seeds  # noqa: E402


def strip_comments(summary: str) -> str:
    """Remove inline step comments (` # ...` suffixes) from a recipe summary."""
    return re.sub(r"[ \t]+#[^\n]*", "", summary)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading recipe data ...")
    author_index, summary_index = load_tracking_data()
    print(f"  {len(author_index)} authors")
    print(f"  {sum(len(v) for v in author_index.values())} recipes total\n")

    rows = []

    for author_id, all_recipes in sorted(author_index.items()):
        seeds = select_recipe_seeds(all_recipes)
        print(f"  Author {author_id:>10}  {len(all_recipes):>4} recipes → {len(seeds):>3} seeds selected")

        for seed in seeds:
            key     = (seed["flow_id"], seed["version_no"])
            summary = summary_index.get(key, "")
            if not summary:
                continue

            recipe_uid = f"{author_id}_{seed['flow_id']}_v{seed['version_no']}"
            connectors = ", ".join(sorted(seed["connectors"]))

            payload = json.dumps({
                "recipe_uid": recipe_uid,
                "author_id":  author_id,
                "flow_id":    seed["flow_id"],
                "version_no": seed["version_no"],
                "connectors": sorted(seed["connectors"]),
                "step_count": seed["step_count"],
            }, ensure_ascii=False)

            rows.append({
                "recipe_uid":       recipe_uid,
                "author_id":        author_id,
                "flow_id":          seed["flow_id"],
                "version_no":       seed["version_no"],
                "connectors":       connectors,
                "step_count":       seed["step_count"],
                "text":             summary,
                "text_no_comments": strip_comments(summary),
                "payload":          payload,
            })

    df = pd.DataFrame(rows, columns=[
        "recipe_uid", "author_id", "flow_id", "version_no",
        "connectors", "step_count", "text", "text_no_comments", "payload",
    ])

    df.to_csv(OUTPUT_PATH, index=False)

    print(f"\n{'=' * 60}")
    print(f"Total seeds selected : {len(df)}")
    print(f"Authors              : {df['author_id'].nunique()}")
    print(f"Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
