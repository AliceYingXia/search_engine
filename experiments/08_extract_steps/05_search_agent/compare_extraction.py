"""
compare_extraction.py — Compare batch vs individual step extraction over 20 queries.

For each query:
  1. Fetch OpenSearch results once (shared)
  2. Run batch extraction (all recipes in one LLM call)
  3. Run individual extraction (one LLM call per recipe, parallelized)
  4. Record coverage, depth, latency, LLM call count

Output: compare_extraction_results.json + printed summary table
"""

from __future__ import annotations

import asyncio
import json  # still needed for output file writing
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from openai import AsyncOpenAI, OpenAI
from opensearchpy import OpenSearch

from search_recipes import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionResult,
    GPT_MODEL,
    RecipeSteps,
    TOP_K_DEFAULT,
    _call_extraction_llm,
    search_recipes,
)

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
# Individual extraction (async, parallelized)
# ---------------------------------------------------------------------------

async def _extract_single_async(
    ac: AsyncOpenAI, query: str, recipe: dict
) -> dict:
    uid = recipe["recipe_uid"]
    search_text = recipe.get("search_text", "")
    user_prompt = f"Query: {query}\n\nRecipes:\n[Recipe {uid}]\n{search_text}"
    resp = await ac.beta.chat.completions.parse(
        model=GPT_MODEL,
        max_completion_tokens=1024,
        temperature=0,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format=ExtractionResult,
    )
    result = resp.choices[0].message.parsed
    if result and result.recipes:
        return result.recipes[0].model_dump()
    return {"recipe_uid": uid, "relevant_steps": []}


async def run_individual(ac: AsyncOpenAI, query: str, results: list[dict]) -> list[dict]:
    tasks = [_extract_single_async(ac, query, r) for r in results]
    return await asyncio.gather(*tasks)

# ---------------------------------------------------------------------------
# Per-query experiment
# ---------------------------------------------------------------------------

def run_query(
    query: str,
    tag_hint: str | None,
    os_client: OpenSearch,
    sync_client: OpenAI,
    async_client: AsyncOpenAI,
) -> dict:
    # Extract tag from query if present
    tag = None
    if "with tag " in query:
        tag = query.split("with tag ")[1].split()[0].rstrip("?.,")
    elif "tagged " in query:
        tag = query.split("tagged ")[1].split()[0].rstrip("?.,")

    # Fetch OpenSearch results once
    results, tag_matched = search_recipes(
        os_client, query, "mixed", top_k=TOP_K_DEFAULT, tag=tag
    )
    num_recipes = len(results)

    # --- Batch (all recipes, one call) ---
    t0 = time.perf_counter()
    batch_extracted = _call_extraction_llm(sync_client, query, results)
    batch_latency = time.perf_counter() - t0
    batch_coverage    = sum(1 for r in batch_extracted if r.get("relevant_steps"))
    batch_total_steps = sum(len(r.get("relevant_steps", [])) for r in batch_extracted)

    # --- Individual (parallel async, one call per recipe) ---
    t0 = time.perf_counter()
    individual_extracted = asyncio.run(run_individual(async_client, query, results))
    individual_latency = time.perf_counter() - t0
    individual_coverage    = sum(1 for r in individual_extracted if r.get("relevant_steps"))
    individual_total_steps = sum(len(r.get("relevant_steps", [])) for r in individual_extracted)

    # --- Batch-n1 (one recipe per call, sequential — isolates context size from parallelism) ---
    t0 = time.perf_counter()
    batch_n1_extracted = []
    for r in results:
        extracted = _call_extraction_llm(sync_client, query, [r])
        batch_n1_extracted.append(extracted[0] if extracted else {"recipe_uid": r["recipe_uid"], "relevant_steps": []})
    batch_n1_latency = time.perf_counter() - t0
    batch_n1_coverage    = sum(1 for r in batch_n1_extracted if r.get("relevant_steps"))
    batch_n1_total_steps = sum(len(r.get("relevant_steps", [])) for r in batch_n1_extracted)

    return {
        "query": query,
        "tag": tag,
        "tag_matched": tag_matched,
        "num_recipes": num_recipes,
        "batch": {
            "coverage": batch_coverage,
            "total_steps": batch_total_steps,
            "latency_s": round(batch_latency, 2),
            "llm_calls": 1,
            "per_recipe": batch_extracted,
        },
        "individual": {
            "coverage": individual_coverage,
            "total_steps": individual_total_steps,
            "latency_s": round(individual_latency, 2),
            "llm_calls": num_recipes,
            "per_recipe": individual_extracted,
        },
        "batch_n1": {
            "coverage": batch_n1_coverage,
            "total_steps": batch_n1_total_steps,
            "latency_s": round(batch_n1_latency, 2),
            "llm_calls": num_recipes,
            "per_recipe": batch_n1_extracted,
        },
    }

# ---------------------------------------------------------------------------
# Two-pass extraction (free-form → structured)
# ---------------------------------------------------------------------------

TWO_PASS_SYSTEM_PROMPT_1 = """\
You are given a search query and one automation recipe.
Think out loud: which steps in this recipe are relevant to the query and why?
Be thorough — mention every step that relates to the query intent, even loosely.
Reference the exact action names from the recipe (e.g. "google_sheets / search_spreadsheet_rows_v4_new")."""

TWO_PASS_SYSTEM_PROMPT_2 = """\
You are given an analysis of a recipe and the original recipe steps.
Extract only the exact step identifiers mentioned as relevant in the analysis.
A step identifier looks like: "connector / action_name" or "trigger: connector / action_name".
Return them as a JSON array of strings with no surrounding text: ["step1", "step2", ...]
If none are mentioned, return []."""


async def _two_pass_single(ac: AsyncOpenAI, query: str, recipe: dict) -> dict:
    uid = recipe["recipe_uid"]
    search_text = recipe.get("search_text", "")

    # Pass 1 — free-form reasoning
    resp1 = await ac.chat.completions.create(
        model=GPT_MODEL,
        max_completion_tokens=1024,
        temperature=0,
        messages=[
            {"role": "system", "content": TWO_PASS_SYSTEM_PROMPT_1},
            {"role": "user",   "content": f"Query: {query}\n\nRecipe [{uid}]:\n{search_text}"},
        ],
    )
    analysis = resp1.choices[0].message.content.strip()

    # Pass 2 — extract step identifiers from the analysis
    resp2 = await ac.chat.completions.create(
        model=GPT_MODEL,
        max_completion_tokens=512,
        temperature=0,
        messages=[
            {"role": "system", "content": TWO_PASS_SYSTEM_PROMPT_2},
            {"role": "user",   "content": f"Analysis:\n{analysis}\n\nRecipe steps:\n{search_text}"},
        ],
    )
    raw = resp2.choices[0].message.content.strip()
    try:
        steps = json.loads(raw)
        if not isinstance(steps, list):
            steps = []
    except Exception:
        steps = []

    return {"recipe_uid": uid, "relevant_steps": steps}


async def _run_two_pass(ac: AsyncOpenAI, query: str, results: list[dict]) -> list[dict]:
    tasks = [_two_pass_single(ac, query, r) for r in results]
    return await asyncio.gather(*tasks)


def run_two_pass_experiment(
    os_client: OpenSearch,
    async_client: AsyncOpenAI,
    sync_client: OpenAI,
    queries: list[tuple[str, str]],
) -> None:
    """Compare single-pass individual vs two-pass (free-form → structured) extraction."""
    print(f"\n{'Two-pass experiment — avg across ' + str(len(queries)) + ' queries'}")
    print(f"{'Query':<52} {'1P-cov':>7} {'2P-cov':>7} {'1P-stp':>7} {'2P-stp':>7} {'1P-lat':>7} {'2P-lat':>7}")
    print("-" * 100)

    rows = []
    for query, tag in queries:
        results, _ = search_recipes(os_client, query, "mixed", top_k=TOP_K_DEFAULT, tag=tag)

        # Single-pass individual (baseline)
        t0 = time.perf_counter()
        try:
            one_pass = asyncio.run(run_individual(async_client, query, results))
        except Exception:
            one_pass = []
        one_pass_lat = time.perf_counter() - t0
        one_cov   = sum(1 for r in one_pass if r.get("relevant_steps"))
        one_steps = sum(len(r.get("relevant_steps", [])) for r in one_pass)

        # Two-pass
        t0 = time.perf_counter()
        try:
            two_pass = asyncio.run(_run_two_pass(async_client, query, results))
        except Exception:
            two_pass = []
        two_pass_lat = time.perf_counter() - t0
        two_cov   = sum(1 for r in two_pass if r.get("relevant_steps"))
        two_steps = sum(len(r.get("relevant_steps", [])) for r in two_pass)

        print(
            f"{query[:51]:<52} {one_cov:>7} {two_cov:>7}"
            f" {one_steps:>7} {two_steps:>7}"
            f" {one_pass_lat:>7.1f} {two_pass_lat:>7.1f}"
        )
        rows.append({
            "query": query, "tag": tag,
            "one_pass": {"coverage": one_cov, "total_steps": one_steps, "latency_s": round(one_pass_lat, 2), "llm_calls": len(results), "per_recipe": one_pass},
            "two_pass": {"coverage": two_cov, "total_steps": two_steps, "latency_s": round(two_pass_lat, 2), "llm_calls": len(results) * 2, "per_recipe": two_pass},
        })

    def avg(vals): return round(sum(vals) / len(vals), 2) if vals else 0
    ok = rows
    print(
        f"\n{'Average':<52}"
        f" {avg([r['one_pass']['coverage'] for r in ok]):>7.1f}"
        f" {avg([r['two_pass']['coverage'] for r in ok]):>7.1f}"
        f" {avg([r['one_pass']['total_steps'] for r in ok]):>7.1f}"
        f" {avg([r['two_pass']['total_steps'] for r in ok]):>7.1f}"
        f" {avg([r['one_pass']['latency_s'] for r in ok]):>7.1f}"
        f" {avg([r['two_pass']['latency_s'] for r in ok]):>7.1f}"
    )

    out = Path(__file__).parent / "two_pass_results.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"\nTwo-pass results saved to {out}")

# ---------------------------------------------------------------------------
# Batch-size sweep
# ---------------------------------------------------------------------------

def _chunked(lst: list, n: int) -> list[list]:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def run_batch_size_sweep(
    os_client: OpenSearch,
    sync_client: OpenAI,
    queries: list[tuple[str, str]],
    max_batch_size: int = 10,
) -> None:
    """For each batch size 1..max_batch_size, run all queries and report avg coverage/steps/latency."""
    # Pre-fetch OpenSearch results for all queries once
    query_results = []
    for query, tag in queries:
        results, _ = search_recipes(os_client, query, "mixed", top_k=TOP_K_DEFAULT, tag=tag)
        query_results.append((query, results))

    print(f"\n{'Batch size sweep — avg across ' + str(len(queries)) + ' queries'}")
    print(f"{'size':>6} {'coverage':>10} {'total_steps':>12} {'latency_s':>10} {'llm_calls':>10}")
    print("-" * 55)

    sweep_results = []
    for batch_size in range(1, max_batch_size + 1):
        coverages, total_steps_list, latencies, call_counts = [], [], [], []

        for query, results in query_results:
            chunks = _chunked(results, batch_size)
            t0 = time.perf_counter()
            extracted = []
            try:
                for chunk in chunks:
                    extracted.extend(_call_extraction_llm(sync_client, query, chunk))
            except Exception:
                continue
            latency = time.perf_counter() - t0

            coverages.append(sum(1 for r in extracted if r.get("relevant_steps")))
            total_steps_list.append(sum(len(r.get("relevant_steps", [])) for r in extracted))
            latencies.append(latency)
            call_counts.append(len(chunks))

        def avg(v): return round(sum(v) / len(v), 2)
        row = {
            "batch_size": batch_size,
            "avg_coverage": avg(coverages),
            "avg_total_steps": avg(total_steps_list),
            "avg_latency_s": avg(latencies),
            "avg_llm_calls": avg(call_counts),
        }
        sweep_results.append(row)
        print(f"{batch_size:>6} {row['avg_coverage']:>10.1f} {row['avg_total_steps']:>12.1f} {row['avg_latency_s']:>10.1f} {row['avg_llm_calls']:>10.1f}")

    sweep_path = Path(__file__).parent / "batch_size_sweep.json"
    sweep_path.write_text(json.dumps(sweep_results, indent=2))
    print(f"\nSweep results saved to {sweep_path}")

# ---------------------------------------------------------------------------
# Attention dilution: position sweep
# ---------------------------------------------------------------------------

def run_position_sweep(
    os_client: OpenSearch,
    sync_client: OpenAI,
    target_query: str,
    target_tag: str,
    filler_query: str,
    filler_tag: str,
    positions: list[int] | None = None,
) -> None:
    """
    Fix a target recipe and move it to different positions in a 10-recipe batch.
    All other slots are filled with filler recipes from a different query.
    Measures how many steps are extracted for the target recipe at each position.
    """
    if positions is None:
        positions = [1, 2, 3, 5, 7, 10]

    # Fetch target and filler recipes
    target_results, _ = search_recipes(os_client, target_query, "mixed", top_k=10, tag=target_tag)
    filler_results, _ = search_recipes(os_client, filler_query, "mixed", top_k=10, tag=filler_tag)

    # Pick the target recipe with the most search_text (richest content)
    target = max(target_results, key=lambda r: len(r.get("search_text", "")))
    fillers = [r for r in filler_results if r["recipe_uid"] != target["recipe_uid"]]

    # Baseline: target alone (batch size 1)
    baseline = _call_extraction_llm(sync_client, target_query, [target])
    baseline_steps = baseline[0].get("relevant_steps", []) if baseline else []

    print(f"\nAttention dilution — position sweep")
    print(f"Target recipe: {target['recipe_uid']} ({len(target.get('search_text',''))} chars)")
    print(f"Query: {target_query}")
    print(f"\n{'Position':>10} {'Steps extracted':>16} {'Step names'}")
    print("-" * 80)
    print(f"{'baseline(1)':>10} {len(baseline_steps):>16}  {baseline_steps}")

    position_results = [{"position": "baseline", "steps": baseline_steps}]

    for pos in positions:
        # Build batch: filler recipes before and after target
        before = fillers[:pos - 1]
        after  = fillers[pos - 1: pos - 1 + (10 - pos)]
        batch  = before + [target] + after

        try:
            extracted = _call_extraction_llm(sync_client, target_query, batch)
            uid_map = {r.get("recipe_uid"): r for r in extracted}
            steps = uid_map.get(target["recipe_uid"], {}).get("relevant_steps", [])
        except Exception as e:
            steps = [f"ERROR: {e}"]

        print(f"{pos:>10} {len(steps):>16}  {steps}")
        position_results.append({"position": pos, "steps": steps})

    out = Path(__file__).parent / "position_sweep_results.json"
    out.write_text(json.dumps({
        "target_recipe": target["recipe_uid"],
        "query": target_query,
        "results": position_results,
    }, indent=2, ensure_ascii=False))
    print(f"\nPosition sweep results saved to {out}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    os_client    = OpenSearch(os.getenv("OPENSEARCH_URL", "http://localhost:9200"))
    sync_client  = OpenAI(api_key=os.environ["API_KEY"], base_url=os.environ["BASE_URL"])
    async_client = AsyncOpenAI(api_key=os.environ["API_KEY"], base_url=os.environ["BASE_URL"])

    all_queries = [
        (q, cat)
        for cat, qs in QUERIES.items()
        for q in qs
    ]

    results = []
    total = len(all_queries)

    print(f"{'#':<4} {'Query':<52} {'B-cov':>6} {'I-cov':>6} {'N1-cov':>7} {'B-stp':>6} {'I-stp':>6} {'N1-stp':>7} {'B-lat':>6} {'I-lat':>6} {'N1-lat':>7}")
    print("-" * 140)

    for i, (query, cat) in enumerate(all_queries, 1):
        print(f"{i:<4} {query[:51]:<52}", end="", flush=True)
        try:
            r = run_query(query, cat, os_client, sync_client, async_client)
            b, ind, n1 = r["batch"], r["individual"], r["batch_n1"]
            print(
                f" {b['coverage']:>6} {ind['coverage']:>6} {n1['coverage']:>7}"
                f" {b['total_steps']:>6} {ind['total_steps']:>6} {n1['total_steps']:>7}"
                f" {b['latency_s']:>6.1f} {ind['latency_s']:>6.1f} {n1['latency_s']:>7.1f}"
            )
            results.append({"query_category": cat, **r})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"query_category": cat, "query": query, "error": str(e)})

    # Summary
    ok = [r for r in results if "error" not in r]
    def avg(vals): return round(sum(vals) / len(vals), 2) if vals else 0

    print("\n" + "=" * 140)
    print(f"{'SUMMARY':<52} {'B-cov':>6} {'I-cov':>6} {'N1-cov':>7} {'B-stp':>6} {'I-stp':>6} {'N1-stp':>7} {'B-lat':>6} {'I-lat':>6} {'N1-lat':>7}")
    print(
        f"{'Average across ' + str(len(ok)) + ' queries':<52}"
        f" {avg([r['batch']['coverage'] for r in ok]):>6.1f}"
        f" {avg([r['individual']['coverage'] for r in ok]):>6.1f}"
        f" {avg([r['batch_n1']['coverage'] for r in ok]):>7.1f}"
        f" {avg([r['batch']['total_steps'] for r in ok]):>6.1f}"
        f" {avg([r['individual']['total_steps'] for r in ok]):>6.1f}"
        f" {avg([r['batch_n1']['total_steps'] for r in ok]):>7.1f}"
        f" {avg([r['batch']['latency_s'] for r in ok]):>6.1f}"
        f" {avg([r['individual']['latency_s'] for r in ok]):>6.1f}"
        f" {avg([r['batch_n1']['latency_s'] for r in ok]):>7.1f}"
    )

    output_path = Path(__file__).parent / "compare_extraction_results.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nFull results saved to {output_path}")

    # --- Batch size sweep (valid-tag queries only, where results are non-empty) ---
    sweep_queries = [
        (q, q.split("with tag ")[1].split()[0].rstrip("?.,") if "with tag " in q
         else q.split("tagged ")[1].split()[0].rstrip("?.,"))
        for q in QUERIES["VALID_TAG"]
    ]
    run_batch_size_sweep(os_client, sync_client, sweep_queries)

    # --- Two-pass experiment ---
    run_two_pass_experiment(os_client, async_client, sync_client, sweep_queries)

    # --- Position sweep (attention dilution test) ---
    run_position_sweep(
        os_client, sync_client,
        target_query="Find recipes tagged google_sheets that process employee data",
        target_tag="google_sheets",
        filler_query="Find recipes with tag salesforce that sync leads",
        filler_tag="salesforce",
    )


if __name__ == "__main__":
    main()
