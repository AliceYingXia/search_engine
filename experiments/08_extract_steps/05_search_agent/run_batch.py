"""
run_batch.py — Run a fixed set of queries against the search agent and save results.

Usage:
    python run_batch.py
    python run_batch.py --output results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Agent is in the same directory
sys.path.insert(0, str(Path(__file__).parent))
from agent import run_agent

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

QUERIES: dict[str, list[str]] = {
    "VALID_TAG": [
        "Find recipes with tag salesforce that sync leads",
        "Show me recipes with tag jira that post Slack notifications",
        "Which recipes with tag snowflake pull data from NetSuite?",
        "Find all recipes tagged clock that run daily",
        "Show recipes with tag coupa_connector related to purchase orders",
        "Find recipes with tag slack_bot that handle incident alerts",
        "Which recipes with tag outreach manage sequence states?",
        "Find recipes tagged google_sheets that process employee data",
        "Show me recipes with tag open_ai that summarize content",
        "Which recipes with tag workato_api_platform expose an API endpoint?",
    ],
    "INVALID_TAG": [
        "Find recipes with tag zendesk that handle support tickets",
        "Show recipes with tag hubspot that sync contacts",
        "Which recipes with tag stripe process payments?",
        "Find all recipes tagged servicenow for IT workflows",
        "Show recipes with tag nonexistent_connector that do anything",
        "Find recipes with tag marketo that nurture leads",
        "Which recipes tagged bamboohr sync employee records?",
        "Show me recipes with tag twilio that send SMS alerts",
        "Find recipes with tag shopify that sync orders",
        "Which recipes with tag fake_tag_xyz handle data transformation?",
    ],
}

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(output_path: Path) -> None:
    results = []
    total = sum(len(qs) for qs in QUERIES.values())
    idx = 0

    for category, queries in QUERIES.items():
        for query in queries:
            idx += 1
            print(f"[{idx}/{total}] [{category}] {query}", flush=True)
            try:
                answer = run_agent(query)
                status = "ok"
            except Exception:
                answer = traceback.format_exc()
                status = "error"

            results.append({
                "category": category,
                "query": query,
                "status": status,
                "answer": answer,
            })
            print(f"  → {status}\n", flush=True)

    output = {
        "run_at": datetime.now().isoformat(),
        "total": total,
        "results": results,
    }
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nSaved {total} results to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="batch_results.json",
                        help="Output JSON file (default: batch_results.json)")
    args = parser.parse_args()
    run_all(Path(args.output))


if __name__ == "__main__":
    main()
