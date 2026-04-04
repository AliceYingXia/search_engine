"""
build_eval_category2_relevance.py
===================================

Phase 2 of the Category 2 evaluation dataset pipeline.
Run this AFTER reviewing the queries printed by build_eval_category2_queries.py.

What this script does
---------------------
1. Loads eval_category2_queries.json (Phase 1 output).
2. Loads every *_tracking.json and *_semantic.json from cleaned/ to rebuild
   the full seed recipe pool across all authors.
3. Builds a single global candidate pool — all seed recipes from all authors
   (identified by source_flow_id across the entire queries JSON).
   Relevance is assessed against this global pool, not restricted to the
   query's own author.
4. For each query, sends one call per chunk of up to CHUNK_SIZE seed recipes
   to BOTH models independently. Labels from all chunks are merged per model
   before writing. Each chunk call returns a JSON mapping flow_id → label.
5. Keeps rows where EITHER model returns "Strongly Related" or "Weakly Related"
   (drops rows where both models return "Not Related").
6. Writes rows to eval_category2.csv incrementally and saves a checkpoint
   after each query so the run can be safely interrupted and resumed.

Models used
-----------
  MODEL_GPT52  : azure/gpt-5.2
  MODEL_CLAUDE : bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0

Relevance label definitions
---------------------------
  Strongly Related : The recipe is highly likely to be the exact automation
                     described by the query — the trigger, action, and
                     systems match closely.
  Weakly Related   : The recipe performs a similar or adjacent action but
                     differs in trigger, system, or outcome.
  Not Related      : No meaningful connection — excluded from output.

Inputs
------
  05_sythesize_eval_dataset/eval_category2_queries.json   (Phase 1 output)
  02_cleaning/cleaned/*_tracking.json
  02_cleaning/cleaned/*_semantic.json
  .env  (API_KEY, BASE_URL)

Output
------
  05_sythesize_eval_dataset/eval_category2.csv
  05_sythesize_eval_dataset/eval_category2_checkpoint.json   (resume state — delete to restart)

    Columns:
      author_id            : int   — author who generated the query
      query_id             : str   — "{author_id}_c2q{n}" where n is 1-indexed per author
      query                : str   — the Category 2 NL query
      source_flow_id       : int   — recipe that generated this query
      flow_id              : int   — candidate recipe being judged
      version_no           : int   — version of the candidate recipe
      candidate_author_id  : int   — author who owns the candidate recipe
      connectors           : str   — comma-separated list of connectors used
      relevance_gpt52      : str   — label from azure/gpt-5.2
      relevance_claude     : str   — label from bedrock Claude Sonnet 4

Usage
-----
    python 05_sythesize_eval_dataset/build_eval_category2_relevance.py
"""

import csv
import json
import re
import time
from pathlib import Path

from openai import OpenAI

from eval_utils import load_tracking_data, make_openai_client

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
QUERIES_PATH = BASE_DIR / "eval_category2_queries.json"
OUTPUT_PATH  = BASE_DIR / "eval_category2.csv"
CHECKPOINT   = BASE_DIR / "eval_category2_checkpoint.json"

MODEL_GPT52  = "azure/gpt-5.2"
MODEL_CLAUDE = "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"

CHUNK_SIZE = 20   # max seed recipes per LLM call (guards against "lost in the middle")

POSITIVE_LABELS = {"Strongly Related", "Weakly Related"}


# ---------------------------------------------------------------------------
# Build the recipe block passed to the LLM
# ---------------------------------------------------------------------------

def build_recipes_block(recipes: list[dict], summary_index: dict) -> str:
    """
    Render a list of recipes into a prompt block.
    Each recipe is labelled with its flow_id for unambiguous JSON response keys.
    """
    parts = []
    for r in recipes:
        summary = summary_index.get((r["flow_id"], r["version_no"]), "(no summary available)")
        parts.append(f"[flow_id={r['flow_id']}]\n{summary}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM relevance assessment
# ---------------------------------------------------------------------------

SYSTEM_RELEVANCE = """\
You are helping build a ground-truth evaluation dataset for a semantic \
search system over Workato automation recipes.

A business user typed a specific, action-oriented search query. You are \
given a set of Workato recipes (each described by its recipe_summary).

For each recipe, decide whether it is relevant to the query:

  Strongly Related : The recipe is highly likely to be the exact automation
                     described by the query — the trigger, action, and
                     systems match closely.
  Weakly Related   : The recipe performs a similar or adjacent action but
                     differs in trigger, system, or outcome.
  Not Related      : No meaningful connection to the query.

Return a single JSON object mapping each flow_id (as a string key) to one
of exactly these three labels. Include every flow_id in the response.

Return ONLY valid JSON — no markdown fences, no explanation."""


def assess_relevance(
    client: OpenAI, query: str, recipes_block: str, model: str
) -> dict[str, str]:
    """
    Send one LLM call for a single query against one chunk of seed recipes.
    Returns dict mapping flow_id (str) → relevance label.
    Returns empty dict if the response cannot be parsed after two attempts.
    """
    user_msg = f'Search query: "{query}"\n\nRecipes:\n{recipes_block}'

    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_RELEVANCE},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 0:
                print(f"    [{model}] JSON parse error — retrying ...")
                time.sleep(1)
            else:
                print(f"    [{model}] JSON parse error on retry — skipping this batch")
                return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "source_author_id", "query_id", "query", "source_flow_id",
    "candidate_flow_id", "candidate_version_no", "candidate_author_id", "candidate_connectors",
    "relevance_gpt52", "relevance_claude",
]


def main():
    if not QUERIES_PATH.exists():
        raise FileNotFoundError(
            f"{QUERIES_PATH} not found. Run build_eval_category2_queries.py first."
        )

    done: set[str] = set()
    if CHECKPOINT.exists():
        done = set(json.loads(CHECKPOINT.read_text()))
        print(f"Resuming — {len(done)} queries already processed.\n")

    client = make_openai_client()

    print("Loading queries from Phase 1 ...")
    queries = json.loads(QUERIES_PATH.read_text())
    print(f"  {len(queries)} queries loaded\n")

    print("Loading cleaned recipe data ...")
    author_index, summary_index = load_tracking_data()
    print(f"  {sum(len(v) for v in author_index.values())} recipes across "
          f"{len(author_index)} authors\n")

    # Build global seed pool: all seed flow_ids across all authors
    all_seed_flow_ids: set[int] = {q["source_flow_id"] for q in queries}

    global_seeds: list[dict] = []
    for author_id, recipes in author_index.items():
        for r in recipes:
            if r["flow_id"] in all_seed_flow_ids:
                global_seeds.append({**r, "author_id": author_id})

    print(f"Global seed pool: {len(global_seeds)} recipes across all authors\n")

    write_header = not OUTPUT_PATH.exists() or len(done) == 0
    csv_file = OUTPUT_PATH.open("a" if not write_header else "w", newline="", encoding="utf-8")
    writer   = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
    if write_header:
        writer.writeheader()

    try:
        for idx, q in enumerate(queries, 1):
            query_id       = q["query_id"]
            author_id      = q["author_id"]
            query          = q["query"]
            source_flow_id = q["source_flow_id"]

            if query_id in done:
                continue

            chunks = [global_seeds[i:i + CHUNK_SIZE]
                      for i in range(0, len(global_seeds), CHUNK_SIZE)]

            print(f"[{idx:03d}/{len(queries)}] {query_id}  author={author_id}  "
                  f"({len(global_seeds)} candidates, {len(chunks)} chunk(s))")
            print(f"         Query: \"{query}\"")

            labels_gpt52:  dict[str, str] = {}
            labels_claude: dict[str, str] = {}

            for chunk_idx, chunk in enumerate(chunks, 1):
                chunk_block = build_recipes_block(chunk, summary_index)
                print(f"         Chunk {chunk_idx}/{len(chunks)} ({len(chunk)} seeds)")

                for model, labels in (
                    (MODEL_GPT52,  labels_gpt52),
                    (MODEL_CLAUDE, labels_claude),
                ):
                    print(f"           {model} ...", end=" ", flush=True)
                    chunk_labels = assess_relevance(client, query, chunk_block, model)
                    if chunk_labels:
                        labels.update(chunk_labels)
                        print(f"done ({len(chunk_labels)} labels)")
                    else:
                        print("skipped (parse error)")

            if not labels_gpt52 and not labels_claude:
                print()
                continue

            strong_gpt52  = sum(1 for v in labels_gpt52.values()  if v == "Strongly Related")
            weak_gpt52    = sum(1 for v in labels_gpt52.values()  if v == "Weakly Related")
            strong_claude = sum(1 for v in labels_claude.values() if v == "Strongly Related")
            weak_claude   = sum(1 for v in labels_claude.values() if v == "Weakly Related")
            print(f"         GPT-5.2 : Strong={strong_gpt52}  Weak={weak_gpt52}")
            print(f"         Claude  : Strong={strong_claude}  Weak={weak_claude}\n")

            for r in global_seeds:
                fid = str(r["flow_id"])
                label_gpt52  = labels_gpt52.get(fid,  "Not Related")
                label_claude = labels_claude.get(fid, "Not Related")
                if label_gpt52 in POSITIVE_LABELS or label_claude in POSITIVE_LABELS:
                    writer.writerow({
                        "source_author_id":    author_id,
                        "query_id":            query_id,
                        "query":               query,
                        "source_flow_id":      source_flow_id,
                        "candidate_flow_id":   r["flow_id"],
                        "candidate_version_no": r["version_no"],
                        "candidate_author_id": r["author_id"],
                        "candidate_connectors": ", ".join(r["connectors"]),
                        "relevance_gpt52":     label_gpt52,
                        "relevance_claude":    label_claude,
                    })
            csv_file.flush()

            done.add(query_id)
            CHECKPOINT.write_text(json.dumps(sorted(done)))

    finally:
        csv_file.close()

    print("=" * 60)
    print("Done.")
    try:
        import pandas as pd
        results = pd.read_csv(OUTPUT_PATH)
        for col, model_name in [("relevance_gpt52", "GPT-5.2"), ("relevance_claude", "Claude")]:
            strong = (results[col] == "Strongly Related").sum()
            weak   = (results[col] == "Weakly Related").sum()
            print(f"  {model_name:<10} Strong={strong}  Weak={weak}")
        print(f"  Total rows (either positive) : {len(results)}")
    except Exception as e:
        print(f"  (Could not read final stats: {e})")
    print(f"  Output : {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
