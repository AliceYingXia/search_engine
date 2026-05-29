"""
eval_run.py — Run the standard 21-query test against the filter-count-driven
hybrid pipeline. Captures per-branch diagnostics and computes recall/precision
against the golden datasets for Part 1.

Usage:
    python eval_run.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

SEARCH_DIR = Path(__file__).parent.parent / "05_search"
sys.path.insert(0, str(SEARCH_DIR))

from search_recipes import (  # noqa: E402
    BM25_SCORE_FLOOR,
    DENSE_SCORE_FLOOR,
    _bm25_query,
    _extract_keyword_filters,
    _run_bm25,
    _run_knn,
    _rrf_fusion,
    _tag_exists,
    embed_query,
)
import agent  # noqa: E402

OS_CLIENT = agent._os_client
LLM_CLIENT = agent._agent_client


def call_agent(user_msg: str) -> dict | None:
    resp = LLM_CLIENT.chat.completions.create(
        model=agent.AGENT_MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": agent.SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        tools=[agent.SEARCH_TOOL],
        tool_choice="auto",
    )
    tcs = resp.choices[0].message.tool_calls or []
    if not tcs:
        return None
    return json.loads(tcs[0].function.arguments)


def run_search_verbose(query: str, dense_query: str,
                       tag: str | None = None) -> dict:
    """Mirror of search_recipes() with per-leg diagnostics."""
    tag_valid = True
    tag_matched = True
    if tag and not _tag_exists(OS_CLIENT, tag):
        query = f"{query} {tag}"
        dense_query = f"{dense_query} {tag}"
        tag = None
        tag_valid = False
        tag_matched = False

    keyword_filters = _extract_keyword_filters(query)
    n_filters = len(keyword_filters)

    if n_filters >= 2:
        q_body = _bm25_query(query, ["search_text"])
        bm25_hits = _run_bm25(OS_CLIENT, q_body, tag, keyword_filters)
        return {
            "branch": "bm25_only", "n_filters": n_filters,
            "tag_valid": tag_valid, "tag_matched": tag_matched,
            "bm25_ids": [h["_id"] for h in bm25_hits],
            "dense_ids": [],
            "fused_ids": [h["_id"] for h in bm25_hits],
        }

    if n_filters == 1:
        bm25_fields = ["search_text"]
        bm25_floor  = None
        dense_floor = None
    else:
        bm25_fields = ["search_text", "description", "usage"]
        bm25_floor  = BM25_SCORE_FLOOR
        dense_floor = DENSE_SCORE_FLOOR

    q_body = _bm25_query(query, bm25_fields)
    vector = embed_query(dense_query)
    bm25_hits = _run_bm25(OS_CLIENT, q_body, tag, keyword_filters)
    if bm25_floor is not None:
        bm25_hits = [h for h in bm25_hits if h["_score"] >= bm25_floor]
    dense_hits = _run_knn(OS_CLIENT, vector, tag, keyword_filters, floor=dense_floor)
    top = _rrf_fusion(dense_hits, bm25_hits)
    return {
        "branch": "hybrid_1filter" if n_filters == 1 else "hybrid_0filter",
        "n_filters": n_filters,
        "tag_valid": tag_valid, "tag_matched": tag_matched,
        "bm25_ids": [h["_id"] for h in bm25_hits],
        "dense_ids": [h["_id"] for h in dense_hits],
        "fused_ids": [doc_id for doc_id, _ in top],
    }


def load_golden(name: str) -> set[str]:
    path = Path(__file__).parent / "output" / f"{name}.csv"
    with path.open() as f:
        return {row["recipe_uid"] for row in csv.DictReader(f)}


def metrics(returned_ids: list[str], golden_ids: set[str]) -> tuple[int, float, float]:
    s = set(returned_ids)
    tp = len(s & golden_ids)
    return tp, tp / len(golden_ids) if golden_ids else 0.0, tp / len(returned_ids) if returned_ids else 0.0


PART_1 = [
    ("show me recipes with action create_record in salesforce",                       "salesforce_create_record"),
    ("show me recipes with action create_records in salesforce",                      "salesforce_create_record"),
    ("what recipes use both salesforce netsuite",                                     "salesforce_and_netsuite"),
    ("what recipes sync Salesforce and NetSuite",                                     "salesforce_and_netsuite"),
    ("SF NS sync",                                                                    "salesforce_and_netsuite"),
    ("which recipes post_bot_message in slack",                                       "slack_post_bot_message"),
    ("which recipes post_bot_messages in slack",                                      "slack_post_bot_message"),
    ("which recipes send slack bot messages",                                         "slack_post_bot_message"),
    ("find recipes which automate team notifications in chat",                        "slack_post_bot_message"),
    ("find recipes about slack channel",                                              "slack_channel"),
    ("find recipes about slack channels",                                             "slack_channel"),
    ("please find recipes with action create_record in salesforce",                   "salesforce_create_record"),
    ("please find recipes with action create_record in salesforce tagged netsuite",   "salesforce_create_record"),
    ("please find recipes with action create_record in salesforce tagged asdfghij",   "salesforce_create_record"),
]

PART_2 = [
    "find recipes that create records in salesforce",
    "find recipes that automate Salesforce record creation",
    "find recips about quote to cash automation",
    "which recipes send slack bot messages",
    "find recipes which automate team notifications in chat",
    "find recipes about slack channel",
    "find recipes about slack channels",
]


def run_one(user_msg: str, golden_name: str | None = None) -> dict:
    args = call_agent(user_msg)
    if args is None or not args.get("dense_query"):
        return {"user_msg": user_msg, "error": "LLM tool args missing"}
    diag = run_search_verbose(args["query"], args["dense_query"], tag=args.get("tag"))
    row = {
        "user_msg":      user_msg,
        "query":         args["query"],
        "dense_query":   args["dense_query"],
        "tag_requested": args.get("tag") or "",
        "branch":        diag["branch"],
        "n_filters":     diag["n_filters"],
        "tag_valid":     diag["tag_valid"],
        "tag_matched":   diag["tag_matched"],
        "bm25":          len(diag["bm25_ids"]),
        "dense":         len(diag["dense_ids"]),
        "fused":         len(diag["fused_ids"]),
    }
    if golden_name:
        golden = load_golden(golden_name)
        tp, recall, precision = metrics(diag["fused_ids"], golden)
        row.update({
            "golden_name": golden_name, "golden_size": len(golden),
            "tp": tp, "recall": recall, "precision": precision,
        })
    return row


def main() -> None:
    print("=" * 78)
    print("PART 1 — compared with golden datasets")
    print("=" * 78)
    rows1 = []
    for i, (msg, golden) in enumerate(PART_1, 1):
        print(f"\n[{i}/{len(PART_1)}] {msg}")
        row = run_one(msg, golden)
        rows1.append(row)
        if "error" in row:
            print(f"   ERROR: {row['error']}")
            continue
        print(f"   branch={row['branch']:<15} n_filters={row['n_filters']}")
        print(f"   query={row['query']!r}")
        print(f"   dense_query={row['dense_query']!r} tag={row['tag_requested']!r}")
        print(f"   tag_valid={row['tag_valid']} bm25={row['bm25']} dense={row['dense']} fused={row['fused']}")
        print(f"   golden={row['golden_name']}({row['golden_size']}) tp={row['tp']} "
              f"recall={row['recall']:.1%} precision={row['precision']:.1%}")

    print("\n" + "=" * 78)
    print("PART 2 — exploratory (no golden)")
    print("=" * 78)
    rows2 = []
    for i, msg in enumerate(PART_2, 1):
        print(f"\n[{i}/{len(PART_2)}] {msg}")
        row = run_one(msg)
        rows2.append(row)
        if "error" in row:
            print(f"   ERROR: {row['error']}")
            continue
        print(f"   branch={row['branch']:<15} n_filters={row['n_filters']}")
        print(f"   query={row['query']!r}")
        print(f"   dense_query={row['dense_query']!r} tag={row['tag_requested']!r}")
        print(f"   bm25={row['bm25']} dense={row['dense']} fused={row['fused']}")

    out = Path(__file__).parent / "eval_results.json"
    with out.open("w") as f:
        json.dump({"part1": rows1, "part2": rows2}, f, indent=2, default=str)
    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
