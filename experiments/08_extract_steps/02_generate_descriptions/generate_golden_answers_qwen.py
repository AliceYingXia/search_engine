"""
generate_golden_answers_qwen.py

Qwen3.5-35B-A3B (Baseten) golden answer generation.
Run in parallel with generate_golden_answers.py (GPT) and generate_golden_answers_claude.py.

Output:
    pipeline/02_generate_descriptions/golden_answers_qwen.parquet
    columns: query, query_type, recipe_uid, step
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASETEN_API_KEY = os.environ["BASETEN_API_KEY"]
BASETEN_BASE_URL = "https://model-wx4l575q.api.baseten.co/environments/production/sync/v1"
QWEN_MODEL       = "Qwen/Qwen3.5-35B-A3B"

MAX_CONCURRENT = 40

QUERIES_JSON   = Path(__file__).parent / "filtered_queries.json"
INPUT_PARQUET  = Path(__file__).parent.parent / "01_process_data" / "cleaned" / "recipe_summaries_full.parquet"
OUTPUT_PARQUET = Path(__file__).parent / "golden_answers_qwen.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_qwen_client = AsyncOpenAI(api_key=BASETEN_API_KEY, base_url=BASETEN_BASE_URL)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are given a search query and the structured outline of a Workato recipe automation.

Your task: identify which specific steps in this recipe are an EXACT match for the query.

Queries fall into three categories — apply strict matching rules for each:

1. FIELD queries ("What steps use the <field_name> field?")
   - Match steps where the exact field name appears in the step's "input fields" or "datapill fields" sub-lines.
   - Return the PARENT step line (the "- action:" or "- trigger:" line), not the sub-line.
   - The field name must match exactly (case-insensitive). Do NOT match steps just because they use a related or similar field.

2. ACTION queries ("What steps <do something> in <connector>?")
   - Match steps where the action name in the step line directly corresponds to what the query describes.
   - The connector name and action name must match exactly (e.g., "salesforce / create_record").
   - Do NOT match generic wrappers like "workato_recipe_function / call_recipe" or "http / get" unless the query explicitly asks for those.

3. URL queries ("What steps call the <endpoint> endpoint?")
   - Match steps where the exact endpoint path appears in the step's "url" sub-line.
   - The URL path must match exactly or as a clear suffix (e.g., "api/v2/sequenceStates" matches url: api/v2/sequenceStates).
   - Return the PARENT step line (the "- action:" line), not the url sub-line.
   - Do NOT match generic "http / get" or "http / post" steps unless their "url" sub-line contains the exact endpoint.

General rules:
- Return ONLY the step lines that directly match — lines starting with "- trigger:", "- action:", "- if", "- foreach", etc.
- Copy the step line exactly as it appears in the recipe (including indentation dashes).
- If no steps match exactly, return an empty list. Prefer false negatives over false positives.
- Do not include sub-lines (input fields, datapill fields, url, calls recipe lines) in the output.

Return JSON only, no explanation: {"matched_steps": ["- action: salesforce / create_record", ...]}
"""

def make_user_prompt(query: str, search_text: str) -> str:
    return f"/no_think\nQuery: {query}\n\nRecipe:\n{search_text}"

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def call_qwen(semaphore: asyncio.Semaphore, query: str, search_text: str) -> list[str]:
    async with semaphore:
        attempt = 0
        while attempt < 5:
            try:
                resp = await _qwen_client.chat.completions.create(
                    model=QWEN_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": make_user_prompt(query, search_text)},
                    ],
                    max_tokens=512,
                    temperature=0,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                raw = resp.choices[0].message.content or ""
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
                json_str = m.group(1) if m else raw
                result = json.loads(json_str)
                return result.get("matched_steps", [])
            except Exception as e:
                attempt += 1
                log.warning(f"Qwen error (attempt {attempt}): {e}")
                if attempt < 5:
                    await asyncio.sleep(min(2 ** attempt, 30))
        return []

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    log.info("Loading data...")
    with open(QUERIES_JSON) as f:
        queries_data = json.load(f)

    df = pd.read_parquet(INPUT_PARQUET)
    df["search_text_len"] = df["search_text"].str.len()
    recipes = df[df["search_text_len"] > 10000].reset_index(drop=True)
    log.info(f"Recipes (>10k chars): {len(recipes)}")

    all_queries = (
        [(q, "field")  for q in queries_data["field_queries"]] +
        [(q, "action") for q in queries_data["action_queries"]] +
        [(q, "url")    for q in queries_data["url_queries"]]
    )
    log.info(f"Total queries: {len(all_queries)}")
    log.info(f"Total (query, recipe) pairs: {len(all_queries) * len(recipes)}")

    qwen_sem = asyncio.Semaphore(MAX_CONCURRENT)
    all_records: list[dict] = []

    for i, (query, query_type) in enumerate(all_queries):
        log.info(f"[{i+1}/{len(all_queries)}] '{query[:70]}'")

        tasks = [
            call_qwen(qwen_sem, query, row["search_text"])
            for _, row in recipes.iterrows()
        ]
        results = await asyncio.gather(*tasks)

        query_hits = 0
        for (_, row), steps in zip(recipes.iterrows(), results):
            for step in steps:
                all_records.append({
                    "query":      query,
                    "query_type": query_type,
                    "recipe_uid": row["recipe_uid"],
                    "step":       step.strip(),
                })
                query_hits += 1

        log.info(f"  → {query_hits} matched steps across {len(recipes)} recipes")

        if (i + 1) % 10 == 0:
            pd.DataFrame(all_records).to_parquet(OUTPUT_PARQUET, index=False)
            log.info(f"Checkpoint: {len(all_records)} total records saved")

    out_df = pd.DataFrame(all_records)
    out_df.to_parquet(OUTPUT_PARQUET, index=False)
    log.info(f"Done. {len(out_df)} golden answer records saved to {OUTPUT_PARQUET}")

    print(f"\nTotal answers: {len(out_df)}")
    if not out_df.empty:
        print(f"\nQueries with answers: {out_df['query'].nunique()} / {len(all_queries)}")


if __name__ == "__main__":
    asyncio.run(main())
