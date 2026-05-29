import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import httpx
import openai
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from config import (
    SUMMARIES_PATH,
    ENV_PATH,
    INFRA_CONNECTOR_FREQ,
    LLM_BACKOFF_BASE,
    LLM_MAX_ATTEMPTS,
    MAX_CONNECTOR_OVERLAP,
    MIN_CONNECTORS,
)

load_dotenv(ENV_PATH)


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

def make_openai_client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at the LiteLLM proxy."""
    return OpenAI(
        api_key=os.getenv("API_KEY"),
        base_url=os.getenv("BASE_URL"),
        http_client=httpx.Client(verify=False),
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_tracking_data() -> tuple[dict, dict]:
    """
    Load recipe data from recipe_summaries.parquet.

    Returns
    -------
    author_index : dict[int, list[dict]]
        author_id → list of recipe dicts with keys:
        flow_id, version_no, connectors (list[str]), step_count (int)

    summary_index : dict[tuple, str]
        (flow_id, version_no) → recipe_summary string
    """
    df = pd.read_parquet(SUMMARIES_PATH)

    author_index: dict[int, list] = {}
    for row in df.itertuples(index=False):
        author_index.setdefault(row.author_id, []).append({
            "flow_id":    row.flow_id,
            "version_no": row.version_no,
            "connectors": list(row.connectors),
            "step_count": row.step_count,
        })

    summary_index: dict[tuple, str] = {
        (row.flow_id, row.version_no): row.recipe_summary_with_comment
        for row in df.itertuples(index=False)
    }

    return author_index, summary_index


def load_corpus_texts() -> dict[tuple, dict]:
    """
    Load both text variants for every recipe from recipe_summaries.parquet.

    Returns
    -------
    dict[(flow_id, version_no) → {"text": str, "text_no_comments": str}]

    Used by PrepareCorpus to build the pgvector ingestion CSV — the only
    place that needs recipe_summary_without_comment.
    """
    df = pd.read_parquet(SUMMARIES_PATH)
    return {
        (row.flow_id, row.version_no): {
            "text":             row.recipe_summary_with_comment,
            "text_no_comments": row.recipe_summary_without_comment,
        }
        for row in df.itertuples(index=False)
    }


# ---------------------------------------------------------------------------
# Seed selection
# ---------------------------------------------------------------------------

def get_infra_connectors(recipes: list[dict]) -> set[str]:
    """Return connectors present in more than INFRA_CONNECTOR_FREQ of the recipes."""
    freq = Counter(c for r in recipes for c in r["connectors"])
    return {c for c, cnt in freq.items() if cnt / len(recipes) > INFRA_CONNECTOR_FREQ}


def select_recipe_seeds(recipes: list[dict]) -> list[dict]:
    """
    Greedily select diverse seed recipes for one author (no cap).

    Steps:
      1. Identify infrastructure connectors (present in >INFRA_CONNECTOR_FREQ of recipes).
      2. Rank by total distinct connectors desc, step_count desc.
      3. Skip recipes whose signal connector set (connectors minus infra) is empty.
      4. Skip recipes with fewer than MIN_CONNECTORS total distinct connectors.
      5. Pick every recipe whose signal connectors overlap <=MAX_CONNECTOR_OVERLAP
         with every already-selected seed.
    """
    infra  = get_infra_connectors(recipes)
    ranked = sorted(
        recipes,
        key=lambda r: (len(set(r["connectors"])), r["step_count"]),
        reverse=True,
    )

    selected: list[dict] = []
    selected_sig_sets: list[set] = []

    for candidate in ranked:
        sig = set(candidate["connectors"]) - infra
        if not sig:
            continue
        if len(set(candidate["connectors"])) < MIN_CONNECTORS:
            continue
        too_similar = any(
            min(len(sig), len(s_sig)) > 0
            and len(sig & s_sig) / min(len(sig), len(s_sig)) > MAX_CONNECTOR_OVERLAP
            for s_sig in selected_sig_sets
        )
        if not too_similar:
            selected.append(candidate)
            selected_sig_sets.append(sig)

    return selected


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def build_recipes_block(recipes: list[dict], summary_index: dict) -> str:
    """Format a list of recipes into an LLM prompt block keyed by flow_id."""
    parts = []
    for r in recipes:
        summary = summary_index.get((r["flow_id"], r["version_no"]), "(no summary available)")
        parts.append(f"[flow_id={r['flow_id']}]\n{summary}")
    return "\n\n---\n\n".join(parts)


def call_llm(
    client: OpenAI,
    system: str,
    user: str,
    max_tokens: int = 800,
    model: str = "azure/gpt-5.2",
    temperature: float = 0.0,
    label: str = "",
) -> str | None:
    """
    Robust single-turn LLM call; returns raw text content.
    Retries up to LLM_MAX_ATTEMPTS times with exponential backoff on API errors.
    Returns None if all attempts fail.
    """
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except (openai.RateLimitError, openai.APITimeoutError, openai.APIError) as e:
            _retry_wait(str(e), label, attempt)
    return None


def call_llm_json(
    client: OpenAI,
    system: str,
    user: str,
    max_tokens: int = 800,
    model: str = "azure/gpt-5.2",
    temperature: float = 0.0,
    label: str = "",
) -> dict | list | None:
    """
    Robust single-turn LLM call; parses and returns the JSON response.
    Retries up to LLM_MAX_ATTEMPTS times with exponential backoff on both
    API errors and JSON parse errors.
    Returns None if all attempts fail.
    """
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return json.loads(strip_fences(resp.choices[0].message.content.strip()))
        except json.JSONDecodeError:
            _retry_wait("JSON parse error", label, attempt)
        except (openai.RateLimitError, openai.APITimeoutError, openai.APIError) as e:
            _retry_wait(str(e), label, attempt)
    return None


def _retry_wait(reason: str, label: str, attempt: int) -> None:
    """Log a retry message and sleep with exponential backoff, or log final failure."""
    prefix = f"[{label}] " if label else ""
    if attempt < LLM_MAX_ATTEMPTS - 1:
        wait = LLM_BACKOFF_BASE ** attempt
        print(f"    {prefix}{reason} — retrying in {wait}s ({attempt + 1}/{LLM_MAX_ATTEMPTS}) ...")
        time.sleep(wait)
    else:
        print(f"    {prefix}{reason} — all {LLM_MAX_ATTEMPTS} attempts failed")


def strip_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$",          "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def make_recipe_uid(row: pd.Series) -> str:
    return (
        f"{int(row['candidate_author_id'])}"
        f"_{int(row['candidate_flow_id'])}"
        f"_v{int(row['candidate_version_no'])}"
    )


def source_in_both_strong(group: pd.DataFrame) -> bool:
    """
    Return True if the source recipe is Strongly Related.

    Uses `relevance_final` (post-adjudication) when present,
    otherwise requires both models to agree on Strongly Related.
    """
    src      = group["source_flow_id"].iloc[0]
    src_rows = group[group["candidate_flow_id"] == src]
    if src_rows.empty:
        return False
    if "relevance_final" in src_rows.columns:
        return (src_rows["relevance_final"] == "Strongly Related").any()
    in_gpt52  = (src_rows["relevance_gpt52"]  == "Strongly Related").any()
    in_claude = (src_rows["relevance_claude"] == "Strongly Related").any()
    return bool(in_gpt52 and in_claude)


def summarise_query_group(g: pd.DataFrame) -> pd.Series:
    """
    Groupby-apply: build strong/weak candidate UID lists for one query.

    Uses `relevance_final` (post-adjudication) when present:
      strong — relevance_final == "Strongly Related"
      weak   — relevance_final == "Weakly Related"

    Falls back to dual-model agreement logic when relevance_final is absent:
      strong — both models Strongly Related
      weak   — both positive but not both Strong (S/W, W/S, W/W)
    """
    if "relevance_final" in g.columns and g["relevance_final"].notna().any():
        strong_mask = g["relevance_final"] == "Strongly Related"
        weak_mask   = g["relevance_final"] == "Weakly Related"
    else:
        POSITIVE     = {"Strongly Related", "Weakly Related"}
        both_strong  = (g["relevance_gpt52"] == "Strongly Related") & (g["relevance_claude"] == "Strongly Related")
        both_pos     = g["relevance_gpt52"].isin(POSITIVE) & g["relevance_claude"].isin(POSITIVE)
        strong_mask  = both_strong
        weak_mask    = both_pos & ~both_strong

    strong_uids = g.loc[strong_mask, "recipe_uid"].tolist()
    weak_uids   = g.loc[weak_mask,   "recipe_uid"].tolist()
    return pd.Series({
        "strong_list":  ", ".join(sorted(strong_uids)),
        "strong_count": len(strong_uids),
        "weak_list":    ", ".join(weak_uids),
        "weak_count":   len(weak_uids),
    })
