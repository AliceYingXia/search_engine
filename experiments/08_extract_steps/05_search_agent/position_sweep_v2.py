"""
position_sweep_v2.py — Position sweep with a richer ground-truth target.

Target recipe: 1873346_60999102_v2
  Trigger: salesforce / new_custom_object_webhook (LinkSquares Agreement)
  Steps: search_sobjects_soql, search_sobjects, update_sobject (×4)

Query crafted to have strong, unambiguous expected steps so dilution is
clearly visible when the target is buried among unrelated filler recipes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from openai import OpenAI
from opensearchpy import OpenSearch

from search_recipes import (
    _call_extraction_llm,
    search_recipes,
)

# Ground-truth expected steps for the target recipe
EXPECTED_STEPS = {
    "new_custom_object_webhook",
    "search_sobjects_soql",
    "search_sobjects",
    "update_sobject",
}

TARGET_RECIPE_ID = "1873346_60999102_v2"
TARGET_QUERY = (
    "Find Salesforce recipes triggered by a new agreement webhook that look up "
    "related account records and update partner or contract status fields"
)
FILLER_QUERY = "Show me recipes with tag jira that post Slack notifications"


def run() -> None:
    os_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}],
        http_auth=("admin", os.environ["OPENSEARCH_PASSWORD"]),
        use_ssl=False, verify_certs=False,
    )
    sync_client = OpenAI(api_key=os.environ["API_KEY"], base_url=os.environ["BASE_URL"])

    # Fetch target directly by ID
    raw = os_client.get(
        index="bt_recipe",
        id=TARGET_RECIPE_ID,
        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
    )
    target = {"recipe_uid": TARGET_RECIPE_ID, **raw["_source"]}

    # Fetch filler recipes
    filler_results, _ = search_recipes(os_client, FILLER_QUERY, "mixed", top_k=10)
    fillers = [r for r in filler_results if r["recipe_uid"] != TARGET_RECIPE_ID][:9]

    print(f"Target: {TARGET_RECIPE_ID} ({len(target.get('search_text',''))} chars)")
    print(f"Query:  {TARGET_QUERY}")
    print(f"Expected steps: {sorted(EXPECTED_STEPS)}")
    print()

    # Baseline: target alone
    baseline = _call_extraction_llm(sync_client, TARGET_QUERY, [target])
    baseline_steps = baseline[0].get("relevant_steps", []) if baseline else []
    baseline_hit = sum(1 for s in baseline_steps if any(e in s for e in EXPECTED_STEPS))

    print(f"{'Position':>10} {'Steps':>6} {'Hits':>5}  Step names")
    print("-" * 90)
    print(f"{'baseline':>10} {len(baseline_steps):>6} {baseline_hit:>5}  {baseline_steps}")

    positions = [1, 2, 3, 5, 7, 10]
    sweep_results = [{"position": "baseline", "steps": baseline_steps, "hits": baseline_hit}]

    for pos in positions:
        before = fillers[: pos - 1]
        after  = fillers[pos - 1 : pos - 1 + (10 - pos)]
        batch  = before + [target] + after

        try:
            extracted = _call_extraction_llm(sync_client, TARGET_QUERY, batch)
            uid_map = {r.get("recipe_uid"): r for r in extracted}
            steps = uid_map.get(TARGET_RECIPE_ID, {}).get("relevant_steps", [])
        except Exception as e:
            steps = [f"ERROR: {e}"]

        hits = sum(1 for s in steps if any(e in s for e in EXPECTED_STEPS))
        print(f"{pos:>10} {len(steps):>6} {hits:>5}  {steps}")
        sweep_results.append({"position": pos, "steps": steps, "hits": hits})

    out = Path(__file__).parent / "position_sweep_v2_results.json"
    out.write_text(json.dumps({
        "target_recipe": TARGET_RECIPE_ID,
        "query": TARGET_QUERY,
        "expected_steps": sorted(EXPECTED_STEPS),
        "results": sweep_results,
    }, indent=2, ensure_ascii=False))
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    run()
