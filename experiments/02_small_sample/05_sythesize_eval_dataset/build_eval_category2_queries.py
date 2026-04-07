"""
build_eval_category2_queries.py
================================

Phase 1 of the Category 2 evaluation dataset pipeline.
Run this AFTER build_recipe_df.py and build_step_df.py have been run.

What this script does
---------------------
1. Loads every *_tracking.json and *_semantic.json from cleaned/ to get
   author_index and summary_index (via eval_utils.load_tracking_data).
2. Loads step_df.parquet (produced by build_step_df.py) to get per-step intents.
3. Selects ALL diverse seed recipes per author (same seeds as Category 1).
4. For each seed recipe, calls the LiteLLM proxy (azure/gpt-5.2) to generate one
   Category 2 (action-oriented) natural-language search query.
   Category 2 queries are specific — they name the systems involved and the
   trigger/outcome, e.g.:
     "Is there an automation that sends a Slack notification when an invoice is overdue?"
     "Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"
5. Saves all queries to eval_category2_queries.json (intermediate file).
6. Prints a numbered summary of all queries for human review.

After reviewing the printed queries, run build_eval_category2_relevance.py
to assess relevance and produce the final eval_category2.csv.

Inputs
------
  02_cleaning/cleaned/*_tracking.json
  02_cleaning/cleaned/*_semantic.json
  05_sythesize_eval_dataset/step_df.parquet
  .env  (DIRECT_OPENAI_API_KEY)

Output
------
  05_sythesize_eval_dataset/eval_category2_queries.json

    List of objects:
      query_id              : str       — "{author_id}_c2q{n}" where n is 1-indexed per author
      author_id             : int
      source_flow_id        : int       — recipe used to generate the query
      source_version_no     : int
      source_connectors     : list[str]
      source_step_as_list   : list[str] — "as" handles of all steps in the source recipe
      query                 : str       — generated Category 2 NL query

Usage
-----
    python 05_sythesize_eval_dataset/build_eval_category2_queries.py
"""

import json
from pathlib import Path

import pandas as pd
from openai import OpenAI

from eval_utils import (
    get_infra_connectors,
    load_tracking_data,
    make_openai_client,
    select_recipe_seeds,
)

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
STEP_DF_PATH = BASE_DIR / "step_df.parquet"
OUTPUT_PATH  = BASE_DIR / "eval_category2_queries.json"

MODEL = "azure/gpt-5.2"

# ---------------------------------------------------------------------------
# Generate Category 2 query via LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are helping build an evaluation dataset for a semantic search system \
over Workato automation recipes.

Your task: given a recipe summary and the step intents of the recipe, write \
exactly ONE Category 2 (action-oriented) search query that a business user \
might type to find this specific automation.

Category 2 queries describe a specific action or outcome — they name the \
concrete systems, the trigger, and the result. They are distinct from \
Category 1 queries, which describe broad business processes.

Good examples:
  "Is there an automation that sends a Slack notification when an invoice is overdue?"
  "Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"
  "Find the automation that pages the on-call engineer when a critical recipe errors."
  "Is there a recipe that syncs customer data between Salesforce and HubSpot?"
  "Which recipe creates a Workday position when a headcount request is approved?"
  "Is there an automation that converts currency values before writing to NetSuite?"
  "Find the recipe that maps Salesforce opportunity stages to NetSuite order statuses."
  "Is there a recipe that sends a daily summary of new leads to the sales manager?"
  "Which recipe updates the CRM when a support ticket is resolved in Zendesk?"
  "Is there a recipe that creates an onboarding checklist in Asana when a new hire starts?"
  "Which automation assigns incoming support tickets to the correct team based on category?"
  "Find the recipe that escalates overdue approvals to a manager after 48 hours."

Rules:
  - One short sentence only — as a user would type in a search box.
  - Be specific: name the systems, the trigger, and the outcome when evident.
  - Do not mention Workato.
  - Ground the query only in what the recipe summary and step intents show.
  - Return only the query string — no quotes, no explanation."""


def generate_query(client: OpenAI, recipe_summary: str, step_intents: list[str]) -> str:
    """Call the LLM and return a single Category 2 query string."""
    steps_block = "\n".join(f"- {s}" for s in step_intents)
    user_msg = (
        f"Recipe summary:\n{recipe_summary}\n\n"
        f"Step intents:\n{steps_block}"
    )
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=120,
    )
    return resp.choices[0].message.content.strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not STEP_DF_PATH.exists():
        raise FileNotFoundError(
            f"{STEP_DF_PATH} not found. Run build_step_df.py first."
        )

    client = make_openai_client()

    print("Loading tracking data ...")
    author_index, summary_index = load_tracking_data()
    print(f"Authors loaded: {len(author_index)}\n")

    print(f"Loading step_df from {STEP_DF_PATH} ...")
    step_df = pd.read_parquet(STEP_DF_PATH)
    print(f"  {len(step_df)} step rows loaded\n")

    # Build (flow_id, version_no) → list of (as, step_intent) tuples
    step_data_index: dict[tuple, list[tuple[str, str]]] = {}
    for (fid, vno), grp in step_df.groupby(["flow_id", "version_no"]):
        rows = grp[["as", "step_intent"]].dropna(subset=["step_intent"])
        if not rows.empty:
            step_data_index[(int(fid), int(vno))] = list(zip(rows["as"], rows["step_intent"]))

    results = []

    for author_id, all_recipes in sorted(author_index.items()):
        seeds = select_recipe_seeds(all_recipes)
        infra = get_infra_connectors(all_recipes)
        print(f"Author {author_id}  ({len(all_recipes)} recipes → {len(seeds)} seeds"
              f"  infra excluded: {sorted(infra) if infra else 'none'})")

        for i, seed in enumerate(seeds, 1):
            key     = (seed["flow_id"], seed["version_no"])
            summary = summary_index.get(key, "")
            if not summary:
                print(f"  [{i}/{len(seeds)}] flow_id={seed['flow_id']} — no summary, skipping")
                continue

            step_data = step_data_index.get(key, [])
            if not step_data:
                print(f"  [{i}/{len(seeds)}] flow_id={seed['flow_id']} — no step intents, skipping")
                continue

            step_as_list  = [s[0] for s in step_data]
            step_intents  = [s[1] for s in step_data]

            print(f"  [{i}/{len(seeds)}] flow_id={seed['flow_id']} "
                  f"({len(set(seed['connectors']))} connectors, "
                  f"{len(step_intents)} steps) ...", end=" ", flush=True)

            query = generate_query(client, summary, step_intents)
            print(f'"{query}"')

            results.append({
                "query_id":           f"{author_id}_c2q{i}",
                "author_id":          author_id,
                "source_flow_id":     seed["flow_id"],
                "source_version_no":  seed["version_no"],
                "source_connectors":  seed["connectors"],
                "source_step_as_list": step_as_list,
                "query":              query,
            })

        print()

    OUTPUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    print("=" * 70)
    print(f"ALL {len(results)} GENERATED QUERIES — please review before running Phase 2")
    print("=" * 70)
    current_author = None
    for r in results:
        if r["author_id"] != current_author:
            current_author = r["author_id"]
            print(f"\nAuthor {current_author}")
            print("-" * 40)
        print(f"  {r['query_id']:20s}  {r['query']}")

    print(f"\nSaved → {OUTPUT_PATH}")
    print("\nNext step: review the queries above, then run build_eval_category2_relevance.py")


if __name__ == "__main__":
    main()
