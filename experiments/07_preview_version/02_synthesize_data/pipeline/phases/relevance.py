"""Phase 2 — Exhaust Relevance.

For each query, sends every seed recipe (in chunks of CHUNK_SIZE) to both
GPT-5.2 and Claude independently. Rows where at least one model returns a
positive label are written to the output CSV. Progress is checkpointed after
each query so the run can be safely interrupted and resumed.
"""

import csv
import json
import random
from pathlib import Path

from openai import OpenAI

from config import CHUNK_SIZE, MODEL_CLAUDE, MODEL_GPT52, POSITIVE_LABELS
from pipeline.query_styles import QueryStyle
from utils import build_recipes_block, call_llm_json

_VALID_LABELS = {"Strongly Related", "Weakly Related", "Not Related"}

_SYSTEM_RELEVANCE_TEMPLATE = """\
You are helping build a ground-truth evaluation dataset for a semantic \
search system over Workato automation recipes.

A business user typed a search query. You are given a set of Workato recipes.

For each recipe, decide whether it is relevant to the query:

{label_definitions}

Return a single JSON object mapping each flow_id (as a string key) to one
of exactly these three labels. Include every flow_id in the response.

Return ONLY valid JSON — no markdown fences, no explanation."""

_FIELDNAMES = [
    "source_author_id", "query_id", "query", "source_flow_id",
    "candidate_flow_id", "candidate_version_no", "candidate_author_id",
    "candidate_connectors", "relevance_gpt52", "relevance_claude",
]


def exhaust_relevance(
    style: QueryStyle,
    client: OpenAI,
    queries_path: Path,
    author_index: dict,
    summary_index: dict,
    output_path: Path,
    checkpoint_path: Path,
) -> None:
    """Score every (query, seed recipe) pair with two models and write to CSV."""
    system_prompt = _SYSTEM_RELEVANCE_TEMPLATE.format(
        label_definitions=style.relevance_definitions
    )

    done: set[str] = set()
    if checkpoint_path.exists():
        done = set(json.loads(checkpoint_path.read_text()))
        print(f"Resuming — {len(done)} queries already processed.\n")

    queries = json.loads(queries_path.read_text())
    print(f"{len(queries)} queries loaded\n")

    all_seed_flow_ids: set[int] = {q["source_flow_id"] for q in queries}
    global_seeds: list[dict] = [
        {**r, "author_id": author_id}
        for author_id, recipes in author_index.items()
        for r in recipes
        if r["flow_id"] in all_seed_flow_ids
    ]
    print(f"Global seed pool: {len(global_seeds)} recipes\n")

    write_header = not output_path.exists() or len(done) == 0
    with output_path.open("w" if write_header else "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        if write_header:
            writer.writeheader()

        for idx, q in enumerate(queries, 1):
            query_id, author_id  = q["query_id"], q["author_id"]
            query, source_flow_id = q["query"], q["source_flow_id"]

            if query_id in done:
                continue

            # Shuffle per-query so each query sees recipes in a different order,
            # reducing systematic position bias ("lost in the middle" effect).
            shuffled = global_seeds.copy()
            random.shuffle(shuffled)
            chunks = [
                shuffled[i:i + CHUNK_SIZE]
                for i in range(0, len(shuffled), CHUNK_SIZE)
            ]
            print(
                f"[{idx:03d}/{len(queries)}] {query_id}  author={author_id}  "
                f"({len(global_seeds)} candidates, {len(chunks)} chunk(s))"
            )
            print(f'         Query: "{query}"')

            labels_gpt52:  dict[str, str] = {}
            labels_claude: dict[str, str] = {}

            for chunk_idx, chunk in enumerate(chunks, 1):
                chunk_block = build_recipes_block(chunk, summary_index)
                print(f"         Chunk {chunk_idx}/{len(chunks)} ({len(chunk)} seeds)")
                for model, labels in ((MODEL_GPT52, labels_gpt52), (MODEL_CLAUDE, labels_claude)):
                    print(f"           {model} ...", end=" ", flush=True)
                    result = _assess_relevance(client, query, chunk_block, model, system_prompt)
                    if result:
                        labels.update(result)
                        print(f"done ({len(result)} labels)")
                    else:
                        print("skipped (parse error)")

            if not labels_gpt52 and not labels_claude:
                print()
                continue

            _print_label_summary(labels_gpt52, labels_claude)

            for r in global_seeds:
                fid          = str(r["flow_id"])
                label_gpt52  = labels_gpt52.get(fid,  "Not Related")
                label_claude = labels_claude.get(fid, "Not Related")
                if label_gpt52 in POSITIVE_LABELS or label_claude in POSITIVE_LABELS:
                    writer.writerow({
                        "source_author_id":     author_id,
                        "query_id":             query_id,
                        "query":                query,
                        "source_flow_id":       source_flow_id,
                        "candidate_flow_id":    r["flow_id"],
                        "candidate_version_no": r["version_no"],
                        "candidate_author_id":  r["author_id"],
                        "candidate_connectors": ", ".join(r["connectors"]),
                        "relevance_gpt52":      label_gpt52,
                        "relevance_claude":     label_claude,
                    })
            f.flush()

            done.add(query_id)
            checkpoint_path.write_text(json.dumps(sorted(done)))


def _assess_relevance(
    client: OpenAI,
    query: str,
    recipes_block: str,
    model: str,
    system_prompt: str,
) -> dict[str, str]:
    """One LLM call for a chunk; returns flow_id → label, or {} on failure."""
    result = call_llm_json(
        client,
        system=system_prompt,
        user=f'Search query: "{query}"\n\nRecipes:\n{recipes_block}',
        max_tokens=2000,
        model=model,
        label=model,
    )
    if result is None:
        return {}
    return _validate_labels(result, model)


def _validate_labels(labels: dict, model: str) -> dict[str, str]:
    """Normalise any label outside the three valid values to 'Not Related'."""
    cleaned = {}
    for fid, label in labels.items():
        if label not in _VALID_LABELS:
            print(f"    [{model}] unexpected label {label!r} for flow_id={fid} — defaulting to 'Not Related'")
            cleaned[fid] = "Not Related"
        else:
            cleaned[fid] = label
    return cleaned


def _print_label_summary(labels_gpt52: dict, labels_claude: dict) -> None:
    for labels, name in ((labels_gpt52, "GPT-5.2"), (labels_claude, "Claude")):
        strong = sum(1 for v in labels.values() if v == "Strongly Related")
        weak   = sum(1 for v in labels.values() if v == "Weakly Related")
        print(f"         {name:<10} Strong={strong}  Weak={weak}")
    print()
