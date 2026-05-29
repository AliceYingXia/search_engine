"""
generate_queries.py

Generate step-level search queries for the N longest recipes.

Run:
    python generate_queries.py

Output:
    pipeline/02_generate_descriptions/recipe_queries.parquet
    columns: recipe_uid, field_queries, action_queries, url_queries
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
import pandas as pd

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY         = os.environ["API_KEY"]
BASE_URL        = os.environ["BASE_URL"]
MODEL           = "azure/gpt-5.2"

MAX_CONCURRENT  = 20
MAX_RETRIES     = 5
MAX_TOKENS      = 512
N_RECIPES       = 20
INPUT_CHARS     = 8000

INPUT_PARQUET   = Path(__file__).parent.parent / "01_process_data" / "cleaned" / "recipe_summaries_full.parquet"
OUTPUT_PARQUET  = Path(__file__).parent / "recipe_queries.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are given the structured outline of a Workato recipe automation.

Generate questions a developer or ops person would ask to locate specific steps in this recipe.
All questions MUST start with "What steps in recipes".

Generate exactly three kinds (2 questions each, 6 total):

1. FIELD queries: ask about steps that use a specific field name that actually appears in the recipe.
   - Pick real field names from the "input fields" or "datapill fields" lines in the recipe
   - Mention the field name directly in the question
   - Example: "What steps in recipes use the OwnerId field?"

2. ACTION queries: ask about steps that perform a specific business operation.
   - Use natural business language only — do NOT mention connector names, action names, or technical identifiers
   - Must mention the specific system (e.g. Salesforce, Jira, Marketo, Slack) and the business object (e.g. lead, account, issue, message)
   - Must be specific enough to point to one or a few steps — avoid generic phrases like "start a workflow", "process a record"
   - Example: "What steps in recipes reassign Salesforce lead ownership to a new user?"

3. URL queries: ask about steps that call a specific URL that actually appears in the recipe.
   - Use the exact URL or endpoint path from the recipe's "url:" lines
   - Only generate these if the recipe contains url steps; otherwise return an empty list
   - Example: "What steps in recipes call the JSSResource/computers/match endpoint?"

Return JSON: {"field_queries": ["...", "..."], "action_queries": ["...", "..."], "url_queries": ["...", "..."]}
"""

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def generate_one(
    semaphore: asyncio.Semaphore,
    recipe_uid: str,
    search_text: str,
) -> dict | None:
    attempt = 0
    wait = 5
    async with semaphore:
        while attempt < MAX_RETRIES:
            try:
                async with AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL) as client:
                    resp = await client.chat.completions.create(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user",   "content": search_text[:INPUT_CHARS]},
                        ],
                        response_format={"type": "json_object"},
                        max_completion_tokens=MAX_TOKENS,
                    )
                result = json.loads(resp.choices[0].message.content)
                return {
                    "recipe_uid":     recipe_uid,
                    "field_queries":  result.get("field_queries", []),
                    "action_queries": result.get("action_queries", []),
                    "url_queries":    result.get("url_queries", []),
                }
            except Exception as e:
                attempt += 1
                log.warning(f"recipe_uid={recipe_uid} attempt={attempt} error={e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, 60)
    log.error(f"recipe_uid={recipe_uid} failed after {MAX_RETRIES} attempts")
    return None

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

URL_QUERY_TARGET = 40

async def main():
    log.info(f"Loading {INPUT_PARQUET}")
    df = pd.read_parquet(INPUT_PARQUET)
    df["search_text_len"] = df["search_text"].str.len()

    # Load existing results
    existing = pd.read_parquet(OUTPUT_PARQUET) if OUTPUT_PARQUET.exists() else pd.DataFrame()
    done_uids = set(existing["recipe_uid"]) if not existing.empty else set()
    current_url_count = existing["url_queries"].apply(len).sum() if not existing.empty else 0
    log.info(f"Existing: {len(done_uids)} recipes done, {current_url_count} URL queries so far")

    if current_url_count >= URL_QUERY_TARGET:
        log.info(f"Already have {current_url_count} URL queries — nothing to do")
        return

    # Prioritise recipes with URL steps, sorted by length descending
    has_url = df["search_text"].str.contains("\n    url:", na=False)
    candidates = (
        df[has_url & ~df["recipe_uid"].isin(done_uids)]
        .sort_values("search_text_len", ascending=False)
        [["recipe_uid", "search_text"]]
        .reset_index(drop=True)
    )
    log.info(f"Candidates with url steps: {len(candidates)}")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    records = list(existing.to_dict("records")) if not existing.empty else []
    url_count = current_url_count
    batch_size = MAX_CONCURRENT

    for start in range(0, len(candidates), batch_size):
        if url_count >= URL_QUERY_TARGET:
            break
        batch = candidates.iloc[start:start + batch_size]
        tasks = [generate_one(semaphore, row["recipe_uid"], row["search_text"]) for _, row in batch.iterrows()]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                records.append(r)
                url_count += len(r["url_queries"])
        log.info(f"Processed {min(start + batch_size, len(candidates))}/{len(candidates)} — URL queries so far: {url_count}")

    out_df = pd.DataFrame(records)
    out_df.to_parquet(OUTPUT_PARQUET, index=False)
    log.info(f"Done. {len(out_df)} total recipes, {url_count} URL queries saved to {OUTPUT_PARQUET}")

    url_rows = out_df[out_df["url_queries"].apply(len) > 0]
    for _, row in url_rows.iterrows():
        print(f"\nrecipe_uid: {row['recipe_uid']}")
        print("  URL queries:")
        for q in row["url_queries"]:
            print(f"    - {q}")


if __name__ == "__main__":
    asyncio.run(main())
