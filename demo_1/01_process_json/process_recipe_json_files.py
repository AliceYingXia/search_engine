"""
process_recipe_json_files.py
============================

Production-oriented JSON processor for Demo 1.

Reads a directory of raw recipe JSON files and emits a normalized parquet file
containing:

- recipe_uid
- flow_id
- version_no
- author_id
- payload_json
- text_with_comments
- text_no_comments
- connectors
- actions
- input_fields
- datapill_fields
- step_count
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ACTION_KEYWORDS = {"action"}
TRIGGER_KEYWORDS = {"trigger"}
CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{12}$",
    re.IGNORECASE,
)

SUMMARY_TAGS = {
    "else": "else",
    "foreach": "foreach [loop]",
    "try": "try [error handling]",
    "catch": "catch [error handler]",
    "repeat": "repeat [loop]",
}

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from common.logging_utils import get_logger  # noqa: E402

logger = get_logger(__name__)


def collect_connectors(root: dict) -> list[str]:
    providers: set[str] = set()

    def walk(step: dict) -> None:
        provider = step.get("provider")
        if provider:
            providers.add(provider)
        for child in step.get("block", []):
            if isinstance(child, dict):
                walk(child)

    walk(root)
    return sorted(providers)


def collect_actions(root: dict) -> list[str]:
    actions: set[str] = set()

    def walk(step: dict) -> None:
        kw = step.get("keyword", "")
        provider = step.get("provider") or ""
        name = step.get("name") or ""
        if kw in ACTION_KEYWORDS | TRIGGER_KEYWORDS and provider and name:
            actions.add(f"{provider}/{name}")
        for child in step.get("block", []):
            if isinstance(child, dict):
                walk(child)

    walk(root)
    return sorted(actions)


def collect_input_fields(root: dict) -> list[str]:
    fields: set[str] = set()

    def walk(step: dict) -> None:
        if step.get("keyword") in ACTION_KEYWORDS:
            inp = step.get("input", {})
            if isinstance(inp, dict):
                for key in inp:
                    if not _UUID_RE.match(str(key)):
                        fields.add(str(key).lower())
        for child in step.get("block", []):
            if isinstance(child, dict):
                walk(child)

    walk(root)
    return sorted(fields)


def collect_datapill_fields(root: dict) -> list[str]:
    fields: set[str] = set()

    def collect_names(schema_list: list) -> None:
        for item in schema_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            if name and not _UUID_RE.match(name):
                fields.add(str(name).lower())
            collect_names(item.get("properties", []))

    def walk(step: dict) -> None:
        collect_names(step.get("extended_output_schema", []))
        for child in step.get("block", []):
            if isinstance(child, dict):
                walk(child)

    walk(root)
    return sorted(fields)


def extract_conditions(step: dict) -> dict | None:
    inp = step.get("input", {})
    if not isinstance(inp, dict) or "conditions" not in inp:
        return None
    operands = [c.get("operand") for c in inp.get("conditions", [])]
    return {"logic": inp.get("operand"), "operands": operands}


def summary_lines(step: dict, depth: int, include_comments: bool) -> list[str]:
    indent = "  " * depth
    sub = indent + "  "

    kw = step.get("keyword", "")
    provider = step.get("provider") or ""
    name = step.get("name") or ""
    comment = (step.get("comment") or "").strip()

    if kw in CONDITION_KEYWORDS:
        cond = extract_conditions(step)
        if cond and cond["operands"]:
            label = f"{kw} [{cond['logic']}: {', '.join(cond['operands'])}]"
        else:
            label = f"{kw} [condition]"
    elif kw in SUMMARY_TAGS:
        label = SUMMARY_TAGS[kw]
    elif provider and name:
        label = f"{kw}: {provider} / {name}"
    else:
        label = kw or "step"

    line = f"{indent}- {label}"
    if include_comments and comment:
        line += f"  # {comment}"
    result = [line]

    if kw in ACTION_KEYWORDS:
        inp = step.get("input", {})
        if isinstance(inp, dict):
            keys = [str(k) for k in inp if not _UUID_RE.match(str(k))]
            if keys:
                result.append(f"{sub}fields: {', '.join(keys[:8])}")

    return result


def build_recipe_summary(root: dict, include_comments: bool) -> str:
    providers: set[str] = set()
    lines: list[str] = []

    def walk(step: dict, depth: int = 0) -> None:
        provider = step.get("provider")
        if provider:
            providers.add(provider)
        lines.extend(summary_lines(step, depth, include_comments))
        for child in step.get("block", []):
            if isinstance(child, dict):
                walk(child, depth + 1)

    walk(root)
    return f"Connectors: {', '.join(sorted(providers))}\nSteps:\n" + "\n".join(lines)


def count_steps(root: dict) -> int:
    total = 0

    def walk(step: dict) -> None:
        nonlocal total
        total += 1
        for child in step.get("block", []):
            if isinstance(child, dict):
                walk(child)

    walk(root)
    return total


def extract_root(record: dict) -> tuple[dict, dict]:
    meta = {
        "flow_id": int(record.get("flow_id", 0) or 0),
        "version_no": int(record.get("version_no", 0) or 0),
        "author_id": int(record.get("author_id", 0) or 0),
        "recipe_uid": record.get("recipe_uid"),
    }

    if "pii_removed_code" in record:
        raw = record["pii_removed_code"]
        root = json.loads(raw) if isinstance(raw, str) else raw
    elif "payload" in record:
        raw = record["payload"]
        root = json.loads(raw) if isinstance(raw, str) else raw
    elif "recipe" in record:
        root = record["recipe"]
    else:
        root = record

    if not isinstance(root, dict) or "block" not in root:
        raise ValueError("JSON file does not contain a recipe root with a 'block' field")

    return root, meta


def process_file(path: Path) -> dict:
    record = json.loads(path.read_text())
    root, meta = extract_root(record)
    recipe_uid = meta["recipe_uid"] or path.stem

    return {
        "recipe_uid": recipe_uid,
        "flow_id": meta["flow_id"],
        "version_no": meta["version_no"],
        "author_id": meta["author_id"],
        "payload_json": json.dumps(root),
        "text_with_comments": build_recipe_summary(root, include_comments=True),
        "text_no_comments": build_recipe_summary(root, include_comments=False),
        "connectors": collect_connectors(root),
        "actions": collect_actions(root),
        "input_fields": collect_input_fields(root),
        "datapill_fields": collect_datapill_fields(root),
        "step_count": count_steps(root),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing raw recipe JSON files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "processed",
        help="Directory for processed parquet output.",
    )
    args = parser.parse_args()

    if not args.input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {args.input_dir}")
    if not args.input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {args.input_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "recipes.parquet"

    files = sorted(args.input_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No JSON files found in {args.input_dir}")

    rows = []
    skipped = 0
    for file_path in files:
        try:
            rows.append(process_file(file_path))
        except Exception as exc:
            skipped += 1
            logger.warning("Skipping %s: %s", file_path.name, exc)

    if not rows:
        raise RuntimeError("No valid recipe JSON files could be processed.")

    df = pd.DataFrame(rows)
    df.to_parquet(output_path, index=False)
    logger.info("Wrote %s processed recipes -> %s", len(df), output_path)
    if skipped:
        logger.warning("Skipped invalid files: %s", skipped)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
