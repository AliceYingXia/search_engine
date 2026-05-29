"""
position_sweep_v3.py — Position sweep with a third ground-truth recipe.

Target recipe: 4818251_59278429_v20
  SOAR recipe: Slack bot command → validate user → look up Workato table →
  create/update Jira issue → invoke response functions → post Slack updates.

8 distinct step types:
  slack_bot/bot_command_v2, slack_bot/block_kit_modals, slack_bot/get_user_by_email,
  slack_bot/post_bot_message, workato_db_table/get_records, jira/find_user,
  jira/create_issue, jira/create_comment, jira/update_issue_status,
  workato_recipe_function/call_recipe, slack/post_message_to_channel
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

EXPECTED_STEPS = {
    "bot_command_v2",
    "block_kit_modals",
    "get_user_by_email",
    "post_bot_message",
    "get_records",
    "find_user",
    "create_issue",
    "create_comment",
    "update_issue_status",
    "call_recipe",
    "post_message_to_channel",
}

TARGET_RECIPE_ID = "4818251_59278429_v20"
TARGET_QUERY = (
    "Find SOAR recipes triggered by a Slack bot command that open an interactive modal, "
    "validate the requester, look up reference data, create a Jira issue with investigation "
    "context, and post status updates back to Slack"
)
FILLER_QUERY = "Find Salesforce recipes triggered by a new agreement webhook that look up related account records and update partner or contract status fields"


def count_hits(steps: list[str]) -> int:
    return sum(1 for s in steps if any(e in s for e in EXPECTED_STEPS))


def run() -> None:
    os_client = OpenSearch(
        hosts=[{"host": "localhost", "port": 9200}],
        http_auth=("admin", os.environ["OPENSEARCH_PASSWORD"]),
        use_ssl=False, verify_certs=False,
    )
    sync_client = OpenAI(api_key=os.environ["API_KEY"], base_url=os.environ["BASE_URL"])

    raw = os_client.get(
        index="bt_recipe",
        id=TARGET_RECIPE_ID,
        params={"_source_excludes": "description_qwen,usage_qwen,combined_qwen"},
    )
    target = {"recipe_uid": TARGET_RECIPE_ID, **raw["_source"]}

    filler_results, _ = search_recipes(os_client, FILLER_QUERY, "mixed", top_k=10)
    fillers = [r for r in filler_results if r["recipe_uid"] != TARGET_RECIPE_ID][:9]

    print(f"Target: {TARGET_RECIPE_ID} ({len(target.get('search_text',''))} chars)")
    print(f"Query:  {TARGET_QUERY}")
    print(f"Expected step types ({len(EXPECTED_STEPS)}): {sorted(EXPECTED_STEPS)}")
    print()

    baseline = _call_extraction_llm(sync_client, TARGET_QUERY, [target])
    baseline_steps = baseline[0].get("relevant_steps", []) if baseline else []
    baseline_hits = count_hits(baseline_steps)

    print(f"{'Position':>10} {'Steps':>6} {'Hits':>5}  Step names")
    print("-" * 100)
    print(f"{'baseline':>10} {len(baseline_steps):>6} {baseline_hits:>5}  {baseline_steps}")

    positions = [1, 2, 3, 5, 7, 10]
    sweep_results = [{"position": "baseline", "steps": baseline_steps, "hits": baseline_hits}]

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

        hits = count_hits(steps)
        print(f"{pos:>10} {len(steps):>6} {hits:>5}  {steps}")
        sweep_results.append({"position": pos, "steps": steps, "hits": hits})

    out = Path(__file__).parent / "position_sweep_v3_results.json"
    out.write_text(json.dumps({
        "target_recipe": TARGET_RECIPE_ID,
        "query": TARGET_QUERY,
        "expected_steps": sorted(EXPECTED_STEPS),
        "results": sweep_results,
    }, indent=2, ensure_ascii=False))
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    run()
