"""Phase 2.5 — Adjudicate Disagreements.

Reads the raw relevance CSV from Phase 2, finds every row where GPT-5.2 and
Claude disagree (one says Strongly Related, the other Weakly Related), and
runs a focused third LLM call to produce a final verdict.

Adds a `relevance_final` column to every row:
  - S/S agreement  →  "Strongly Related"   (no LLM call)
  - W/W agreement  →  "Weakly Related"     (no LLM call)
  - S/W or W/S     →  adjudicator decision (LLM call)

Phase 3 (filter_dataset) uses `relevance_final` for strong/weak classification
when this column is present, replacing the original dual-model agreement logic.

Progress is checkpointed per query so the run can be safely interrupted.
"""

import json
from pathlib import Path

import pandas as pd
from openai import OpenAI

from config import CHUNK_SIZE, MODEL_GPT52
from pipeline.query_styles import QueryStyle
from utils import call_llm_json

_SYSTEM_ADJUDICATE_TEMPLATE = """\
You are resolving labelling disagreements in a relevance evaluation dataset \
for a semantic search system over Workato automation recipes.

Two models disagreed on whether each recipe below is Strongly Related or \
Weakly Related to a search query. Your job is to make the final call.

{label_definitions}

For each recipe, return your final verdict.

Return a single JSON object mapping each flow_id (as a string key) to either
"Strongly Related" or "Weakly Related".

Return ONLY valid JSON — no markdown fences, no explanation."""


def adjudicate_disagreements(
    style: QueryStyle,
    client: OpenAI,
    raw_path: Path,
    summary_index: dict,
    output_path: Path,
    checkpoint_path: Path,
    model: str = MODEL_GPT52,
) -> None:
    """Resolve S/W and W/S disagreements; write adjudicated CSV with relevance_final."""
    system_prompt = _SYSTEM_ADJUDICATE_TEMPLATE.format(
        label_definitions=style.relevance_definitions
    )

    df = pd.read_csv(raw_path)

    done: set[str] = set()
    if checkpoint_path.exists():
        done = set(json.loads(checkpoint_path.read_text()))
        print(f"Resuming — {len(done)} queries already adjudicated.\n")

    # Identify disagreement mask: S/W or W/S (both positive, labels differ)
    pos = {"Strongly Related", "Weakly Related"}
    disagree_mask = (
        df["relevance_gpt52"].isin(pos) &
        df["relevance_claude"].isin(pos) &
        (df["relevance_gpt52"] != df["relevance_claude"])
    )

    n_disagree = disagree_mask.sum()
    n_queries  = df.loc[disagree_mask, "query_id"].nunique()
    print(f"Disagreements found: {n_disagree} rows across {n_queries} queries")
    print(f"Agreement rows     : {(~disagree_mask).sum()} (no LLM call needed)\n")

    # Pre-fill relevance_final for all agreement rows
    df["relevance_final"] = df.apply(
        lambda r: r["relevance_gpt52"] if r["relevance_gpt52"] == r["relevance_claude"] else None,
        axis=1,
    )

    disagree_query_ids = df.loc[disagree_mask, "query_id"].unique()

    for idx, query_id in enumerate(disagree_query_ids, 1):
        if query_id in done:
            continue

        q_rows = df[(df["query_id"] == query_id) & disagree_mask]
        query  = q_rows["query"].iloc[0]

        print(f"[{idx:03d}/{len(disagree_query_ids)}] {query_id}  ({len(q_rows)} disagreement(s))")
        print(f'         Query: "{query}"')

        candidates = [
            {
                "flow_id":    int(row["candidate_flow_id"]),
                "version_no": int(row["candidate_version_no"]),
                "gpt52":      row["relevance_gpt52"],
                "claude":     row["relevance_claude"],
            }
            for _, row in q_rows.iterrows()
        ]

        # Chunk if many disagreements (guards against very long prompts)
        chunks = [candidates[i:i + CHUNK_SIZE] for i in range(0, len(candidates), CHUNK_SIZE)]
        adjudicated: dict[str, str] = {}

        for chunk in chunks:
            result = call_llm_json(
                client,
                system=system_prompt,
                user=_build_adjudication_block(query, chunk, summary_index),
                max_tokens=len(chunk) * 20 + 100,
                model=model,
                label=f"{query_id} adjudicate",
            )
            if result:
                adjudicated.update(result)

        # Write adjudicated labels back to df
        for _, row in q_rows.iterrows():
            fid      = str(int(row["candidate_flow_id"]))
            verdict  = adjudicated.get(fid)
            if verdict in {"Strongly Related", "Weakly Related"}:
                final = verdict
            else:
                # Adjudication failed for this row — take the stronger label
                final    = "Strongly Related" if "Strongly Related" in {row["relevance_gpt52"], row["relevance_claude"]} else "Weakly Related"
                verdict  = f"fallback → {final}"

            df.loc[
                (df["query_id"] == query_id) & (df["candidate_flow_id"] == row["candidate_flow_id"]),
                "relevance_final",
            ] = final
            print(f"         flow_id={fid}  {row['relevance_gpt52'][:2]}/{row['relevance_claude'][:2]} → {verdict}")

        print()
        done.add(query_id)
        checkpoint_path.write_text(json.dumps(sorted(done)))

    df.to_csv(output_path, index=False)

    # Summary
    if n_disagree > 0:
        resolved_strong = (df.loc[disagree_mask, "relevance_final"] == "Strongly Related").sum()
        resolved_weak   = n_disagree - resolved_strong
        print(f"Disagreements resolved: {resolved_strong} → Strong  {resolved_weak} → Weak")
    print(f"Saved → {output_path}  ({len(df)} rows, relevance_final added)\n")


def _build_adjudication_block(
    query: str, candidates: list[dict], summary_index: dict
) -> str:
    parts = []
    for c in candidates:
        summary = summary_index.get((c["flow_id"], c["version_no"]), "(no summary available)")
        parts.append(
            f"[flow_id={c['flow_id']}]\n"
            f"Model A said: {c['gpt52']}  |  Model B said: {c['claude']}\n"
            f"{summary}"
        )
    return f'Query: "{query}"\n\nRecipes to adjudicate:\n\n' + "\n\n---\n\n".join(parts)
