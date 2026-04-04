"""
eval_utils.py
=============

Shared utilities for the Category 1 and Category 2 evaluation pipelines.

  make_openai_client()   — configured OpenAI client
  load_tracking_data()   — author_index and summary_index from cleaned/
  get_infra_connectors() — per-author infrastructure connector set
  select_recipe_seeds()  — greedy diverse seed recipe selection

Imported by build_eval_category1_*.py and build_eval_category2_*.py.
"""

import json
import os
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE       = Path(__file__).parent
CLEANED_DIR = _HERE.parent / "02_cleaning" / "cleaned"
ENV_PATH    = _HERE.parent.parent / ".env"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MAX_CONNECTOR_OVERLAP = 0.50   # max signal-connector overlap between any two seeds
INFRA_CONNECTOR_FREQ  = 0.50   # connectors in >50% of an author's recipes are infra
MIN_CONNECTORS        = 3      # seeds must have at least this many total distinct connectors

load_dotenv(ENV_PATH)


# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------

def make_openai_client() -> OpenAI:
    """
    Return an OpenAI-compatible client pointed at the LiteLLM proxy.
    Reads API_KEY and BASE_URL from .env.
    verify=False works around corporate SSL inspection proxies.
    """
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
    Parse all tracking and semantic JSON files in cleaned/.

    Returns
    -------
    author_index : dict[int, list[dict]]
        author_id → list of recipe dicts, each with keys:
        flow_id, version_no, connectors (list[str]), step_count (int)

    summary_index : dict[tuple, str]
        (flow_id, version_no) → recipe_summary string
    """
    author_index: dict[int, list] = {}
    summary_index: dict[tuple, str] = {}

    for tf in sorted(CLEANED_DIR.glob("*_tracking.json")):
        trk = json.loads(tf.read_text())
        author_index.setdefault(trk["author_id"], []).append({
            "flow_id":    trk["flow_id"],
            "version_no": trk["version_no"],
            "connectors": trk.get("connectors", []),
            "step_count": len(trk.get("steps", [])),
        })

    for sf in sorted(CLEANED_DIR.glob("*_semantic.json")):
        sem = json.loads(sf.read_text())
        summary_index[(sem["flow_id"], sem["version_no"])] = sem["recipe_summary"]

    return author_index, summary_index


# ---------------------------------------------------------------------------
# Seed selection
# ---------------------------------------------------------------------------

def get_infra_connectors(recipes: list[dict]) -> set[str]:
    """
    Return connectors present in more than INFRA_CONNECTOR_FREQ of the recipes.
    These are boilerplate connectors (e.g. workato_recipe_function,
    workato_variable) that inflate similarity between otherwise unrelated
    recipes and are excluded from the diversity overlap check.
    """
    freq = Counter(c for r in recipes for c in r["connectors"])
    return {c for c, cnt in freq.items() if cnt / len(recipes) > INFRA_CONNECTOR_FREQ}


def select_recipe_seeds(recipes: list[dict]) -> list[dict]:
    """
    Select all diverse seed recipes for one author (no cap).

    Selection steps:
      1. Identify infrastructure connectors (present in >INFRA_CONNECTOR_FREQ
         of the author's recipes).
      2. Rank recipes by total distinct connectors desc, step_count desc.
      3. Skip recipes whose signal connector set (connectors minus infra)
         is empty — their only connectors are infrastructure.
      4. Skip recipes with fewer than MIN_CONNECTORS total distinct connectors.
      5. Greedily pick every remaining recipe whose *signal* connector set
         overlaps <= MAX_CONNECTOR_OVERLAP with every already-selected seed.

    Overlap = |intersection(signal_A, signal_B)| / min(|signal_A|, |signal_B|).
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
        too_similar = False
        for s_sig in selected_sig_sets:
            denom = min(len(sig), len(s_sig))
            if denom == 0:
                continue
            if len(sig & s_sig) / denom > MAX_CONNECTOR_OVERLAP:
                too_similar = True
                break
        if not too_similar:
            selected.append(candidate)
            selected_sig_sets.append(sig)

    return selected
