"""
build_eval_category1_queries.py
================================

Phase 1 of the Category 1 evaluation dataset pipeline.

What this script does
---------------------
1. Loads every *_tracking.json from cleaned/ to build:
     author_id → list of {flow_id, version_no, connectors, step_count}
2. Loads every *_semantic.json from cleaned/ to build:
     (flow_id, version_no) → recipe_summary
3. Selects ALL diverse seed recipes per author (no cap) — see eval_utils.select_recipe_seeds().
4. For each seed, calls the LiteLLM proxy (azure/gpt-5.2) to generate one
     Category 1 (process-oriented) natural-language search query.
     Category 1 queries describe a broad business workflow, e.g.:
       "Which recipes handle our employee onboarding?"
       "Find all automations involved in the Quote-to-Cash process."
5. Saves all queries to eval_category1_queries.json (intermediate file).
6. Prints a numbered summary of all queries for human review.

After reviewing the printed queries, run build_eval_category1_relevance.py
to assess relevance and produce the final eval_category1.csv.

Inputs
------
  02_cleaning/cleaned/*_tracking.json
  02_cleaning/cleaned/*_semantic.json
  .env  (DIRECT_OPENAI_API_KEY)

Output
------
  05_sythesize_eval_dataset/eval_category1_queries.json

    List of objects:
      query_id          : str  — "{author_id}_q{n}" where n is 1-indexed per author
      author_id         : int
      source_flow_id    : int  — recipe used to generate the query
      source_version_no : int
      source_connectors : list[str]
      query             : str  — generated Category 1 NL query

Usage
-----
    python 05_sythesize_eval_dataset/build_eval_category1_queries.py
"""

import json
from pathlib import Path

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
BASE_DIR    = Path(__file__).parent
OUTPUT_PATH = BASE_DIR / "eval_category1_queries.json"

MODEL = "azure/gpt-5.2"

# ---------------------------------------------------------------------------
# Generate Category 1 query via LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are helping build an evaluation dataset for a semantic search system \
over Workato automation recipes.

Your task: given a recipe_summary, write exactly ONE Category 1 \
(process-oriented) search query that a non-technical business user might \
type to discover this recipe.

Category 1 queries describe a high-level business workflow or process — \
NOT a specific tool action or connector name.

Good examples:
  "Which recipes handle our employee onboarding?"
  "Find all automations involved in the Quote-to-Cash process."
  "What recipes run when a new hire is created in our HR system?"
  "Which automations are part of our monthly financial close?"
  "Which recipes are involved in customer master data synchronization?"
  "Find recipes that are part of the lead management process."

Rules:
  - One short sentence only — as a user would type in a search box.
  - Use plain business language (no connector names, no technical jargon).
  - Do not mention Workato.
  - Do not combine multiple requirements or clauses into one query.
  - Ground the query only in what recipe_summary shows.
  - Return only the query string — no quotes, no explanation."""


def generate_query(client: OpenAI, recipe_summary: str) -> str:
    """Call the LLM and return a single Category 1 query string."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"recipe_summary:\n{recipe_summary}"},
        ],
        temperature=0.4,
        max_tokens=120,
    )
    return resp.choices[0].message.content.strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = make_openai_client()

    print("Loading tracking data ...")
    author_index, summary_index = load_tracking_data()
    print(f"Authors loaded: {len(author_index)}\n")

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

            print(f"  [{i}/{len(seeds)}] flow_id={seed['flow_id']} "
                  f"({len(set(seed['connectors']))} connectors) ...", end=" ", flush=True)

            query = generate_query(client, summary)
            print(f'"{query}"')

            results.append({
                "query_id":           f"{author_id}_q{i}",
                "author_id":          author_id,
                "source_flow_id":     seed["flow_id"],
                "source_version_no":  seed["version_no"],
                "source_connectors":  seed["connectors"],
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
    print("\nNext step: review the queries above, then run build_eval_category1_relevance.py")


if __name__ == "__main__":
    main()
