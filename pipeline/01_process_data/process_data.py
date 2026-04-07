"""
process_data.py

Two-step data preparation pipeline for semantic search ingestion.

  Step 1  Sample bt_prod.parquet  →  data/bt_prod_sample.parquet
  Step 2  Build recipe summaries  →  cleaned/recipe_summaries.parquet

Input:  data/bt_prod.parquet
        data/gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet
Output: data/bt_prod_sample.parquet
        cleaned/recipe_summaries.parquet

Usage:
    python process_data.py
"""

import json
import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR          = Path(__file__).parent.parent.parent / "data"
RECIPES_PATH      = DATA_DIR / "bt_prod.parquet"
DESCRIPTIONS_PATH = DATA_DIR / "gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet"
SAMPLE_PATH       = DATA_DIR / "bt_prod_sample.parquet"
OUTPUT_DIR        = Path(__file__).parent / "cleaned"
SUMMARIES_PATH    = OUTPUT_DIR / "recipe_summaries.parquet"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N_AUTHORS = 30

ACTION_KEYWORDS    = {"action"}
CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

# UUID-format keys are dynamic filter-row identifiers with no semantic value.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

SUMMARY_TAGS = {
    "else":    "else",
    "foreach": "foreach [loop]",
    "try":     "try [error handling]",
    "catch":   "catch [error handler]",
    "repeat":  "repeat [loop]",
}


# ---------------------------------------------------------------------------
# Step 1 — Sample recipes
# ---------------------------------------------------------------------------

def sample_recipes() -> None:
    """Filter bt_prod.parquet to the top N_AUTHORS by recipe count (described only)."""
    print(f"Loading {RECIPES_PATH} ...")
    df = pd.read_parquet(RECIPES_PATH)
    print(f"  Rows: {len(df):,}  |  Authors: {df['author_id'].nunique()}")

    print(f"Loading {DESCRIPTIONS_PATH} ...")
    desc = pd.read_parquet(DESCRIPTIONS_PATH)
    print(f"  Described recipes: {len(desc):,}")

    df = df.merge(
        desc[["flow_id", "description", "short_user_intent", "verbose_user_intent"]],
        on="flow_id",
        how="inner",
    )
    print(f"After description filter: {len(df):,} rows  |  Authors: {df['author_id'].nunique()}")

    author_counts = df.groupby("author_id").size().sort_values(ascending=False)
    selected = author_counts.head(N_AUTHORS)
    print(f"\nSelected top {N_AUTHORS} authors by recipe count:")
    for aid, cnt in selected.items():
        print(f"  author_id={aid:>10}  recipes={cnt}")

    sample = df[df["author_id"].isin(selected.index)].copy()
    print(f"\nFinal sample: {len(sample):,} rows across {sample['author_id'].nunique()} authors")
    print(f"  has_comment=True : {sample['has_comment'].sum()} ({100 * sample['has_comment'].mean():.1f}%)")
    print(f"  flow_ids         : {sample['flow_id'].nunique()} unique recipes")

    sample.to_parquet(SAMPLE_PATH, index=False)
    print(f"Saved → {SAMPLE_PATH}")


# ---------------------------------------------------------------------------
# Step 2 — Build recipe summaries
# ---------------------------------------------------------------------------

def collect_connectors(root: dict) -> list[str]:
    """Return a sorted list of distinct provider names across all steps."""
    providers: set[str] = set()

    def walk(step: dict) -> None:
        p = step.get("provider")
        if p:
            providers.add(p)
        for child in step.get("block", []):
            walk(child)

    walk(root)
    return sorted(providers)


def extract_conditions(step: dict) -> dict | None:
    """Extract condition structure from an if / elsif / while_condition step."""
    inp = step.get("input", {})
    if not isinstance(inp, dict) or "conditions" not in inp:
        return None
    operands = [c.get("operand") for c in inp.get("conditions", [])]
    return {
        "logic":    inp.get("operand"),
        "count":    len(operands),
        "operands": operands,
    }


def summary_lines(step: dict, depth: int, include_comments: bool) -> list[str]:
    """
    Return indented summary lines for a single step.

    Main line: step label with inline # comment when include_comments is True.
    Sub-line:  fields: <input_field_names> for action steps (capped at 8).
    """
    indent = "  " * depth
    sub    = indent + "  "

    kw       = step.get("keyword", "")
    provider = step.get("provider") or ""
    name     = step.get("name") or ""
    comment  = (step.get("comment") or "").strip()

    if kw in CONDITION_KEYWORDS:
        cond = extract_conditions(step)
        if cond and cond["operands"]:
            tag = f"[{cond['logic']}: {', '.join(cond['operands'])}]"
        else:
            tag = "[condition]"
        label = f"{kw} {tag}"
    elif kw in SUMMARY_TAGS:
        label = SUMMARY_TAGS[kw]
    elif provider and name:
        label = f"{kw}: {provider} / {name}"
    else:
        label = kw

    main = f"{indent}- {label}"
    if include_comments and comment:
        main += f"  # {comment}"
    result = [main]

    if kw in ACTION_KEYWORDS:
        inp = step.get("input", {})
        if isinstance(inp, dict):
            keys = [
                k for k in inp
                if k not in ("operand", "type", "conditions")
                and not _UUID_RE.match(str(k))
            ]
            if keys:
                display = keys
                result.append(f"{sub}fields: {', '.join(display)}")

    return result


def build_recipe_summary(root: dict, include_comments: bool) -> str:
    """Generate the full indented recipe summary text."""
    providers: set[str] = set()
    lines: list[str] = []

    def walk(step: dict, depth: int = 0) -> None:
        p = step.get("provider")
        if p:
            providers.add(p)
        lines.extend(summary_lines(step, depth, include_comments=include_comments))
        for child in step.get("block", []):
            walk(child, depth + 1)

    walk(root)
    return f"Connectors: {', '.join(sorted(providers))}\nSteps:\n" + "\n".join(lines)


def count_steps(root: dict) -> int:
    """Return the total number of steps (including nested) in a recipe."""
    count = 0
    def walk(step: dict) -> None:
        nonlocal count
        count += 1
        for child in step.get("block", []):
            walk(child)
    walk(root)
    return count


def process_recipe(row: pd.Series) -> dict | None:
    """Return both summary variants for one recipe row, or None on parse error."""
    flow_id    = int(row["flow_id"])
    version_no = int(row["version_no"])
    author_id  = int(row["author_id"])

    try:
        root = json.loads(row["pii_removed_code"])
    except Exception as e:
        print(f"  SKIP flow_id={flow_id} v{version_no}: JSON parse error – {e}")
        return None

    return {
        "flow_id":                        flow_id,
        "version_no":                     version_no,
        "author_id":                      author_id,
        "connectors":                     collect_connectors(root),
        "step_count":                     count_steps(root),
        "recipe_summary_with_comment":    build_recipe_summary(root, include_comments=True),
        "recipe_summary_without_comment": build_recipe_summary(root, include_comments=False),
    }


def build_summaries() -> None:
    """Parse pii_removed_code for each recipe and emit two summary variants."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Loading {SAMPLE_PATH} ...")
    df = pd.read_parquet(SAMPLE_PATH)
    print(f"  Rows: {len(df):,}")

    print("Building recipe summaries ...")
    records, errors = [], 0
    for i, (_, row) in enumerate(df.iterrows(), 1):
        try:
            result = process_recipe(row)
            if result:
                records.append(result)
        except Exception as e:
            print(f"  ERROR row {i}: {e}")
            errors += 1
        if i % 100 == 0:
            print(f"  {i}/{len(df)}")

    pd.DataFrame(records).to_parquet(SUMMARIES_PATH, index=False)
    print(f"Done.  Recipes written: {len(records)}  |  Output: {SUMMARIES_PATH}")
    if errors:
        print(f"  Errors: {errors}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Step 1 — Sample recipes")
    print("=" * 60)
    sample_recipes()

    print()
    print("=" * 60)
    print("Step 2 — Build recipe summaries")
    print("=" * 60)
    build_summaries()


if __name__ == "__main__":
    main()
