"""
generate_descriptions.py

Generate LLM description + usage for every recipe in recipe_summaries_full.parquet
and merge results with all existing fields into one output parquet.

Run:
    python generate_descriptions.py

Output:
    pipeline/02_generate_descriptions/recipes_with_descriptions.parquet
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

API_KEY  = os.environ["API_KEY"]
BASE_URL = os.environ["BASE_URL"]
MODEL    = "azure/gpt-5.2"

MAX_CONCURRENT      = 20
MAX_RETRIES         = 5
MAX_TOKENS          = 1024
CHECKPOINT_EVERY    = 200

INPUT_PARQUET       = Path(__file__).parent.parent / "01_process_data" / "cleaned" / "recipe_summaries_full.parquet"
CHECKPOINT_PARQUET  = Path(__file__).parent / "descriptions_checkpoint.parquet"
OUTPUT_PARQUET      = Path(__file__).parent / "recipes_with_descriptions.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts & schema
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Your task is to generate a description and usage for a Workato recipe automation.
You will be given a structured outline of the recipe showing its trigger, actions, and nesting.

Each recipe must have:

*description*: A high-level description including:
- the business category or domain the recipe belongs to
- the main data sources and target systems involved
- whether the recipe is scheduled, event-driven, or function-triggered
- a brief overview of what it does end-to-end

*usage*: Typical usage scenarios including:
- when and why a team would use this recipe
- what operational or business problem it solves
- what kind of outcome it enables (e.g. reduced manual work, systems staying aligned)
- which roles or teams would benefit (e.g. finance, ops, data, IT)

Hard constraints:
- Do NOT mention internal numeric flow IDs
- Do NOT list raw field names
- Keep description to 2-4 sentences, usage to 2-4 sentences
- Use natural business language
"""

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "recipe_desc",
        "schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "usage":       {"type": "string"},
            },
            "required": ["description", "usage"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}

# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    return {row["recipe_uid"]: row.to_dict() for _, row in df.iterrows()}


def save_checkpoint(results: list[dict], path: Path) -> None:
    pd.DataFrame(results).to_parquet(path, index=False)

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def generate_one(
    semaphore: asyncio.Semaphore,
    recipe_uid: str,
    flow_id: int,
    version_no: int,
    search_text: str,
) -> dict | None:
    user_prompt = search_text
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
                            {"role": "user",   "content": user_prompt},
                        ],
                        response_format=RESPONSE_SCHEMA,
                        max_completion_tokens=MAX_TOKENS,
                    )
                result = json.loads(resp.choices[0].message.content)
                return {
                    "recipe_uid":  recipe_uid,
                    "flow_id":     flow_id,
                    "version_no":  version_no,
                    "description": result["description"],
                    "usage":       result["usage"],
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
# Pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(recipes: pd.DataFrame, done: dict[str, dict]) -> list[dict]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    results: list[dict] = list(done.values())
    pending = recipes[~recipes["recipe_uid"].isin(done)]

    log.info(f"Total: {len(recipes)} | Done: {len(done)} | Pending: {len(pending)}")

    tasks = {
        asyncio.create_task(
            generate_one(semaphore, row["recipe_uid"], row["flow_id"], row["version_no"], row["search_text"])
        ): row["recipe_uid"]
        for _, row in pending.iterrows()
    }

    completed = 0
    for coro in asyncio.as_completed(tasks):
        result = await coro
        completed += 1
        if result:
            results.append(result)
        if completed % CHECKPOINT_EVERY == 0 or completed == len(pending):
            save_checkpoint([r for r in results if r], CHECKPOINT_PARQUET)
            log.info(f"Checkpoint: {completed}/{len(pending)} done, {len(results)} results")

    return results

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    log.info(f"Loading {INPUT_PARQUET}")
    recipes = pd.read_parquet(INPUT_PARQUET)
    log.info(f"Loaded {len(recipes)} recipes")

    done = load_checkpoint(CHECKPOINT_PARQUET)
    log.info(f"Checkpoint: {len(done)} already done")

    results = await run_pipeline(recipes, done)

    desc_df = pd.DataFrame([r for r in results if r])[
        ["recipe_uid", "description", "usage"]
    ]

    merged = recipes.merge(desc_df, on="recipe_uid", how="left")
    merged.to_parquet(OUTPUT_PARQUET, index=False)
    log.info(f"Done. {len(desc_df)} descriptions merged. Saved to {OUTPUT_PARQUET}")


if __name__ == "__main__":
    asyncio.run(main())
