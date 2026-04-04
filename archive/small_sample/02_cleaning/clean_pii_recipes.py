"""
clean_pii_recipes.py

Cleans bt_prod_sample.parquet following cleaning-process-pii.md.

For each recipe version, produces two files:

  cleaned/<flow_id>_<version_no>_semantic.json
      Text content prepared for embedding. Contains:
      - recipe_summary   : indented structural text of the full recipe
      - steps            : list of step objects with input_fields, block_context,
                           prev_step, next_step, and optional comment

  cleaned/<flow_id>_<version_no>_tracking.json
      Structured metadata for Qdrant payload. Contains:
      - recipe-level fields: flow_id, version_no, author_id, connectors
      - steps: as, uuid, number, keyword, provider, name,
               parent_as, parent_keyword, depth, has_comment

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
INPUT      = Path(__file__).parent.parent / "data" / "bt_prod_sample.parquet"
OUTPUT_DIR = Path(__file__).parent / "cleaned"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Only action steps get input_fields in the semantic file.
# All other keywords' input is either captured via block_context (if/elsif/
# while_condition) or fully redacted with no semantic value (foreach source,
# catch retry config, etc.).
ACTION_KEYWORDS = {"action"}

# For steps whose parent is one of these keywords, assign a branch label.
BRANCH_LABELS = {
    "if":    "if_true",
    "elsif": "elsif",
    "else":  "else",
}

# Keywords that carry condition info in their input
CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

# Structural container steps excluded from the semantic file (and therefore
# not embedded). They are still walked (for block_context derivation of their
# children) and still written to the tracking file.
SKIP_SEMANTIC_KEYWORDS = {"else", "try"}

# Summary label overrides for control-flow steps
# UUID-format keys are dynamic filter-row identifiers (used by workato_db_table).
# They carry no semantic meaning and must be excluded from input_fields.
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
)

SUMMARY_TAGS = {
    "else":            "else",
    "foreach":         "foreach [loop]",
    "try":             "try [error handling]",
    "catch":           "catch [error handler]",
    "repeat":          "repeat [loop]",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_as(step: dict) -> str:
    """Return the step's `as` field, or a synthetic _step_{number} key."""
    return step.get("as") or f"_step_{step.get('number')}"


def extract_conditions(step: dict) -> dict | None:
    """
    Extract condition structure from an if / elsif / while_condition step.
    Returns None if the input has no conditions list.
    """
    inp = step.get("input", {})
    if not isinstance(inp, dict) or "conditions" not in inp:
        return None
    operands = [c.get("operand") for c in inp.get("conditions", [])]
    return {
        "logic":    inp.get("operand"),
        "count":    len(operands),
        "operands": operands,
    }


def build_block_context(parent: dict | None, grandparent: dict | None) -> dict | None:
    """
    Build the block_context object for a step given its parent and grandparent.
    Returns None for root-level steps (direct children of trigger).
    """
    if parent is None:
        return None

    parent_kw = parent.get("keyword")
    gp_kw     = grandparent.get("keyword") if grandparent else None

    return {
        "parent_keyword":      parent_kw,
        "branch":              BRANCH_LABELS.get(parent_kw),
        "conditions":          extract_conditions(parent) if parent_kw in CONDITION_KEYWORDS else None,
        "grandparent_keyword": gp_kw,
    }


# ---------------------------------------------------------------------------
# Core walk
# ---------------------------------------------------------------------------

def walk_recipe(root: dict) -> tuple[list[dict], list[dict]]:
    """
    Recursively walk all steps in the recipe tree.

    Returns:
        flat_semantic  : list of semantic dicts ordered by step number
        flat_tracking  : list of tracking dicts ordered by step number
    """
    flat_semantic: list[dict] = []
    flat_tracking: list[dict] = []

    def walk(step: dict, parent: dict | None, grandparent: dict | None, depth: int):
        kw       = step.get("keyword")
        as_      = make_as(step)
        provider = (step.get("provider") or "").replace("\n", "").strip() or None
        name     = step.get("name") or None

        # ── Semantic ──────────────────────────────────────────────────────
        sem: dict = {
            "as":       as_,
            "keyword":  kw,
            "provider": provider,
            "name":     name,
        }

        comment = step.get("comment")
        if comment:
            sem["comment"] = comment

        # input_fields: action steps only, keys only (all values are REDACTED)
        if kw in ACTION_KEYWORDS:
            inp = step.get("input", {})
            if isinstance(inp, dict):
                keys = [
                    k for k in inp
                    if k not in ("operand", "type", "conditions")
                    and not _UUID_RE.match(str(k))
                ]
                if keys:
                    sem["input_fields"] = keys

        # own_conditions: the step's own condition structure (if/elsif/while_condition only).
        # Stored separately from block_context, which holds the PARENT's conditions.
        if kw in CONDITION_KEYWORDS:
            own_cond = extract_conditions(step)
            if own_cond:
                sem["own_conditions"] = own_cond

        if kw not in SKIP_SEMANTIC_KEYWORDS:
            sem["block_context"] = build_block_context(parent, grandparent)
            sem["_number"]       = step.get("number")   # temp; removed after sort
            flat_semantic.append(sem)

        # ── Tracking ──────────────────────────────────────────────────────
        flat_tracking.append({
            "as":             as_,
            "uuid":           step.get("uuid"),
            "number":         step.get("number"),
            "keyword":        kw,
            "provider":       provider,
            "name":           name,
            "parent_as":      make_as(parent) if parent else None,
            "parent_keyword": parent.get("keyword") if parent else None,
            "depth":          depth,
        })

        for child in step.get("block", []):
            walk(child, parent=step, grandparent=parent, depth=depth + 1)

    walk(root, parent=None, grandparent=None, depth=0)

    # Sort both lists by step number
    flat_semantic.sort(key=lambda s: (s["_number"] is None, s["_number"]))
    flat_tracking.sort(key=lambda s: (s["number"] is None, s["number"]))

    # Fill prev_step / next_step now that order is known
    def neighbour(s: dict) -> dict:
        return {"keyword": s["keyword"], "provider": s["provider"], "name": s["name"]}

    for i, sem in enumerate(flat_semantic):
        sem["prev_step"] = neighbour(flat_semantic[i - 1]) if i > 0 else None
        sem["next_step"] = neighbour(flat_semantic[i + 1]) if i < len(flat_semantic) - 1 else None
        del sem["_number"]

    return flat_semantic, flat_tracking


# ---------------------------------------------------------------------------
# Recipe-level summary
# ---------------------------------------------------------------------------

def summary_lines(step: dict, depth: int) -> list[str]:
    """
    Return one or more indented lines for the recipe-level summary.

    Main line: step label, with comment appended as  # <text>  when present.
    Sub-line:  fields: <input_field_names>  for action steps (capped at 8).

    Sub-lines use 2 extra spaces of indentation so they visually belong to
    their parent step rather than appearing as siblings.
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

    # Main line — append comment inline so it stays on one scannable line
    main = f"{indent}- {label}"
    if comment:
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


def build_recipe_summary(root: dict) -> str:
    """Generate the recipe-level summary text block.

    The summary contains the connector list and a step outline that includes,
    for each step: type/provider/name, any user comment, and (for action steps)
    the input field names. No flow_id or version_no — they carry no semantic
    meaning for embedding.
    """
    providers: set[str] = set()
    lines: list[str] = []

    def walk(step: dict, depth: int = 0):
        p = step.get("provider")
        if p:
            providers.add(p)
        lines.extend(summary_lines(step, depth))
        for child in step.get("block", []):
            walk(child, depth + 1)

    walk(root)

    header = (
        f"Connectors: {', '.join(sorted(providers))}\n"
        f"Steps:"
    )
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-recipe entry point
# ---------------------------------------------------------------------------

def clean_recipe(row: pd.Series, output_dir: Path):
    """Clean one recipe version and write semantic + tracking JSON files."""
    flow_id     = int(row["flow_id"])
    version_no  = int(row["version_no"])
    author_id   = int(row["author_id"])
    has_comment = bool(row["has_comment"])

    try:
        root = json.loads(row["pii_removed_code"])
    except Exception as e:
        print(f"  SKIP flow_id={flow_id} v{version_no}: JSON parse error — {e}")
        return

    flat_semantic, flat_tracking = walk_recipe(root)

    # Stamp has_comment (recipe-level flag) onto every tracking step
    for trk in flat_tracking:
        trk["has_comment"] = has_comment

    recipe_providers = sorted({
        trk["provider"] for trk in flat_tracking if trk["provider"]
    })

    recipe_summary = build_recipe_summary(root)

    semantic_out = {
        "flow_id":        flow_id,
        "version_no":     version_no,
        "recipe_summary": recipe_summary,
        "steps":          flat_semantic,
    }

    tracking_out = {
        "flow_id":    flow_id,
        "version_no": version_no,
        "author_id":  author_id,
        "connectors": recipe_providers,
        "steps":      flat_tracking,
    }

    stem = f"{flow_id}_{version_no}"
    (output_dir / f"{stem}_semantic.json").write_text(
        json.dumps(semantic_out, indent=2, ensure_ascii=False)
    )
    (output_dir / f"{stem}_tracking.json").write_text(
        json.dumps(tracking_out, indent=2, ensure_ascii=False)
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Loading {INPUT} ...")
    df = pd.read_parquet(INPUT)
    print(f"  Rows: {len(df):,}")

    print(f"Cleaning recipes → {OUTPUT_DIR} ...")
    errors = 0
    for i, (_, row) in enumerate(df.iterrows(), 1):
        try:
            clean_recipe(row, OUTPUT_DIR)
        except Exception as e:
            print(f"  ERROR row {i}: {e}")
            errors += 1
        if i % 100 == 0:
            print(f"  {i}/{len(df)}")

    semantic_files = list(OUTPUT_DIR.glob("*_semantic.json"))
    tracking_files = list(OUTPUT_DIR.glob("*_tracking.json"))
    print(f"\nDone.")
    print(f"  Semantic files : {len(semantic_files)}")
    print(f"  Tracking files : {len(tracking_files)}")
    if errors:
        print(f"  Errors         : {errors}")


if __name__ == "__main__":
    main()
