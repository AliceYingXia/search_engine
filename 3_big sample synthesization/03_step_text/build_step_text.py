"""
build_step_text.py

Generates embed text for each step from the cleaned semantic JSON files.
Reads:  description_intent/cleaned/<flow_id>_<version_no>_semantic.json
Writes: description_intent/step_texts/<flow_id>_<version_no>_step_texts.json

Each output file contains a list of objects:
    {
        "as":        "<step alias>",
        "flow_id":   <int>,
        "version_no":<int>,
        "step_text": "<embed text string>"
    }

Text format per step type — see "Step Text Construction" section in cleaning-process-pii.md.

Usage:
    python build_step_text.py
"""

from pathlib import Path
import json

INPUT_DIR  = Path(__file__).parent.parent / "02_cleaning" / "cleaned"
OUTPUT_DIR = Path(__file__).parent / "step_texts"

# Control-flow keywords that carry a tag label instead of provider/name
CONTROL_FLOW_TAGS = {
    "foreach":         "foreach [loop]",
    "try":             "try [error handling]",
    "catch":           "catch [error handler]",
    "else":            "else",
    "repeat":          "repeat [loop]",
    "while_condition": "while_condition",
    "stop":            "stop",
    "trigger":         None,   # handled separately
}

CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

# These steps are structural containers only. Their children already capture
# the context via block_context ("inside else branch", "inside try block").
# They have no semantic content worth embedding.
SKIP_KEYWORDS = {"else", "try"}


# ---------------------------------------------------------------------------
# Block context → readable string
# ---------------------------------------------------------------------------

def render_conditions(conditions: dict) -> str:
    """Turn a conditions dict into a compact readable string (with brackets)."""
    operands = ", ".join(conditions.get("operands", []))
    logic    = conditions.get("logic", "")
    return f"[{logic}: {operands}]"


def render_conditions_inline(conditions: dict) -> str:
    """Turn a conditions dict into an inline string without outer brackets."""
    operands = ", ".join(conditions.get("operands", []))
    logic    = conditions.get("logic", "")
    return f"{logic}: {operands}"


def render_block_context(bc: dict | None) -> str | None:
    """
    Render block_context as a single readable line.
    Returns None for root-level steps (bc is null or parent is trigger).
    """
    if bc is None:
        return None
    pk = bc.get("parent_keyword")
    if pk == "trigger" or pk is None:
        return None

    gp = bc.get("grandparent_keyword")
    cond = bc.get("conditions")

    # Build parent description
    if pk == "foreach":
        parent_str = "foreach loop"
    elif pk == "try":
        parent_str = "try block"
    elif pk == "catch":
        parent_str = "catch block"
    elif pk == "repeat":
        parent_str = "repeat loop"
    elif pk == "else":
        parent_str = "else branch"
    elif pk in ("if", "elsif"):
        branch = bc.get("branch", pk)
        branch_label = {"if_true": "true branch", "elsif": "elsif branch"}.get(branch, branch)
        if cond:
            parent_str = f"{pk} [{branch_label}, {render_conditions_inline(cond)}]"
        else:
            parent_str = f"{pk} [{branch_label}]"
    else:
        parent_str = pk

    # Add grandparent if meaningful
    if gp and gp not in ("trigger", None):
        gp_labels = {
            "foreach": "foreach loop",
            "try":     "try block",
            "if":      "if block",
            "repeat":  "repeat loop",
        }
        gp_str = gp_labels.get(gp, gp)
        return f"inside {parent_str} > {gp_str}"

    return f"inside {parent_str}"


# ---------------------------------------------------------------------------
# Neighbour → readable string
# ---------------------------------------------------------------------------

def render_neighbour(step: dict | None) -> str | None:
    """Render a prev_step or next_step dict as a short label."""
    if step is None:
        return None
    kw       = step.get("keyword", "")
    provider = step.get("provider")
    name     = step.get("name")
    if provider and name:
        return f"{provider}/{name}"
    return kw


# ---------------------------------------------------------------------------
# Step text builders
# ---------------------------------------------------------------------------

def build_action_text(step: dict) -> str:
    lines = []

    # 1. Comment (highest signal — goes first)
    comment = step.get("comment")
    if comment:
        lines.append(comment.strip())

    # 2. Operation
    provider = step.get("provider") or ""
    name     = step.get("name") or ""
    lines.append(f"action {provider} / {name}")

    # 3. Input fields (capped at 8)
    fields = step.get("input_fields")
    if fields:
        if len(fields) > 8:
            display = fields[:8] + [f"(+{len(fields) - 8} more)"]
        else:
            display = fields
        lines.append(f"fields: {', '.join(display)}")

    # 4. Block context
    ctx = render_block_context(step.get("block_context"))
    if ctx:
        lines.append(f"context: {ctx}")

    # 5. Flow
    prev = render_neighbour(step.get("prev_step"))
    nxt  = render_neighbour(step.get("next_step"))
    if prev and nxt:
        lines.append(f"flow: {prev} → {nxt}")
    elif prev:
        lines.append(f"flow: {prev} →")
    elif nxt:
        lines.append(f"flow: → {nxt}")

    return "\n".join(lines)


def build_condition_text(step: dict) -> str:
    """For if / elsif / while_condition steps."""
    lines = []
    kw   = step.get("keyword")
    bc   = step.get("block_context") or {}
    cond = step.get("own_conditions")   # step's own conditions, not parent's

    # 1. Operation with own conditions inline
    if cond:
        lines.append(f"{kw} {render_conditions(cond)}")
    else:
        lines.append(kw)

    # 2. Block context (grandparent only useful here)
    ctx = render_block_context(bc)
    if ctx:
        lines.append(f"context: {ctx}")

    # 3. Flow
    prev = render_neighbour(step.get("prev_step"))
    nxt  = render_neighbour(step.get("next_step"))
    if prev and nxt:
        lines.append(f"flow: {prev} → {nxt}")
    elif prev:
        lines.append(f"flow: {prev} →")
    elif nxt:
        lines.append(f"flow: → {nxt}")

    return "\n".join(lines)


def build_control_flow_text(step: dict) -> str:
    """For foreach / try / catch / else / repeat / stop / trigger."""
    lines = []
    kw = step.get("keyword")

    # 1. Label
    if kw == "trigger":
        provider = step.get("provider") or ""
        name     = step.get("name") or ""
        label = f"trigger: {provider} / {name}" if (provider and name) else "trigger"
    else:
        tag   = CONTROL_FLOW_TAGS.get(kw, kw)
        label = tag or kw
    lines.append(label)

    # 2. Block context
    ctx = render_block_context(step.get("block_context"))
    if ctx:
        lines.append(f"context: {ctx}")

    # 3. Flow
    prev = render_neighbour(step.get("prev_step"))
    nxt  = render_neighbour(step.get("next_step"))
    if prev and nxt:
        lines.append(f"flow: {prev} → {nxt}")
    elif prev:
        lines.append(f"flow: {prev} →")
    elif nxt:
        lines.append(f"flow: → {nxt}")

    return "\n".join(lines)


def build_step_text(step: dict) -> str:
    kw = step.get("keyword")
    if kw == "action":
        return build_action_text(step)
    elif kw in CONDITION_KEYWORDS:
        return build_condition_text(step)
    else:
        return build_control_flow_text(step)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_file(sem_path: Path, output_dir: Path):
    data     = json.loads(sem_path.read_text())
    flow_id  = data["flow_id"]
    version_no = data["version_no"]

    results = []
    for step in data["steps"]:
        if step.get("keyword") in SKIP_KEYWORDS:
            continue
        results.append({
            "as":         step["as"],
            "flow_id":    flow_id,
            "version_no": version_no,
            "step_text":  build_step_text(step),
        })

    stem = f"{flow_id}_{version_no}"
    (output_dir / f"{stem}_step_texts.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    sem_files = sorted(INPUT_DIR.glob("*_semantic.json"))
    print(f"Processing {len(sem_files)} semantic files → {OUTPUT_DIR} ...")

    errors = 0
    for i, f in enumerate(sem_files, 1):
        try:
            process_file(f, OUTPUT_DIR)
        except Exception as e:
            print(f"  ERROR {f.name}: {e}")
            errors += 1
        if i % 200 == 0:
            print(f"  {i}/{len(sem_files)}")

    out_files = list(OUTPUT_DIR.glob("*_step_texts.json"))
    total_steps = sum(
        len(json.loads(f.read_text())) for f in out_files
    )
    print(f"\nDone.")
    print(f"  Output files : {len(out_files)}")
    print(f"  Total steps  : {total_steps:,}")
    if errors:
        print(f"  Errors       : {errors}")


if __name__ == "__main__":
    main()
