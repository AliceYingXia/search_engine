"""
process_data.py

Data preparation pipeline for semantic search ingestion.

Supported modes:

  1. sample
     Sample the top-N authors into data/bt_prod_sample.parquet, then
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
DATA_DIR            = Path(__file__).parent.parent.parent / "data"
RECIPES_PATH        = DATA_DIR / "bt_prod.parquet"
SAMPLE_PATH         = DATA_DIR / "bt_prod_sample.parquet"
OUTPUT_DIR          = Path(__file__).parent / "cleaned"
SUMMARIES_PATH      = OUTPUT_DIR / "recipe_summaries.parquet"
FULL_SUMMARIES_PATH = OUTPUT_DIR / "recipe_summaries_full.parquet"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N_AUTHORS = 30

ACTION_KEYWORDS    = {"action"}
CONDITION_KEYWORDS = {"if", "elsif", "while_condition"}

# UUID-format keys — both standard hyphen form and double-underscore URL-encoded form.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}([-_]|__2d__)[0-9a-f]{4}([-_]|__2d__)[0-9a-f]{4}([-_]|__2d__)[0-9a-f]{4}([-_]|__2d__)[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Trailing tenant/account IDs appended to field names (e.g. cf_field_name_109001).
_TRAILING_ID_RE = re.compile(r"_\d{4,}$")

# Strips all numeric ID segments from connector names (e.g. connector_3165546_1699532902 → connector).
_CONNECTOR_ID_RE = re.compile(r"(_\d{4,})+$")

# Datapill expressions embedded in URL strings — strip from the static prefix onward.
_DATAPILL_RE = re.compile(r"#\{_dp\(.*", re.DOTALL)

# Input keys that are structural metadata, not user-facing field names.
_INPUT_SKIP = {"operand", "type", "conditions", "source",
               "parameters_schema_json", "result_schema_json",
               "job_report_schema", "job_report_config", "job_url", "job_id",
               "calling_job_id"}

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
    """Filter bt_prod.parquet to the top N_AUTHORS by recipe count."""
    print(f"Loading {RECIPES_PATH} ...")
    df = pd.read_parquet(RECIPES_PATH)
    print(f"  Rows: {len(df):,}  |  Authors: {df['author_id'].nunique()}")

    author_counts = df.groupby("author_id").size().sort_values(ascending=False)
    selected = author_counts.head(N_AUTHORS)
    print(f"\nSelected top {N_AUTHORS} authors by recipe count:")
    for aid, cnt in selected.items():
        print(f"  author_id={aid:>10}  recipes={cnt}")

    sample = df[df["author_id"].isin(selected.index)].copy()
    print(f"\nFinal sample: {len(sample):,} rows across {sample['author_id'].nunique()} authors")
    print(f"  flow_ids : {sample['flow_id'].nunique()} unique recipes")

    sample.to_parquet(SAMPLE_PATH, index=False)
    print(f"Saved → {SAMPLE_PATH}")


# ---------------------------------------------------------------------------
# Step 2 — Build recipe summaries
# ---------------------------------------------------------------------------

def _clean_url(raw: str) -> str:
    """Strip trailing datapill expressions from a URL, return the static prefix."""
    return _DATAPILL_RE.sub("", raw).rstrip("/? ")


def _raw_datapill_names(schema_list: list) -> list[str]:
    """Recursively collect unique raw field names from an extended_output_schema list."""
    seen: set[str] = set()
    names: list[str] = []

    def _collect(items: list) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            n = item.get("name") or ""
            if n and not _UUID_RE.match(n) and not n.isdigit() and n not in seen:
                seen.add(n)
                names.append(n)
            _collect(item.get("properties", []))

    _collect(schema_list)
    return names


def extract_conditions(step: dict) -> dict | None:
    """Extract condition structure from an if / elsif / while_condition step."""
    inp = step.get("input", {})
    if not isinstance(inp, dict) or "conditions" not in inp:
        return None
    operands = [c.get("operand") for c in inp.get("conditions", [])]
    return {
        "logic":    inp.get("operand"),
        "operands": operands,
    }


def extract_step_values(step: dict) -> list[tuple[str, str]]:
    """
    Return whitelisted key-value pairs from a step's input to include in the summary.
    Only specific fields per step type are extracted — everything else is ignored.
    """
    provider = step.get("provider") or ""
    name     = step.get("name") or ""
    inp      = step.get("input") or {}
    if not isinstance(inp, dict):
        return []

    pairs: list[tuple[str, str]] = []

    def _recipe_call_pair(label: str) -> None:
        fid = inp.get("flow_id")
        if fid:
            dpls = step.get("dynamicPickListSelection") or {}
            recipe_name = dpls.get("flow_id", "")
            value = str(fid)
            if recipe_name:
                value += f"  [{recipe_name}]"
            pairs.append((label, value))

    if provider == "workato_recipe_function" and name == "call_recipe":
        _recipe_call_pair("calls recipe")

    elif provider == "workato_service" and name in ("call_service", "call_service_async"):
        _recipe_call_pair("calls service")

    elif provider == "workato_webhooks" and name == "new_event":
        ws = inp.get("webhook_suffix")
        if ws:
            pairs.append(("event", str(ws)))
        req = inp.get("request")
        if isinstance(req, dict):
            wt = req.get("webhook_type")
            if wt:
                pairs.append(("type", str(wt)))

    elif provider == "salesforce" and "webhook" in name:
        sobj = inp.get("sobject_name")
        if sobj:
            pairs.append(("object", str(sobj)))
        field_list = inp.get("field_list")
        if field_list:
            fields = [f.strip() for f in str(field_list).splitlines() if f.strip()]
            pairs.append(("fields", ", ".join(fields[:10])))

    elif provider == "jira" and "webhook" in name:
        jql = inp.get("jql")
        if jql:
            pairs.append(("jql", str(jql)[:100]))

    elif provider == "service_now" and "webhook" in name:
        table = inp.get("table")
        if table:
            pairs.append(("table", str(table)))

    elif "github" in provider and "webhook" in name:
        event = inp.get("event")
        org   = inp.get("org")
        if event:
            pairs.append(("event", str(event)))
        if org:
            pairs.append(("org", str(org)))

    elif provider == "event_brite" and "webhook" in name:
        oid = inp.get("organization_id")
        eid = inp.get("event_id")
        if oid:
            pairs.append(("organization_id", str(oid)))
        if eid:
            pairs.append(("event_id", str(eid)))

    elif provider == "box" and "webhook" in name:
        events = inp.get("events")
        folder = inp.get("folder")
        if events:
            pairs.append(("events", str(events)))
        if folder:
            pairs.append(("folder", str(folder)))

    elif name == "__adhoc_http_action":
        raw = inp.get("path") or inp.get("url") or ""
        if raw:
            pairs.append(("url", _clean_url(str(raw))))

    elif provider == "rest" and name == "make_request_v2":
        req = inp.get("request")
        raw = (req.get("url") if isinstance(req, dict) else None) or inp.get("url") or ""
        if raw:
            pairs.append(("url", _clean_url(str(raw))))

    return pairs


def summary_lines(step: dict, depth: int) -> list[str]:
    """
    Return indented summary lines for a single step.

    Main line: title (if present) appended to the step label.
    Sub-lines: whitelisted input values (url, flow_id, webhook_suffix, etc.)
               plus input field key names for action steps.
    """
    indent = "  " * depth
    sub    = indent + "  "

    kw       = step.get("keyword", "")
    provider = step.get("provider") or ""
    name     = step.get("name") or ""

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

    result = [f"{indent}- {label}"]

    for k, v in extract_step_values(step):
        result.append(f"{sub}{k}: {v}")

    if kw in ACTION_KEYWORDS:
        inp = step.get("input", {})
        if isinstance(inp, dict):
            keys = [
                k for k in inp
                if k not in _INPUT_SKIP and not _UUID_RE.match(str(k))
            ]
            if keys:
                result.append(f"{sub}input fields: {', '.join(keys)}")

    dp_names = _raw_datapill_names(step.get("extended_output_schema") or [])
    if dp_names:
        result.append(f"{sub}datapill fields: {', '.join(dp_names)}")

    return result


def build_recipe_body(root: dict) -> dict:
    """
    Walk the recipe tree once and collect all summary fields.

    Returns a dict with:
      connectors    — sorted distinct provider names
      actions       — sorted distinct provider/name pairs (triggers + actions)
      input_fields  — sorted distinct input key names across all action steps
      datapill_fields — sorted distinct output schema field names
      step_count    — total node count
      search_text   — full indented step summary text
    """
    providers:       set[str] = set()
    actions:         set[str] = set()
    input_fields:    set[str] = set()
    datapill_fields: set[str] = set()
    step_count = 0
    lines: list[str] = []

    def collect_datapill_names(schema_list: list) -> None:
        for item in schema_list:
            if not isinstance(item, dict):
                continue
            n = item.get("name") or ""
            if n and not _UUID_RE.match(n) and not n.isdigit():
                datapill_fields.add(_TRAILING_ID_RE.sub("", n.lower()))
            collect_datapill_names(item.get("properties", []))

    def walk(step: dict, depth: int = 0) -> None:
        nonlocal step_count
        step_count += 1

        kw       = step.get("keyword", "")
        provider = step.get("provider") or ""
        name     = step.get("name") or ""

        if provider:
            providers.add(_CONNECTOR_ID_RE.sub("", provider))

        if kw in ACTION_KEYWORDS | {"trigger"} and provider and name:
            clean_provider = _CONNECTOR_ID_RE.sub("", provider)
            clean_name = _CONNECTOR_ID_RE.sub("", name)
            actions.add(f"{clean_provider}/{clean_name}")

        if kw in ACTION_KEYWORDS:
            inp = step.get("input") or {}
            if isinstance(inp, dict):
                for k in inp:
                    sk = str(k)
                    if k not in _INPUT_SKIP and not _UUID_RE.match(sk) and not sk.isdigit():
                        input_fields.add(_TRAILING_ID_RE.sub("", sk.lower()))

        collect_datapill_names(step.get("extended_output_schema") or [])

        lines.extend(summary_lines(step, depth))

        for child in step.get("block", []):
            walk(child, depth + 1)

    walk(root)

    search_text = "\n".join(lines)

    return {
        "connectors":       " ".join(sorted(providers)),
        "actions":          " ".join(sorted(actions)),
        "input_fields":     " ".join(sorted(input_fields)),
        "datapill_fields":  " ".join(sorted(datapill_fields)),
        "step_count":       step_count,
        "search_text":      search_text,
    }


def make_recipe_uid(author_id: int, flow_id: int, version_no: int) -> str:
    return f"{author_id}_{flow_id}_v{version_no}"


def process_recipe(row: pd.Series) -> dict | None:
    """Return cleaned summary fields for one recipe row, or None on parse error."""
    flow_id    = int(row["flow_id"])
    version_no = int(row["version_no"])
    author_id  = int(row["author_id"])

    try:
        root = json.loads(row["code"])
    except Exception as e:
        print(f"  SKIP flow_id={flow_id} v{version_no}: JSON parse error – {e}")
        return None

    body = build_recipe_body(root)

    return {
        "recipe_uid":  make_recipe_uid(author_id, flow_id, version_no),
        "flow_id":     flow_id,
        "version_no":  version_no,
        "author_id":   author_id,
        "payload_json": row["code"],
        **body,
    }


def build_summaries(input_path: Path, output_path: Path) -> None:
    """Parse raw recipe code for each row and emit cleaned summary fields."""
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
