"""
clean_pii_recipes.py

Processes bt_prod_sample.parquet and produces recipe-level summaries.

Output: cleaned/recipe_summaries.parquet
  Columns:
    - flow_id
    - version_no
    - author_id
    - connectors                     : sorted list of distinct provider names (payload)
    - recipe_summary_with_comment    : full structural text including user comments
    - recipe_summary_without_comment : same text with comments stripped

Usage:
    python clean_pii_recipes.py
"""

import json
import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INPUT       = Path(__file__).parent.parent / "data" / "bt_prod_sample.parquet"
OUTPUT_DIR  = Path(__file__).parent / "cleaned"
OUTPUT_FILE = OUTPUT_DIR / "recipe_summaries.parquet"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTION_KEYWORDS = {"action"}
CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

# UUID-format keys are dynamic filter-row identifiers with no semantic value.
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
)

SUMMARY_TAGS = {
    "else":   "else",
    "foreach": "foreach [loop]",
    "try":    "try [error handling]",
    "catch":  "catch [error handler]",
    "repeat": "repeat [loop]",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_connectors(root: dict) -> list[str]:
    """Return a sorted list of distinct provider names across all steps."""
    providers: set[str] = set()

    def walk(step: dict):
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
    Return one or more indented lines for the recipe-level summary.

    Main line: step label, with comment appended as  # <text>  when present
               and include_comments is True.
    Sub-line:  fields: <input_field_names>  for action steps (capped at 8).
    """
    indent = "  " * depth
    sub    = indent + "  "   # 2 extra spaces — aligns below the step label

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

    # Fields sub-line — action steps only, keys only (values are all REDACTED)
    if kw in ACTION_KEYWORDS:
        inp = step.get("input", {})
        if isinstance(inp, dict):
            keys = [
                k for k in inp
                if k not in ("operand", "type", "conditions")
                and not _UUID_RE.match(str(k))
            ]
            if keys:
                if len(keys) > 8:
                    display = keys[:8] + [f"(+{len(keys) - 8} more)"]
                else:
                    display = list(keys)
                result.append(f"{sub}fields: {', '.join(display)}")

    return result


def build_recipe_summary(root: dict, include_comments: bool) -> str:
    """Generate the recipe-level summary text block."""
    providers: set[str] = set()
    lines: list[str] = []

    def walk(step: dict, depth: int = 0):
        p = step.get("provider")
        if p:
            providers.add(p)
        lines.extend(summary_lines(step, depth, include_comments=include_comments))
        for child in step.get("block", []):
            walk(child, depth + 1)

    walk(root)

    header = f"Connectors: {', '.join(sorted(providers))}\nSteps:"
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-recipe entry point
# ---------------------------------------------------------------------------

def process_recipe(row: pd.Series) -> dict | None:
    """Return a dict with both summary variants for one recipe version."""
    flow_id    = int(row["flow_id"])
    version_no = int(row["version_no"])
    author_id  = int(row["author_id"])

    try:
        root = json.loads(row["pii_removed_code"])
    except Exception as e:
        print(f"  SKIP flow_id={flow_id} v{version_no}: JSON parse error — {e}")
        return None

    return {
        "flow_id":                        flow_id,
        "version_no":                     version_no,
        "author_id":                      author_id,
        "connectors":                     collect_connectors(root),
        "recipe_summary_with_comment":    build_recipe_summary(root, include_comments=True),
        "recipe_summary_without_comment": build_recipe_summary(root, include_comments=False),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Loading {INPUT} ...")
    df = pd.read_parquet(INPUT)
    print(f"  Rows: {len(df):,}")

    print("Building recipe summaries ...")
    records = []
    errors = 0
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

    out_df = pd.DataFrame(records)
    out_df.to_parquet(OUTPUT_FILE, index=False)

    print(f"\nDone.")
    print(f"  Recipes written : {len(records)}")
    print(f"  Output          : {OUTPUT_FILE}")
    if errors:
        print(f"  Errors          : {errors}")


if __name__ == "__main__":
    main()
