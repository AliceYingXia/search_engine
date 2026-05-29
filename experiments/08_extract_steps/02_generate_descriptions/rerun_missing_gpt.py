"""Rerun the 3 queries missing from golden_answers.parquet and append results."""

import asyncio
import json
import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from generate_golden_answers import call_gpt, SYSTEM_PROMPT, INPUT_PARQUET, OUTPUT_PARQUET

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MISSING = [
    ("What steps in recipes call the profiles endpoint?", "url"),
    ("What steps in recipes take details from a Jira issue and use them to create or update a record in another system?", "action"),
    ("What steps in recipes call the repos/workato/workato/merges endpoint?", "url"),
]

MAX_CONCURRENT = 40

async def main():
    df = pd.read_parquet(INPUT_PARQUET)
    df["search_text_len"] = df["search_text"].str.len()
    recipes = df[df["search_text_len"] > 10000].reset_index(drop=True)
    log.info(f"Recipes: {len(recipes)}")

    existing = pd.read_parquet(OUTPUT_PARQUET)
    all_records = existing.to_dict("records")
    log.info(f"Existing records: {len(existing)}")

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    for query, query_type in MISSING:
        log.info(f"Running: '{query[:70]}'")
        tasks = [call_gpt(sem, query, row["search_text"]) for _, row in recipes.iterrows()]
        results = await asyncio.gather(*tasks)

        hits = 0
        for (_, row), steps in zip(recipes.iterrows(), results):
            for step in steps:
                all_records.append({
                    "query": query,
                    "query_type": query_type,
                    "recipe_uid": row["recipe_uid"],
                    "step": step.strip(),
                })
                hits += 1
        log.info(f"  → {hits} matched steps")

    out_df = pd.DataFrame(all_records)
    out_df.to_parquet(OUTPUT_PARQUET, index=False)
    log.info(f"Done. {len(out_df)} total records saved.")

if __name__ == "__main__":
    asyncio.run(main())
