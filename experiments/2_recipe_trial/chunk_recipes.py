"""
chunk_recipes.py

For each cleaned recipe pair in example/cleaned/, generate a chunks file:
  - example/chunks/<name>_chunks.json

Each chunk file is a flat list of Qdrant-ready points, two types:
  - Type 1 (recipe): one per recipe — recipe_summary as embed text
  - Type 2 (step):   one per step  — ancestor context + step content as embed text

Run:
    python3 chunk_recipes.py
"""

import json
import os
import glob


# ---------------------------------------------------------------------------
# Ancestor context
# ---------------------------------------------------------------------------

def build_as_index(semantic_steps, tracking_steps):
    """Return a dict mapping as -> (semantic_step, tracking_step)."""
    index = {}
    for s, t in zip(semantic_steps, tracking_steps):
        key = t.get("as")
        if key is not None:
            index[key] = (s, t)
    return index


def get_ancestor_chain(tracking_step, as_index):
    """
    Walk parent_as upward and return the ancestor list from root to
    immediate parent (excludes the step itself).
    """
    chain = []
    parent_as = tracking_step.get("parent_as")
    while parent_as is not None:
        if parent_as not in as_index:
            break
        ancestor_s, ancestor_t = as_index[parent_as]
        chain.append((ancestor_s, ancestor_t))
        parent_as = ancestor_t.get("parent_as")
    chain.reverse()
    return chain


def format_ancestor_context(chain, as_index):
    """
    Render ancestor chain as a Context line, e.g.:
      Context: [foreach: salesforce / get_records] > [if: sfdc_opportunity_id is blank]
    """
    if not chain:
        return None
    parts = []
    for ancestor_s, ancestor_t in chain:
        keyword = ancestor_s.get("keyword", "")
        provider = ancestor_s.get("provider", "")
        name = ancestor_s.get("name", "")
        if keyword == "if":
            condition = _summarise_if_condition(ancestor_s.get("input", {}))
            parts.append(f"[if: {condition}]")
        elif provider and name:
            parts.append(f"[{keyword}: {provider} / {name}]")
        else:
            parts.append(f"[{keyword}]")
    return "Context: " + " > ".join(parts)


def _summarise_if_condition(input_obj):
    """
    Extract a short human-readable summary of an if condition.
    Falls back to 'condition' if structure is unrecognised.
    """
    if not isinstance(input_obj, dict):
        return "condition"
    conditions = input_obj.get("conditions", [])
    if not conditions:
        return "condition"
    parts = []
    for cond in conditions:
        lhs = cond.get("lhs", "")
        operand = cond.get("operand", "")
        rhs = cond.get("rhs", "")
        if rhs:
            parts.append(f"{lhs} {operand} {rhs}")
        else:
            parts.append(f"{lhs} {operand}")
    operand_join = f" {input_obj.get('operand', 'and')} "
    return operand_join.join(parts)


# ---------------------------------------------------------------------------
# Chunk text builders
# ---------------------------------------------------------------------------

def build_step_text(semantic_step, tracking_step, as_index, recipe_name):
    """Build the embed text for a Type 2 step chunk."""
    lines = []
    lines.append(f"Recipe: {recipe_name}")

    ancestor_chain = get_ancestor_chain(tracking_step, as_index)
    context = format_ancestor_context(ancestor_chain, as_index)
    if context:
        lines.append(context)

    keyword = semantic_step.get("keyword", "")
    provider = semantic_step.get("provider", "")
    name = semantic_step.get("name", "")
    if provider and name:
        lines.append(f"Step: {keyword} — {provider} / {name}")
    else:
        lines.append(f"Step: {keyword}")

    title = semantic_step.get("title")
    if title:
        lines.append(f"Title: {title}")

    comment = semantic_step.get("comment")
    if comment:
        lines.append(f"Comment: {comment}")

    input_obj = semantic_step.get("input")
    if input_obj:
        lines.append("Input:")
        for k, v in _flatten_input(input_obj):
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def _flatten_input(input_obj, prefix=""):
    """
    Yield (key_path, value) pairs from an input dict, flattening one level
    of nesting. Skips uuid fields (condition-level noise).
    """
    if not isinstance(input_obj, dict):
        yield (prefix, input_obj)
        return
    for k, v in input_obj.items():
        if k == "uuid":
            continue
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _flatten_input(v, full_key)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                yield from _flatten_input(item, f"{full_key}[{i}]")
        else:
            yield (full_key, v)


# ---------------------------------------------------------------------------
# Main chunking
# ---------------------------------------------------------------------------

def chunk_recipe(semantic_path, tracking_path, source_file):
    with open(semantic_path) as f:
        semantic = json.load(f)
    with open(tracking_path) as f:
        tracking = json.load(f)

    recipe_name = semantic["recipe_name"]
    basename = os.path.splitext(source_file)[0]

    semantic_steps = semantic["steps"]
    tracking_steps = tracking["steps"]
    config = tracking.get("config", [])

    as_index = build_as_index(semantic_steps, tracking_steps)
    connectors = [c["provider"] for c in config if "provider" in c]
    keywords_used = list(dict.fromkeys(s.get("keyword") for s in semantic_steps if s.get("keyword")))

    chunks = []

    # --- Type 1: recipe chunk ---
    chunks.append({
        "chunk_type": "recipe",
        "chunk_id": f"{basename}_recipe",
        "source_file": source_file,
        "recipe_name": recipe_name,
        "connectors": connectors,
        "total_steps": len(semantic_steps),
        "keywords_used": keywords_used,
        "text": semantic["recipe_summary"],
    })

    # --- Type 2: step chunks ---
    for s_step, t_step in zip(semantic_steps, tracking_steps):
        step_as = t_step.get("as")
        number = t_step.get("number", 0)
        chunk_id = (
            f"{basename}_{step_as}" if step_as
            else f"{basename}_step_{number}"
        )
        chunks.append({
            "chunk_type": "step",
            "chunk_id": chunk_id,
            "source_file": source_file,
            "recipe_name": recipe_name,
            "as": step_as,
            "uuid": t_step.get("uuid"),
            "number": number,
            "keyword": s_step.get("keyword"),
            "provider": s_step.get("provider"),
            "name": s_step.get("name"),
            "depth": t_step.get("depth", 0),
            "parent_as": t_step.get("parent_as"),
            "text": build_step_text(s_step, t_step, as_index, recipe_name),
        })

    return chunks


def main():
    cleaned_dir = os.path.join(os.path.dirname(__file__), "example", "cleaned")
    output_dir = os.path.join(os.path.dirname(__file__), "example", "chunks")
    os.makedirs(output_dir, exist_ok=True)

    semantic_files = sorted(glob.glob(os.path.join(cleaned_dir, "*_semantic.json")))
    if not semantic_files:
        print("No semantic files found in example/cleaned/")
        return

    for semantic_path in semantic_files:
        basename = os.path.basename(semantic_path).replace("_semantic.json", "")
        tracking_path = os.path.join(cleaned_dir, f"{basename}_tracking.json")
        source_file = f"{basename}.json"

        if not os.path.exists(tracking_path):
            print(f"Missing tracking file for {basename}, skipping.")
            continue

        print(f"Chunking: {basename}")
        chunks = chunk_recipe(semantic_path, tracking_path, source_file)

        output_path = os.path.join(output_dir, f"{basename}_chunks.json")
        with open(output_path, "w") as f:
            json.dump(chunks, f, indent=2)

        recipe_chunks = sum(1 for c in chunks if c["chunk_type"] == "recipe")
        step_chunks = sum(1 for c in chunks if c["chunk_type"] == "step")
        print(f"  {recipe_chunks} recipe chunk, {step_chunks} step chunks -> {os.path.relpath(output_path)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
