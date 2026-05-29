"""
process_data.py

Data preparation pipeline for semantic search ingestion.

Supported modes:

  1. sample
     Sample the top-N described authors into data/bt_prod_sample.parquet, then
     build cleaned recipe summaries into cleaned/recipe_summaries.parquet.

  2. full
     Build cleaned recipe summaries directly from the full raw parquet into
     cleaned/recipe_summaries_full.parquet.

Usage:
    python process_data.py
    python process_data.py --source full
"""

import argparse
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
FULL_SUMMARIES_PATH = OUTPUT_DIR / "recipe_summaries_full.parquet"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N_AUTHORS = 30

ACTION_KEYWORDS    = {"action"}
TRIGGER_KEYWORDS   = {"trigger"}
CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

# UUID-format keys are dynamic identifiers with no semantic value.
# Matches both hyphen form (input keys)  and underscore form (output schema names).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{12}$",
    re.IGNORECASE,
)

# Input keys that are structural metadata, not user-facing field names.
_INPUT_SKIP = {"operand", "type", "conditions", "source",
               "parameters_schema_json", "result_schema_json"}

# Only keep input_fields and datapill_fields that contain at least one
# non-alphanumeric character (underscore, hyphen, dot, etc.).
# This retains compound technical identifiers (table_id, record_id,
# continuation_token, body-format) and drops plain English words
# (record, status, email, limit) which are too generic to be useful
# discriminators in keyword search.
_COMPOUND_RE = re.compile(r'[^a-z0-9]')


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


def collect_actions(root: dict) -> list[str]:
    """
    Return a sorted list of distinct 'provider/name' pairs from all
    action and trigger steps (e.g. 'workato_db_table/upsert_record').
    """
    actions: set[str] = set()

    def walk(step: dict) -> None:
        kw       = step.get("keyword", "")
        provider = step.get("provider") or ""
        name     = step.get("name") or ""
        if kw in ACTION_KEYWORDS | TRIGGER_KEYWORDS and provider and name:
            actions.add(f"{provider}/{name}")
        for child in step.get("block", []):
            walk(child)

    walk(root)
    return sorted(actions)


def collect_input_fields(root: dict) -> list[str]:
    """
    Return a sorted list of distinct non-UUID input field keys from all
    action steps (e.g. 'table_id', 'record_id', 'primary_field_id').

    These are the fields a user configures when setting up an action —
    they appear in the recipe UI as labelled inputs.
    UUID-keyed entries are dynamic filter rows with no fixed semantic meaning
    and are excluded.  Structural metadata keys (_INPUT_SKIP) are also excluded.
    """
    fields: set[str] = set()

    def walk(step: dict) -> None:
        if step.get("keyword") in ACTION_KEYWORDS:
            inp = step.get("input", {})
            if isinstance(inp, dict):
                for k in inp:
                    kl = k.lower()
                    if k not in _INPUT_SKIP and not _UUID_RE.match(str(k)):
                        fields.add(kl)
        for child in step.get("block", []):
            walk(child)

    walk(root)
    return sorted(fields)


def collect_datapill_fields(root: dict) -> list[str]:
    """
    Return a sorted list of distinct field names from extended_output_schema
    across all steps, collected recursively through nested 'properties'.

    These are the outputs a step produces — in Workato they become 'datapills'
    that downstream steps can reference (e.g. 'record', 'records',
    'continuation_token', 'package_version_name').
    """
    fields: set[str] = set()

    def collect_names(schema_list: list) -> None:
        for item in schema_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            nl = name.lower()
            if name and not _UUID_RE.match(name):
                fields.add(nl)
            collect_names(item.get("properties", []))

    def walk(step: dict) -> None:
        collect_names(step.get("extended_output_schema", []))
        for child in step.get("block", []):
            walk(child)

    walk(root)
    return sorted(fields)


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


def make_recipe_uid(author_id: int, flow_id: int, version_no: int) -> str:
    return f"{author_id}_{flow_id}_v{version_no}"


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
        "recipe_uid":                     make_recipe_uid(author_id, flow_id, version_no),
        "flow_id":                        flow_id,
        "version_no":                     version_no,
        "author_id":                      author_id,
        "payload_json":                   row["pii_removed_code"],
        "connectors":                     collect_connectors(root),
        "actions":                        collect_actions(root),
        "input_fields":                   collect_input_fields(root),
        "datapill_fields":                collect_datapill_fields(root),
        "step_count":                     count_steps(root),
        "text_with_comments":             build_recipe_summary(root, include_comments=True),
        "text_no_comments":               build_recipe_summary(root, include_comments=False),
        "recipe_summary_with_comment":    build_recipe_summary(root, include_comments=True),
        "recipe_summary_without_comment": build_recipe_summary(root, include_comments=False),
    }


def build_summaries(input_path: Path, output_path: Path) -> None:
    """Parse pii_removed_code for each recipe and emit cleaned summary fields."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Loading {input_path} ...")
    df = pd.read_parquet(input_path)
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

    pd.DataFrame(records).to_parquet(output_path, index=False)
    print(f"Done.  Recipes written: {len(records)}  |  Output: {output_path}")
    if errors:
        print(f"  Errors: {errors}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        choices=["sample", "full"],
        default="sample",
        help="Whether to build summaries from the sampled dev subset or the full raw parquet.",
    )
    args = parser.parse_args()

    if args.source == "sample":
        print("=" * 60)
        print("Step 1 — Sample recipes")
        print("=" * 60)
        sample_recipes()

        print()
        print("=" * 60)
        print("Step 2 — Build recipe summaries (sample)")
        print("=" * 60)
        build_summaries(SAMPLE_PATH, SUMMARIES_PATH)
        return

    print("=" * 60)
    print("Build recipe summaries (full dataset)")
    print("=" * 60)
    build_summaries(RECIPES_PATH, FULL_SUMMARIES_PATH)


if __name__ == "__main__":
    main()
